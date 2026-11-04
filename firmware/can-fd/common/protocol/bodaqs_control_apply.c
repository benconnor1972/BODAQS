#include "bodaqs_control_apply.h"
#include <string.h>
static uint16_t read16(const uint8_t *p) { return (uint16_t)(p[0] | ((uint16_t)p[1] << 8)); }
enum
{
    IDLE,
    STAGING,
    APPLYING,
    TERMINAL
};
static void result(BodaqsControlApply *s, const BodaqsControlRecord *q, BodaqsControlRecord *r,
                   uint8_t kind, uint8_t reason, uint8_t field)
{
    *r = *q;
    r->data_length = 24;
    memset(r->data, 0, 24);
    r->data[0] = kind;
    r->data[1] = reason;
    if (field == 1)
    {
        switch (reason)
        {
        case 2:
            field = 2;
            break;
        case 3:
            field = 3;
            break;
        case 6:
            field = 8;
            break;
        case 8:
            field = 12;
            break;
        case 11:
            field = 10;
            break;
        case 21:
            field = 13;
            break;
        case 22:
            field = 18;
            break;
        case 23:
            field = 19;
            break;
        default:
            break;
        }
    }
    r->data[2] = field;
    r->data[3] = q->opcode;
    bodaqs_control_put_u32(r->data + 4, q->operation);
    bodaqs_control_put_u64(r->data + 8, bodaqs_control_get_u64(s->effective + 32));
    bodaqs_control_put_u64(r->data + 16, bodaqs_control_get_u64(s->effective + 24));
    if (kind == 1)
        r->opcode = BODAQS_CONTROL_ERROR;
}
static void publish(BodaqsControlApply *s, uint8_t kind, uint8_t reason, uint8_t field)
{
    BodaqsControlRecord r;
    result(s, &s->begin, &r, kind, reason, field);
    bodaqs_control_authority_complete(s->authority, &s->begin, &r);
    if (kind != 2)
    {
        s->phase = TERMINAL;
        s->view->pending_operation = 0;
        s->view->flags &= ~0x30U;
    }
}
static uint8_t guards(BodaqsControlApply *s)
{
    if (s->view->epoch_exhausted)
        return 22;
    if (s->view->flags & 2)
        return 8;
    if (s->view->flags & 12)
        return 21;
    if (s->view->endpoint_epoch[0] >= UINT64_MAX - 1 ||
        bodaqs_control_get_u64(s->effective + 32) == UINT64_MAX)
        return 22;
    if (bodaqs_control_get_u64(s->begin.data + 16) != bodaqs_control_get_u64(s->effective + 32))
        return 6;
    return 0;
}
static bool advance_epoch(BodaqsControlApply *s)
{
    if (s->view->epoch_exhausted || s->view->endpoint_epoch[0] == UINT64_MAX)
    {
        s->view->epoch_exhausted = true;
        return false;
    }
    ++s->view->endpoint_epoch[0];
    return true;
}
void bodaqs_control_apply_init(BodaqsControlApply *s, BodaqsControlAuthority *a,
                               BodaqsControlNode *v, BodaqsImuDisabled *b)
{
    memset(s, 0, sizeof(*s));
    s->authority = a;
    s->view = v;
    s->backend = b;
    bodaqs_control_unconfigured_descriptor(v, 0, true, s->effective);
    v->flags |= 1U << 9;
}
void bodaqs_control_apply_capture(void *ctx, const BodaqsControlNode *v, uint8_t ep, bool effective,
                                  uint8_t *d)
{
    BodaqsControlApply *s = (BodaqsControlApply *)ctx;
    if (ep != 0)
    {
        bodaqs_control_unconfigured_descriptor(v, ep, effective, d);
        return;
    }
    if (effective)
    {
        memcpy(d, s->effective, 192);
        d[7] = (v->flags & 2) ? 1 : 0;
        bodaqs_control_put_u32(d + 20, (bodaqs_control_get_u32(d + 20) & ~8U) |
                                           ((v->flags & 128) ? 8U : 0));
        bodaqs_control_put_u64(d + 184, v->endpoint_epoch[0]);
    }
    else
    {
        bodaqs_control_unconfigured_descriptor(v, ep, false, d);
        if (s->backend && s->backend->reg)
        {
            d[8] = 3; /* Configuration/readback only; acquisition unsupported. */
            d[6] = 1; d[64] = 1; d[66] = 1;
        }
        d[12] = (s->effective[4] == 1 || s->effective[4] == 2) ? 1 : 0;
        bodaqs_control_put_u32(d + 16, (bodaqs_control_get_u32(s->effective + 20) & ~8U) |
                                           ((v->flags & 128) ? 8U : 0));
    }
}
void bodaqs_control_apply_tick(BodaqsControlApply *s, uint32_t now)
{
    int rc;
    uint32_t known;
    if (s->view->epoch_exhausted && s->phase == STAGING)
    {
        publish(s, 5, 22, 18);
        return;
    }
    if (s->phase == STAGING && (uint32_t)(now - s->started) >= 5000)
    {
        publish(s, 5, 10, 11);
        return;
    }
    if (s->phase != APPLYING)
        return;
    if (s->view->epoch_exhausted)
    {
        bodaqs_imu_disabled_cancel(s->backend);
        s->backend->reason = 22;
        rc = -1;
    }
    else
        rc = bodaqs_imu_disabled_tick(s->backend, now);
    if ((s->backend->changed || s->backend->proof_invalid) && s->effective[4] != 3)
    {
        s->effective[4] = 3;
        bodaqs_control_put_u32(s->effective + 16, bodaqs_control_get_u32(s->effective + 12));
        bodaqs_control_put_u32(s->effective + 20, 32);
        if (!advance_epoch(s))
        {
            s->backend->reason = 22;
            rc = -1;
        }
        s->view->flags = (s->view->flags & ~(1U << 8)) | (1U << 9);
    }
    if (!rc)
        return;
    known = bodaqs_control_get_u32(s->effective + 12);
    if (rc < 0)
    {
        s->effective[4] = 3;
        bodaqs_control_put_u32(s->effective + 16, known);
        bodaqs_control_put_u32(s->effective + 20, 36U);
        if (s->backend->reason == 17)
        {
            bodaqs_control_put_u32(s->effective + 16, known & ~0x800U);
            bodaqs_control_put_u32(s->effective + 8,
                                   bodaqs_control_get_u32(s->effective + 8) | 0x800U);
            bodaqs_control_put_u32(s->effective + 12, known | 0x800U);
            s->effective[176] = s->backend->mismatch_address;
            s->effective[178] = s->backend->expected;
            s->effective[179] = s->backend->observed;
            s->effective[180] = s->backend->mask;
        }
        (void)advance_epoch(s);
        s->view->flags = (s->view->flags & ~(1U << 8)) | (1U << 9);
        publish(s, 5, s->backend->reason,
                s->backend->reason == 15   ? 14
                : s->backend->reason == 16 ? 15
                : s->backend->reason == 18 ? 0
                : s->backend->reason == 22 ? 18
                                           : 16);
        return;
    }
    {
        uint64_t revision = bodaqs_control_get_u64(s->effective + 32);
        bool epoch_change = s->effective[4] != (s->enabled ? 2 : 1) || s->backend->changed ||
                            bodaqs_control_get_u64(s->effective + 24) !=
                                bodaqs_control_get_u64(s->begin.data + 8) ||
                            bodaqs_control_get_u64(s->effective + 144) != s->begin.session;
        if (!revision || s->backend->changed)
            ++revision;
        if (epoch_change && !advance_epoch(s))
        {
            s->effective[4] = 3;
            bodaqs_control_put_u32(s->effective + 16, known);
            bodaqs_control_put_u32(s->effective + 20, 36);
            s->view->flags = (s->view->flags & ~(1U << 8)) | (1U << 9);
            publish(s, 5, 22, 18);
            return;
        }
        memset(s->effective, 0, 192);
        s->effective[0] = 3;
        s->effective[2] = 1;
        s->effective[4] = s->enabled ? 2 : 1;
        if (s->enabled) {
            s->effective[5] = 3;
            s->effective[40] = 1; s->effective[42] = 1;
            s->effective[44] = 1; s->effective[46] = 1; s->effective[47] = 1;
            bodaqs_control_put_u32(s->effective + 48,3333); bodaqs_control_put_u32(s->effective + 52,1);
            bodaqs_control_put_u32(s->effective + 56,3333); bodaqs_control_put_u32(s->effective + 60,1);
            bodaqs_control_put_u32(s->effective + 64,32000); bodaqs_control_put_u32(s->effective + 68,2000000);
            bodaqs_control_put_u32(s->effective + 72,122); bodaqs_control_put_u32(s->effective + 76,125000);
            bodaqs_control_put_u32(s->effective + 80,7); bodaqs_control_put_u32(s->effective + 84,100);
        }
        bodaqs_control_put_u32(s->effective + 8,
                               s->enabled ? 0x7ff : 0x441); /* identity, engines, register proof; acquisition NA */
        bodaqs_control_put_u32(s->effective + 12, s->enabled ? 0x47f : 0x441);
        bodaqs_control_put_u32(s->effective + 20, 3);
        bodaqs_control_put_u64(s->effective + 24, bodaqs_control_get_u64(s->begin.data + 8));
        bodaqs_control_put_u64(s->effective + 32, revision);
        bodaqs_control_put_u64(s->effective + 144, s->begin.session);
        bodaqs_control_put_u32(s->effective + 108, now);
        memcpy(s->effective + 152, s->backend->image, 24);
        s->view->flags = (s->view->flags & ~(1U << 9)) | (1U << 8);
        publish(s, s->adjusted ? 4 : 3, 0, 0);
    }
}
bool bodaqs_control_apply_process(BodaqsControlApply *s, const BodaqsControlRecord *q, uint32_t now,
                                  BodaqsControlRecord *r)
{
    uint8_t reason = 0;
    bool same;
    if (q->opcode < 0x10 || q->opcode > 0x13 || !bodaqs_control_request_valid(q))
        return false;
    bodaqs_control_apply_tick(s, now);
    if (q->node_boot_id != s->view->boot_id)
        reason = 4;
    else if (s->view->epoch_exhausted)
        reason = 22;
    else if (!q->session || q->session != s->view->active_session)
        reason = 5;
    if (reason)
    {
        result(s, q, r, 1, reason, reason == 4 ? 5 : reason == 22 ? 18 : 6);
        return true;
    }
    same = s->valid && q->operation == s->begin.operation && q->session == s->begin.session;
    if (same)
    {
        bool header = q->endpoint == s->begin.endpoint && q->transfer == s->begin.transfer;
        bool metadata =
            (q->opcode != 0x10 && q->opcode != 0x12) || !memcmp(q->data, s->begin.data, 24);
        bool page = q->opcode != 0x11 || (q->page < 2 && q->data_length == (q->page ? 20 : 24));
        if (!header || !metadata || !page)
        {
            result(s, q, r, 1, 12, 1);
            return true;
        }
        if (q->opcode == 0x11 && (s->pages & (1U << q->page)) &&
            memcmp(s->staging + q->page * 24, q->data, q->data_length))
        {
            if (s->phase == STAGING)
                publish(s, 5, 9, 11);
            result(s, q, r, 1, 12, 11);
            return true;
        }
        if (q->opcode == 0x13 && s->phase != STAGING)
        {
            if (s->phase == TERMINAL && s->authority->latest_result.data[0] == 5 &&
                s->authority->latest_result.data[1] == 9 &&
                s->authority->latest_result.data[2] == 1)
                result(s, q, r, 0, 0, 0); /* Retained staging-abort acknowledgement. */
            else
                result(s, q, r, 1, 9, 1);
            return true;
        }
        if (s->phase == TERMINAL || s->phase == APPLYING || q->opcode == 0x10)
        {
            *r = s->authority->latest_result;
            r->opcode = q->opcode;
            r->page = q->page;
            r->data[3] = q->opcode;
            return true;
        }
    }
    else
    {
        if (q->opcode != 0x10)
        {
            result(s, q, r, 1, 19, 18);
            return true;
        }
        reason = bodaqs_control_authority_admit(s->authority, s->view, q);
        if (!reason && (q->endpoint != 0 || !(s->view->endpoint_mask & 1)))
            reason = 23;
        if (!reason && (!s->backend || !s->backend->reg))
            reason = 2;
        if (!reason && (q->data[0] != 1 || q->data[1] || q->data[2] != 1 || q->data[3]))
            reason = 2;
        if (!reason && (q->data[4] != 44 || q->data[5]))
            reason = 24;
        if (!reason && !bodaqs_control_get_u64(q->data + 8))
            reason = 24;
        if (!reason && (s->view->flags & 2))
            reason = 8;
        if (!reason && (s->view->flags & 12))
            reason = 21;
        if (!reason && (s->view->endpoint_epoch[0] >= UINT64_MAX - 1 ||
                        bodaqs_control_get_u64(s->effective + 32) == UINT64_MAX))
            reason = 22;
        if (!reason && s->valid && q->session == s->begin.session &&
            q->transfer == s->begin.transfer)
            reason = 12;
        if (!reason &&
            bodaqs_control_get_u64(q->data + 16) != bodaqs_control_get_u64(s->effective + 32))
            reason = 6;
        if (reason)
        {
            result(s, q, r, 1, reason, reason == 6 ? 8 : 1);
            return true;
        }
        s->begin = *q;
        s->valid = true;
        s->phase = STAGING;
        s->pages = 0;
        s->started = now;
        memset(s->staging, 0, sizeof(s->staging));
        s->view->pending_operation = q->operation;
        s->view->flags |= 1U << 5;
        publish(s, 2, 0, 0);
        *r = s->authority->latest_result;
        return true;
    }
    if (q->opcode == 0x11)
    {
        memcpy(s->staging + q->page * 24, q->data, q->data_length);
        s->pages |= 1U << q->page;
        result(s, q, r, 2, 0, 0);
        return true;
    }
    if (q->opcode == 0x13)
    {
        publish(s, 5, 9, 1);
        result(s, q, r, 0, 0, 0);
        return true;
    }
    if (q->opcode == 0x12)
    {
        unsigned i;
        if (s->pages != 3)
            reason = 11;
        else if (s->staging[0] != 1 || s->staging[1] || s->staging[2] != 1 || s->staging[3])
            reason = 2;
        else
        {
            s->enabled = s->staging[4] == 1;
            s->adjusted = false;
            if (s->staging[4] > 1 || s->staging[5] > 8 || s->staging[6] || s->staging[7]) reason = 24;
            if (!s->enabled) {
                for (i=5;i<44;i++) if (s->staging[i]) reason=24;
            } else if (!reason) {
                uint16_t id=read16(s->staging+8), version=read16(s->staging+10);
                bool supported=id==1 && version==1;
                if (!id || !version) reason=24;
                for (i=0;i<8;i++) {
                    id=read16(s->staging+12+4*i);
                    version=read16(s->staging+14+4*i);
                    if (i<s->staging[5]) {
                        if (!id || !version) reason=24;
                        if (!supported && id==1 && version==1) {supported=true; s->adjusted=true;}
                    } else if (id || version) reason=24;
                }
                if (!reason && !supported) reason=3;
            }
        }
        if (!reason)
            reason = guards(s);
        if (reason)
            publish(s, 5, reason, reason == 6 ? 8 : 1);
        else
        {
            s->phase = APPLYING;
            s->view->flags = (s->view->flags & ~(1U << 5)) | (1U << 4);
            bodaqs_imu_profile_start(s->backend, s->enabled, s->effective[4] == (s->enabled ? 2 : 1), now);
            publish(s, 2, 0, 0);
        }
        *r = s->authority->latest_result;
        r->opcode = q->opcode;
        r->data[3] = q->opcode;
        return true;
    }
    return false;
}
