#include "bodaqs_control_acquisition.h"
#include <string.h>
static bool same(const BodaqsControlRecord *a, const BodaqsControlRecord *b)
{
    uint8_t x[52], y[52];
    return bodaqs_control_encode_record(a, x) && bodaqs_control_encode_record(b, y) &&
           !memcmp(x, y, 52);
}
static bool zero(const uint8_t *p, unsigned n)
{
    while (n--)
        if (*p++)
            return false;
    return true;
}
/* Unbound fallback is a 1ms-quantized nominal-us counter, not native timing
 * qualification. #169 binds the actual capture clock used by sample boundaries. */
static uint32_t wire_tick(BodaqsControlAcquisition *s, uint32_t milliseconds)
{
    uint32_t clock_epoch = s->node_clock_epoch;
    uint32_t tick = s->clock ? s->clock(s->clock_context, &clock_epoch) : milliseconds * 1000U;
    if (s->clock)
    {
        if (s->recording && s->node_clock_epoch && clock_epoch != s->node_clock_epoch)
            bodaqs_control_acquisition_exclude(s, 35);
        s->node_clock_epoch = clock_epoch;
    }
    return tick;
}
bool bodaqs_control_acquisition_set_clock(BodaqsControlAcquisition *s, BodaqsAcquisitionClock clock,
                                          void *context)
{
    if (s->staging || s->recording)
        return false;
    s->clock = clock;
    s->clock_context = context;
    return true;
}
static bool reached(uint32_t now, uint32_t deadline) { return (int32_t)(now - deadline) >= 0; }
static void result(BodaqsControlAcquisition *s, const BodaqsControlRecord *q,
                   BodaqsControlRecord *r, uint8_t kind, uint8_t reason)
{
    *r = *q;
    r->data_length = 24;
    memset(r->data, 0, 24);
    r->data[0] = kind;
    r->data[1] = reason;
    r->data[2] = reason == 4                                      ? 5
                 : reason == 5                                    ? 6
                 : reason == 6                                    ? 8
                 : reason == 20                                   ? 17
                 : reason == 22                                   ? 18
                 : reason == 28                                   ? 20
                 : reason == 33                                   ? 25
                 : reason == 35                                   ? 23
                 : (reason == 27 || reason == 29 || reason == 30) ? 21
                 : reason                                         ? 1
                                                                  : 0;
    r->data[3] = q->opcode;
    bodaqs_control_put_u32(r->data + 4, q->operation);
    (void)s; /* Node-wide generic result retains existing zero revision/generation. */
    if (kind == 1)
        r->opcode = 127;
}
static bool epoch(BodaqsControlAcquisition *s)
{
    if (s->view->epoch_exhausted || s->view->endpoint_epoch[0] == UINT64_MAX)
    {
        s->view->epoch_exhausted = true;
        return false;
    }
    ++s->view->endpoint_epoch[0];
    return true;
}
static void historical(BodaqsControlAcquisition *s)
{
    bodaqs_control_put_u32(s->effective + 16, bodaqs_control_get_u32(s->effective + 12));
    bodaqs_control_put_u32(s->effective + 20, 32);
    s->view->flags &= ~(1U << 8);
}
static void publish(BodaqsControlAcquisition *s, uint8_t kind, uint8_t reason)
{
    BodaqsControlRecord r;
    if (!s->pending.operation)
        return;
    result(s, &s->pending, &r, kind, reason);
    /* An older delayed backend completion cannot replace a newer STOP. */
    if (s->pending.operation == s->authority->high_water &&
        s->pending.session == s->view->active_session)
        bodaqs_control_authority_complete(s->authority, &s->pending, &r);
    if (kind != 2)
    {
        s->view->pending_operation = 0;
        s->pending.operation = 0;
    }
}
static bool command(BodaqsControlAcquisition *s, uint8_t action)
{
    if (s->generation == UINT32_MAX)
    {
        s->view->epoch_exhausted = true;
        if (action != BODAQS_ACQ_STOP)
            return false;
        s->command = action;
        s->command_sent = false;
        return true;
    }
    ++s->generation;
    s->command = action;
    s->command_sent = false;
    return true;
}
void bodaqs_control_acquisition_init(BodaqsControlAcquisition *s, BodaqsControlAuthority *a,
                                     BodaqsControlNode *v, uint8_t effective[192],
                                     BodaqsAcquisitionBackend backend, void *context)
{
    memset(s, 0, sizeof(*s));
    s->authority = a;
    s->view = v;
    s->effective = effective;
    s->backend = backend;
    s->backend_context = context;
    s->stopped = true;
    s->fenced = true;
}
void bodaqs_control_acquisition_exclude(BodaqsControlAcquisition *s, uint8_t reason)
{
    if (!s->recording || s->terminal)
        return;
    s->lease_valid = false;
    s->challenge_valid = false;
    s->terminal = true;
    s->terminated_record = s->recording;
    s->terminated_session = s->owner;
    s->ready = false;
    s->reason = reason;
    s->phase = 4;
    s->stopped = false;
    s->view->flags = (s->view->flags & ~12U) | 2U;
    historical(s);
    (void)epoch(s);
    (void)command(s, BODAQS_ACQ_STOP);
    publish(s, 5, reason);
}
static bool proof(BodaqsControlAcquisition *s, const BodaqsControlRecord *q, uint32_t now,
                  bool initial)
{
    return s->challenge_valid && !reached(now, s->issued_ms + 300U) &&
           bodaqs_control_get_u64(q->data) == bodaqs_control_get_u64(s->challenge_request.data) &&
           bodaqs_control_get_u64(q->data + 8) == s->challenge &&
           bodaqs_control_get_u32(q->data + 16) ==
               bodaqs_control_get_u32(s->challenge_request.data + 8) &&
           q->session == s->challenge_request.session &&
           s->challenge_request.data[12] == (initial ? 0 : 1) &&
           (!initial || q->transfer == s->challenge_request.transfer);
}
void bodaqs_control_acquisition_tick(BodaqsControlAcquisition *s, uint32_t now)
{
    BodaqsAcquisitionEvent e;
    if (s->clock)
        (void)wire_tick(s, now);
    if (s->staging && (uint32_t)(now - s->staged_ms) >= 5000)
    {
        s->staging = false;
        s->challenge_valid = false;
        publish(s, 5, 10);
        s->view->flags &= ~32U;
    }
    if (s->recording && !s->terminal)
    {
        if (s->view->epoch_exhausted)
            bodaqs_control_acquisition_exclude(s, 22);
        else if (s->view->active_session != s->owner)
            bodaqs_control_acquisition_exclude(s, 5);
        else if ((s->view->flags & 128U))
            bodaqs_control_acquisition_exclude(s, 35);
        else if (s->lease_valid && reached(now, s->lease_deadline))
            bodaqs_control_acquisition_exclude(s, 29);
        else if (s->phase == 1 && (uint32_t)(now - s->prepared_ms) >= 5000)
            bodaqs_control_acquisition_exclude(s, 18);
    }
    if (s->challenge_valid && reached(now, s->issued_ms + 300U))
        s->challenge_valid = false;
    if (!s->backend || (!s->command && !s->recording))
        return;
    memset(&e, 0, sizeof(e));
    s->backend(s->backend_context, (!s->command || s->command_sent) ? (uint8_t)BODAQS_ACQ_POLL : s->command,
               s->generation, s->recording, now, &e);
    s->command_sent = true;
    if (e.kind == 0 || e.generation != s->generation)
        return;
    if (!s->clock)
        s->node_clock_epoch = e.node_clock_epoch;
    if (s->clock && e.node_clock_epoch != s->node_clock_epoch)
    {
        bodaqs_control_acquisition_exclude(s, 35);
        return;
    }
    s->sensor_clock_epoch = e.sensor_clock_epoch;
    if (e.kind == BODAQS_ACQ_FAILED)
    {
        if (!s->terminal)
            bodaqs_control_acquisition_exclude(s, e.reason ? e.reason : 27);
        else
        {
            s->reason = e.reason ? e.reason : 27;
            s->command = 0;
            publish(s, 5, s->reason);
        }
        return;
    }
    if (e.kind == BODAQS_ACQ_READY && s->phase == 1 && !s->terminal && e.register_proof_current)
    {
        s->phase = 2;
        s->ready = true;
        s->command = 0;
    }
    else if (e.kind == BODAQS_ACQ_FIRST && s->phase == 2 && s->command == BODAQS_ACQ_START &&
             !s->terminal && (e.boundary[9] & 7) == 7 && !(e.boundary[9] & ~15U) &&
             bodaqs_control_get_u32(e.boundary) == 0 && zero(e.boundary + 10, 6))
    {
        memcpy(s->first, e.boundary, 16);
        s->first_valid = true;
        s->known_empty = false;
        s->phase = 3;
        s->command = 0;
        s->view->flags = (s->view->flags & ~4U) | 8U;
    }
    else if (e.kind == BODAQS_ACQ_STOPPED && s->terminal && s->command == BODAQS_ACQ_STOP &&
             e.register_proof_current)
    {
        s->phase = 5;
        s->stopped = true;
        s->known_empty = e.known_empty && !s->first_valid;
        if ((e.boundary[9] & 7) == 7 && !(e.boundary[9] & ~15U) && zero(e.boundary + 10, 6))
        {
            memcpy(s->final, e.boundary, 16);
            s->final_valid = true;
        }
        s->command = 0;
        s->view->flags &= ~12U;
        s->view->membership_cleanup_allowed = true;
    }
    else if (e.kind == BODAQS_ACQ_FENCED && s->stopped && s->command == BODAQS_ACQ_FENCE)
    {
        s->fenced = true;
        s->command = 0;
        (void)epoch(s);
        publish(s, 3, 0);
        return;
    }
    else
        return;
    if (!epoch(s))
    {
        bodaqs_control_acquisition_exclude(s, 22);
        return;
    }
    if (e.register_proof_current)
    {
        memcpy(s->effective + 152, e.register_image, 24);
        bodaqs_control_put_u32(s->effective + 108, now);
        bodaqs_control_put_u32(s->effective + 16,
                               bodaqs_control_get_u32(s->effective + 16) & ~0x400U);
        bodaqs_control_put_u32(s->effective + 20, s->stopped ? 3 : 0);
    }
    publish(s, 3, 0);
}
static uint8_t validate_stage(BodaqsControlAcquisition *s)
{
    unsigned i;
    if (s->pages != 31)
        return 11;
    if (memcmp(s->staged, s->begin.data, 16) || !zero(s->staged + 24, 40) ||
        !zero(s->staged + 72, 40))
        return 24;
    if (bodaqs_control_get_u64(s->staged + 16) != bodaqs_control_get_u64(s->effective + 32))
        return 6;
    if (bodaqs_control_get_u64(s->staged + 64) != s->view->endpoint_epoch[0])
        return 6;
    for (i = 0; i < 6; ++i)
        if (i && (bodaqs_control_get_u64(s->staged + 16 + 8 * i) ||
                  bodaqs_control_get_u64(s->staged + 64 + 8 * i)))
            return 24;
    if (s->effective[4] != 2 || (s->view->flags & 128U) ||
        !(bodaqs_control_get_u32(s->effective + 20) & 1U))
        return 27;
    return 0;
}
bool bodaqs_control_acquisition_process(BodaqsControlAcquisition *s, const BodaqsControlRecord *q,
                                        uint32_t now, BodaqsControlRecord *r)
{
    uint8_t reason = 0, op = q->opcode;
    bool stage_op = op >= 0x20 && op <= 0x23;
    if (op < 0x20 || op > 0x2A || op == 0x28 || !bodaqs_control_request_valid(q))
        return false;
    bodaqs_control_acquisition_tick(s, now);
    if (q->node_boot_id != s->view->boot_id)
        reason = 4;
    else if (s->view->epoch_exhausted)
        reason = 22;
    else if (!q->session || q->session != s->view->active_session)
        reason = 5;
    if (reason)
    {
        result(s, q, r, 1, reason);
        return true;
    }
    if (op == 0x26)
    {
        uint32_t seq = bodaqs_control_get_u32(q->data + 8);
        bool initial = q->data[12] == 0;
        if (s->terminal)
            reason = 30;
        else if (initial)
        {
            if (!s->staging || q->transfer != s->begin.transfer || q->session != s->begin.session ||
                bodaqs_control_get_u64(q->data) != bodaqs_control_get_u64(s->begin.data + 8))
                reason = 28;
            else
                reason = validate_stage(s);
        }
        else if (!s->recording || bodaqs_control_get_u64(q->data) != s->recording ||
                 q->session != s->owner)
            reason = 28;
        else if (!s->lease_valid)
            reason = 29;
        if (!reason && s->challenge && q->operation == s->challenge_request.operation &&
            q->session == s->challenge_request.session)
        {
            if (!same(q, &s->challenge_request))
                reason = 12;
            else if (!s->challenge_valid)
                reason = 20;
        }
        else if (!reason)
        {
            if (seq <= s->renewal_sequence ||
                (s->challenge && seq <= bodaqs_control_get_u32(s->challenge_request.data + 8)))
                reason = 12;
            else if (!s->authority->next_challenge)
                reason = 22;
            else
            {
                s->challenge = s->authority->next_challenge;
                s->authority->next_challenge = s->challenge == UINT64_MAX ? 0 : s->challenge + 1;
                s->challenge_request = *q;
                s->issued_ms = now;
                s->issued_tick = wire_tick(s, now);
                s->challenge_valid = true;
            }
        }
        if (reason)
        {
            result(s, q, r, 1, reason);
            return true;
        }
        *r = *q;
        r->data_length = 24;
        memset(r->data, 0, 24);
        bodaqs_control_put_u64(r->data, s->challenge);
        bodaqs_control_put_u32(r->data + 8, s->issued_tick);
        bodaqs_control_put_u32(r->data + 12, s->issued_tick + 300000U);
        bodaqs_control_put_u32(r->data + 16, s->issued_tick + 1000000U);
        bodaqs_control_put_u32(r->data + 20, seq);
        return true;
    }
    if (op == 0x27)
    {
        if (s->terminal)
            reason = 30;
        else if (q->session != s->owner || bodaqs_control_get_u64(q->data) != s->recording)
            reason = 28;
        else if (!s->lease_valid)
            reason = 29;
        else if (s->renewal_valid && same(q, &s->renewal_request))
        {
            *r = s->renewal_result;
            return true;
        }
        else if (bodaqs_control_get_u32(q->data + 16) <= s->renewal_sequence)
            reason = 12;
        else if (!proof(s, q, now, false))
            reason = 20;
        if (reason)
        {
            result(s, q, r, 1, reason);
            return true;
        }
        s->lease_deadline = s->issued_ms + 1000U;
        s->lease_tick = s->issued_tick + 1000000U;
        s->renewal_sequence = bodaqs_control_get_u32(q->data + 16);
        s->challenge_valid = false;
        s->renewal_valid = true;
        s->renewal_request = *q;
        *r = *q;
        r->data_length = 24;
        memset(r->data, 0, 24);
        bodaqs_control_put_u64(r->data, s->recording);
        bodaqs_control_put_u32(r->data + 8, s->lease_tick);
        bodaqs_control_put_u32(r->data + 12, s->renewal_sequence);
        bodaqs_control_put_u64(r->data + 16, s->view->endpoint_epoch[0]);
        s->renewal_result = *r;
        return true;
    }
    if (stage_op && s->staged_valid && q->operation == s->begin.operation &&
        q->session == s->begin.session)
    {
        if (q->endpoint != s->begin.endpoint || q->transfer != s->begin.transfer)
            reason = 12;
        else if (op == 0x20 && !same(q, &s->begin))
            reason = 12;
        else if (op == 0x21 && (s->pages & (1U << q->page)) &&
                 memcmp(q->data, s->staged + 24 * q->page, q->data_length))
            reason = 12;
        else if (op == 0x22 && s->commit_valid && !same(q, &s->commit))
            reason = 12;
        if (reason)
        {
            if (s->staging && op == 0x21)
            {
                s->staging = false;
                s->challenge_valid = false;
                s->view->flags &= ~32U;
                publish(s, 5, 9);
            }
            result(s, q, r, 1, reason);
            return true;
        }
        if (!s->staging)
        {
            if (op == 0x23 && s->stage_aborted)
                result(s, q, r, 3, 0);
            else if (op == 0x23 && s->recording)
                result(s, q, r, 1, 9);
            else if (s->authority->high_water > s->begin.operation)
                result(s, q, r, 6, 13);
            else
            {
                *r = s->authority->latest_result;
                r->opcode = q->opcode;
                r->page = q->page;
                r->data[3] = q->opcode;
            }
            return true;
        }
        if (op == 0x20)
        {
            result(s, q, r, 2, 0);
            return true;
        }
        if (op == 0x21)
        {
            memcpy(s->staged + 24 * q->page, q->data, q->data_length);
            s->pages |= 1U << q->page;
            result(s, q, r, 2, 0);
            return true;
        }
        if (op == 0x23)
        {
            s->stage_aborted = true;
            s->staging = false;
            s->challenge_valid = false;
            s->view->flags &= ~32U;
            publish(s, 5, 9);
            result(s, q, r, 3, 0);
            return true;
        }
        reason = validate_stage(s);
        if (!reason && !proof(s, q, now, true))
            reason = 20;
        if (reason)
        {
            result(s, q, r, 1, reason);
            return true;
        }
        s->commit = *q;
        s->commit_valid = true;
        s->recording = bodaqs_control_get_u64(q->data);
        s->owner = q->session;
        s->renewal_sequence = bodaqs_control_get_u32(q->data + 16);
        s->lease_deadline = s->issued_ms + 1000U;
        s->lease_valid = true;
        s->lease_tick = s->issued_tick + 1000000U;
        s->challenge_valid = false;
        s->staging = false;
        s->phase = 1;
        s->prepared_ms = now;
        s->prepared_tick = wire_tick(s, now);
        s->view->membership_cleanup_allowed = false;
        s->fenced = false;
        s->stopped = false;
        s->known_empty = false;
        s->terminal = false;
        s->first_valid = false;
        s->final_valid = false;
        s->renewal_valid = false;
        s->reason = 0;
        s->ready = false;
        memset(s->first, 0, 16);
        memset(s->final, 0, 16);
        s->view->flags = (s->view->flags & ~32U) | 6U;
        historical(s);
        (void)epoch(s);
        (void)command(s, BODAQS_ACQ_PREPARE);
        result(s, q, r, 2, 0);
        publish(s, 2, 0);
        return true;
    }
    if (s->authority->latest_valid && q->operation == s->authority->latest_request.operation &&
        q->session == s->authority->latest_request.session)
    {
        if (same(q, &s->authority->latest_request))
            *r = s->authority->latest_result;
        else
            result(s, q, r, 1, 12);
        return true;
    }
    /* A protected STOP may overtake queued COMMIT. Staging has not touched
     * hardware or accepted membership, but its immutable proof must be revoked. */
    if (op == 0x25 && s->staging &&
        bodaqs_control_get_u64(q->data) == bodaqs_control_get_u64(s->begin.data + 8))
    {
        BodaqsControlNode admission = *s->view;
        admission.pending_operation = 0;
        reason = bodaqs_control_authority_admit(s->authority, &admission, q);
        if (reason)
        {
            result(s, q, r, 1, reason);
            return true;
        }
        s->staging = false;
        s->challenge_valid = false;
        s->terminal = true;
        s->terminated_record = bodaqs_control_get_u64(q->data);
        s->terminated_session = q->session;
        s->stopped = true;
        s->known_empty = true;
        s->fenced = false;
        s->pending.operation = 0;
        s->view->pending_operation = 0;
        s->view->flags &= ~32U;
        result(s, q, r, 3, 0);
        bodaqs_control_authority_complete(s->authority, q, r);
        return true;
    }
    /* STOP alone may supersede an accepted pending acquisition operation. */
    if (op == 0x25 && s->recording && !s->staging)
    {
        BodaqsControlNode admission = *s->view;
        admission.pending_operation = 0;
        reason = bodaqs_control_authority_admit(s->authority, &admission, q);
    }
    else
        reason = bodaqs_control_authority_admit(s->authority, s->view, q);
    if (!reason && stage_op && op != 0x20)
        reason = 19;
    if (!reason && op == 0x20)
    {
        if (s->recording || (s->view->flags & (2U | 12U)))
            reason = 8;
        else if (bodaqs_control_get_u64(q->data + 8) == s->terminated_record && q->session==s->terminated_session)
            reason = 30;
        else if (s->staged_valid && q->session == s->begin.session &&
                 q->transfer == s->begin.transfer)
            reason = 12;
        else if (!s->backend)
            reason = 27;
        else if (q->data[0] != 4 || q->data[1] || q->data[2] != 1 || q->data[3] ||
                 q->data[4] != 112 || q->data[5] || q->data[6] != 1 || q->data[7] ||
                 !bodaqs_control_get_u64(q->data + 8))
            reason = 24;
        else if (s->view->endpoint_epoch[0] >= UINT64_MAX - 4 || s->generation == UINT32_MAX)
            reason = 22;
    }
    else if (!reason)
    {
        /* A freshly bound cleanup owner can fence TX left by an earlier boot.
         * This creates only a bounded tombstone, never acquisition membership.
         * The hardware owner must still acknowledge retirement below. */
        if(op==0x2A && !s->recording && !s->staging && s->stopped && !s->lease_valid &&
           !s->command && (!s->terminated_record ||
             (!s->terminal && s->fenced && q->session!=s->terminated_session)) &&
           bodaqs_control_get_u64(q->data) &&
           s->authority->bound_retry && s->authority->bind_request.session==q->session) {
            s->terminal=true;s->terminated_record=bodaqs_control_get_u64(q->data);
            s->terminated_session=q->session;
            s->fenced=false;
        }
        bool canceled_stage = !s->recording && s->terminal &&
                              bodaqs_control_get_u64(q->data) == s->terminated_record &&
                              (op == 0x29 || op == 0x2A);
        if (!canceled_stage && (bodaqs_control_get_u64(q->data) != s->recording || !s->recording))
            reason = 28;
        else if (op == 0x24)
        {
            if (s->terminal)
                reason = 30;
            else if (!s->lease_valid)
                reason = 29;
            else if (s->phase != 2 || !s->ready)
                reason = 27;
            else if (bodaqs_control_get_u64(q->data + 8) != s->view->endpoint_epoch[0] ||
                     bodaqs_control_get_u64(q->data + 16) !=
                         bodaqs_control_get_u64(s->effective + 32))
                reason = 6;
        }
        else if (op == 0x29 || op == 0x2A)
        {
            if (!s->stopped || s->lease_valid)
                reason = 33;
            else if (op == 0x29 && !s->fenced)
                reason = 33;
        }
        else if (op != 0x25)
            reason = 1;
    }
    if (reason)
    {
        result(s, q, r, 1, reason);
        return true;
    }
    s->pending = *q;
    s->view->pending_operation = q->operation;
    result(s, q, r, 2, 0);
    bodaqs_control_authority_complete(s->authority, q, r);
    if (op == 0x20)
    {
        s->begin = *q;
        s->staged_valid = true;
        s->staging = true;
        s->pages = 0;
        s->staged_ms = now;
        s->commit_valid = false;
        s->stage_aborted = false;
        s->terminal = false;
        s->challenge_valid = false;
        s->challenge = 0;
        s->renewal_sequence = 0;
        memset(s->staged, 0, 112);
        s->view->flags |= 32U;
    }
    else if (op == 0x24)
    {
        (void)command(s, BODAQS_ACQ_START);
    }
    else if (op == 0x25)
    {
        if (!s->terminal)
        {
            s->terminal = true;
            s->terminated_record = s->recording;
            s->terminated_session = s->owner;
            s->lease_valid = false;
            s->challenge_valid = false;
            s->ready = false;
            s->phase = 4;
            s->stopped = false;
            s->view->flags = (s->view->flags & ~12U) | 2U;
            historical(s);
            (void)epoch(s);
            (void)command(s, BODAQS_ACQ_STOP);
        }
        else if (s->stopped)
            publish(s, 3, 0);
    }
    else if (op == 0x2A)
    {
        if (s->fenced)
        {
            s->fenced = true;
            publish(s, 3, 0);
        }
        else
            (void)command(s, BODAQS_ACQ_FENCE);
    }
    else if (op == 0x29)
    {
        s->recording = 0;
        s->owner = 0;
        s->first_valid = false;
        s->final_valid = false;
        s->known_empty = false;
        s->lease_deadline = 0;
        s->lease_tick = 0;
        s->challenge = 0;
        s->challenge_valid = false;
        memset(s->first, 0, 16);
        memset(s->final, 0, 16);
        s->phase = 0;
        s->terminal = false;
        s->reason = 0;
        s->view->flags &= ~2U;
        s->view->membership_cleanup_allowed = false;
        (void)epoch(s);
        publish(s, 3, 0);
    }
    *r = s->authority->latest_result;
    return true;
}
void bodaqs_control_acquisition_capture(void *context, const BodaqsControlNode *v, uint8_t d[128],
                                        uint32_t now)
{
    BodaqsControlAcquisition *s = (BodaqsControlAcquisition *)context;
    uint32_t captured_tick = wire_tick(s, now);
    uint32_t flags = (s->lease_valid ? 1U : 0U) | (s->ready ? 2U : 0U) | (s->reason ? 4U : 0U) |
                     (s->first_valid ? 8U : 0U) | (s->final_valid ? 16U : 0U) |
                     (s->known_empty ? 32U : 0U) | (s->stopped ? 64U : 0U) |
                     (s->recording ? 128U : 0U) | (s->fenced ? 256U : 0U) |
                     (s->challenge_valid ? 512U : 0U) | (s->recording ? 1024U : 0U);
    memset(d, 0, 128);
    d[0] = 5;
    d[2] = 1;
    d[4] = 128;
    d[6] = s->phase;
    d[7] = s->recording ? 1 : 0;
    bodaqs_control_put_u64(d + 8, s->recording);
    bodaqs_control_put_u64(d + 16, s->owner);
    bodaqs_control_put_u32(d + 24, v->boot_id);
    bodaqs_control_put_u32(d + 28, flags);
    bodaqs_control_put_u32(d + 32, s->lease_tick);
    bodaqs_control_put_u32(d + 36, s->challenge ? s->issued_tick + 300000U : 0);
    bodaqs_control_put_u32(d + 40, s->recording ? s->prepared_tick + 5000000U : 0);
    bodaqs_control_put_u32(d + 44, s->renewal_sequence);
    bodaqs_control_put_u32(d + 48, captured_tick);
    bodaqs_control_put_u32(d + 52, s->node_clock_epoch);
    bodaqs_control_put_u32(d + 56, s->sensor_clock_epoch);
    d[60] = s->reason;
    bodaqs_control_put_u64(d + 64, v->endpoint_epoch[0]);
    bodaqs_control_put_u64(d + 72, bodaqs_control_get_u64(s->effective + 32));
    if (s->first_valid)
        memcpy(d + 88, s->first, 16);
    if (s->final_valid)
        memcpy(d + 104, s->final, 16);
}
