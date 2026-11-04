#include "bodaqs_control_authority.h"
#include <string.h>
static bool identical(const BodaqsControlRecord *a, const BodaqsControlRecord *b)
{
    uint8_t x[52], y[52];
    return bodaqs_control_encode_record(a, x) && bodaqs_control_encode_record(b, y) && !memcmp(x, y, 52);
}
static void result(const BodaqsControlRecord *q, BodaqsControlRecord *r, uint8_t reason, uint8_t field)
{
    *r = *q;
    r->data_length = 24;
    memset(r->data, 0, 24);
    r->data[0] = reason ? 1 : 0;
    r->data[1] = reason;
    r->data[2] = field;
    r->data[3] = q->opcode;
    if (q->opcode == BODAQS_CONTROL_BIND_SESSION || q->opcode == BODAQS_CONTROL_RELEASE_SESSION)
        bodaqs_control_put_u32(r->data + 4, q->operation);
    if (reason)
        r->opcode = BODAQS_CONTROL_ERROR;
}
void bodaqs_control_authority_init(BodaqsControlAuthority *s)
{
    memset(s, 0, sizeof(*s));
}
uint8_t bodaqs_control_authority_admit(BodaqsControlAuthority *s, const BodaqsControlNode *v,
                                       const BodaqsControlRecord *q)
{
    if (q->node_boot_id != v->boot_id)
        return 4;
    if (v->epoch_exhausted)
        return BODAQS_CONTROL_REASON_EXHAUSTED;
    if (!q->session || q->session != v->active_session)
        return 5;
    if (v->pending_operation)
        return 7;
    if (s->high_water == UINT32_MAX)
        return 22;
    if (q->operation <= s->high_water)
        return 12;
    if (q->operation != s->high_water + 1)
        return 24;
    return 0;
}
void bodaqs_control_authority_complete(BodaqsControlAuthority *s, const BodaqsControlRecord *q,
                                       const BodaqsControlRecord *r)
{
    /* Late completion of a canceled operation never rewinds the authority. */
    if (q->operation < s->high_water && s->latest_valid && q->session == s->latest_request.session)
        return;
    s->high_water = q->operation;
    s->latest_request = *q;
    s->latest_result = *r;
    s->latest_valid = true;
}
bool bodaqs_control_authority_process(BodaqsControlAuthority *s, BodaqsControlNode *v, const BodaqsControlRecord *q,
                                      uint32_t now, BodaqsControlRandom64 random, void *ctx, BodaqsControlRecord *r)
{
    uint8_t reason = 0, field = 0;
    unsigned endpoint;
    if (q->opcode != BODAQS_CONTROL_GET_CHALLENGE && q->opcode != BODAQS_CONTROL_BIND_SESSION &&
        q->opcode != BODAQS_CONTROL_RELEASE_SESSION && q->opcode != BODAQS_CONTROL_GET_OPERATION)
        return false;
    if (!bodaqs_control_request_valid(q))
        return false;
    if (q->node_boot_id != v->boot_id)
    {
        result(q, r, 4, 5);
        return true;
    }
    if (v->epoch_exhausted)
    {
        result(q, r, BODAQS_CONTROL_REASON_EXHAUSTED, BODAQS_CONTROL_FIELD_SEQUENCE);
        return true;
    }
    if (q->opcode == BODAQS_CONTROL_GET_CHALLENGE)
    {
        if (q->session && q->session != v->active_session)
        {
            result(q, r, 5, 6);
            return true;
        }
        if (identical(q, &s->challenge_request) && s->challenge)
        {
            if ((uint32_t)(now - s->challenge_started) >= 5000 || !s->challenge_valid)
            {
                result(q, r, 20, 17);
                return true;
            }
        }
        else
        {
            if (s->challenge && q->operation == s->challenge_request.operation &&
                q->session == s->challenge_request.session)
            {
                result(q, r, 12, 18);
                return true;
            }
            uint64_t value = s->next_challenge;
            if (!s->challenge)
                value = random ? random(ctx) : 0;
            /* Entropy failure is explicit, with no predictable substitute. */
            if (!value || value == s->challenge)
            {
                result(q, r, 22, 17);
                return true;
            }
            s->next_challenge = value == UINT64_MAX ? 0 : value + 1;
            s->challenge = value;
            s->challenge_started = now;
            s->challenge_request = *q;
            s->proposed_session = bodaqs_control_get_u64(q->data);
            s->challenge_valid = true;
        }
        *r = *q;
        r->transfer = s->challenge;
        r->data_length = 4;
        memset(r->data, 0, 24);
        bodaqs_control_put_u32(r->data, 5000);
        return true;
    }
    if (q->opcode == BODAQS_CONTROL_GET_OPERATION)
    {
        uint32_t target = bodaqs_control_get_u32(q->data);
        if (q->session != v->active_session && !(s->release_valid && q->session == s->release_request.session))
        {
            result(q, r, 5, 6);
            return true;
        }
        if (s->latest_valid && q->session == s->latest_request.session && target == s->latest_request.operation)
        {
            *r = *q;
            r->data_length = 24;
            memcpy(r->data, s->latest_result.data, 24);
            r->data[3] = BODAQS_CONTROL_GET_OPERATION;
            bodaqs_control_put_u32(r->data + 4, target);
            return true;
        }
        result(q, r, 0, 0);
        r->data[0] = 6;
        r->data[1] = (q->session == v->active_session && target < s->high_water) ? 13 : 19;
        bodaqs_control_put_u32(r->data + 4, target);
        return true;
    }
    if (q->opcode == BODAQS_CONTROL_BIND_SESSION && s->bound_retry && identical(q, &s->bind_request) &&
        v->active_session == q->session)
    {
        *r = s->bind_result;
        return true;
    }
    if (q->opcode == BODAQS_CONTROL_RELEASE_SESSION && s->release_valid && identical(q, &s->release_request))
    {
        *r = s->release_result;
        return true;
    }
    if (q->opcode == BODAQS_CONTROL_RELEASE_SESSION && (!q->session || q->session != v->active_session))
    {
        reason = 5;
        field = 6;
    }
    else if ((v->flags & (1U << 1)) &&
             !(q->opcode == BODAQS_CONTROL_BIND_SESSION && v->membership_cleanup_allowed))
    {
        reason = 8;
        field = 12;
    }
    else if (v->flags & ((1U << 2) | (1U << 3)))
    {
        reason = 21;
        field = 13;
    }
    else if (v->pending_operation || (v->flags & ((1U << 4) | (1U << 5))))
    {
        reason = 7;
        field = 18;
    }
    else if (q->opcode == BODAQS_CONTROL_BIND_SESSION)
    {
        if (!s->challenge_valid || s->proposed_session != q->session || s->challenge != q->transfer ||
            (uint32_t)(now - s->challenge_started) >= 5000)
        {
            reason = 20;
            field = 17;
        }
        else if (q->session == v->active_session || (s->release_valid && q->session == s->release_request.session))
        {
            reason = 12;
            field = 6;
        }
    }
    else
    {
        reason = bodaqs_control_authority_admit(s, v, q);
        field = reason ? 18 : 0;
    }
    if (!reason)
    {
        for (endpoint = 0; endpoint < 6; endpoint++)
        {
            if ((v->endpoint_mask & (1U << endpoint)) && v->endpoint_epoch[endpoint] == UINT64_MAX)
            {
                reason = 22;
                field = 18;
                break;
            }
        }
    }
    result(q, r, reason, field);
    if (reason)
        return true;
    /* Authority changes eligibility, never the accepted hardware provenance. */
    for (endpoint = 0; endpoint < 6; endpoint++)
        if (v->endpoint_mask & (1U << endpoint))
            ++v->endpoint_epoch[endpoint];
    if (q->opcode == BODAQS_CONTROL_BIND_SESSION)
    {
        v->active_session = q->session;
        v->flags |= 1;
        s->challenge_valid = false;
        s->release_valid = false;
        s->bind_request = *q;
        s->bind_result = *r;
        s->bound_retry = true;
    }
    else
    {
        v->active_session = 0;
        v->flags &= ~1U;
        s->release_request = *q;
        s->release_result = *r;
        s->release_valid = true;
        s->bound_retry = false;
    }
    bodaqs_control_authority_complete(s, q, r);
    return true;
}
