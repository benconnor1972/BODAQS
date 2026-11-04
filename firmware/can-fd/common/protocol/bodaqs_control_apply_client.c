#include "bodaqs_control_apply_client.h"
#include <string.h>
void bodaqs_control_apply_client_init(BodaqsControlApplyClient *s)
{
    memset(s, 0, sizeof(*s));
}
void bodaqs_control_apply_client_invalidate(BodaqsControlApplyClient *s, uint8_t a)
{
    if (a >= 4)
        return;
    if (s->phase && s->current.node_address == a)
    {
        s->phase = 0;
        s->pending = false;
        s->nodes[a].valid = true;
        s->nodes[a].kind = 6;
        s->nodes[a].reason = 19; /* Invalidated scope is uncertainty, not rejection. */
    }
}
bool bodaqs_control_apply_client_start(BodaqsControlApplyClient *s, BodaqsControlAuthorityClient *a,
                                       uint64_t master, uint8_t address, uint64_t generation,
                                       uint64_t revision, const uint8_t descriptor[44],
                                       uint32_t now)
{
    BodaqsControlRecord *q = &s->current.record;
    if (s->phase || address >= 4 || !master || !generation || !a->session ||
        !a->nodes[address].bound || !a->nodes[address].available ||
        !a->nodes[address].next_mutation || s->next_transfer == UINT64_MAX)
        return false;
    memset(&s->current, 0, sizeof(s->current));
    s->current.master_boot_id = master;
    s->current.node_address = address;
    q->node_boot_id = a->nodes[address].boot;
    q->session = a->session;
    q->operation = a->nodes[address].next_mutation;
    q->transfer = ++s->next_transfer;
    memcpy(s->descriptor, descriptor, 44);
    memset(s->metadata, 0, 24);
    s->metadata[0] = 1;
    s->metadata[2] = 1;
    s->metadata[4] = 44;
    bodaqs_control_put_u64(s->metadata + 8, generation);
    bodaqs_control_put_u64(s->metadata + 16, revision);
    s->phase = 1;
    s->pending = false;
    s->started = now;
    s->committed = 0;
    s->commit_sent = false;
    s->resume_phase = 0;
    if (s->nodes[address].valid) s->previous[address]=s->nodes[address];
    memset(&s->nodes[address], 0, sizeof(s->nodes[address]));
    s->nodes[address].desired_generation = generation;
    s->nodes[address].operation = q->operation;
    s->nodes[address].boot = q->node_boot_id;
    s->nodes[address].session = q->session;
    s->nodes[address].kind = 2;
    return true;
}
bool bodaqs_control_apply_client_next(BodaqsControlApplyClient *s, BodaqsControlAuthorityClient *a,
                                      uint32_t now, BodaqsControlWrapped *out, uint8_t *type)
{
    BodaqsControlRecord *q = &s->current.record;
    BodaqsControlApplyOutcome *o = &s->nodes[s->current.node_address];
    if (!s->phase)
        return false;
    if (!a->nodes[s->current.node_address].bound || a->session != q->session ||
        a->nodes[s->current.node_address].boot != q->node_boot_id)
    {
        s->phase = 0;
        s->pending = false;
        o->valid = true;
        o->kind = 6;
        o->reason = 19;
        o->observed_ms = now;
        return false;
    }
    /* Knowledge expires at the original deadline even while the SPI owner
     * drains an already-issued CAN exchange. Late evidence remains inspectable. */
    if ((uint32_t)(now - (s->commit_sent ? s->committed : s->started)) >= 5000)
    {
        o->kind = 6; o->reason = 19; o->valid = true; o->observed_ms = now;
        if (!s->pending) { s->phase = 0; return false; }
    }
    if (s->pending)
    {
        *out = s->current;
        out->record.data_length = 0;
        memset(out->record.data, 0, 24);
        *type = 7;
        return true;
    }
    if (s->phase == 5 && (int32_t)(now - s->next_query) < 0)
        return false;
    memset(q->data, 0, 24);
    q->page = 0;
    q->operation = o->operation;
    if (s->phase == 1 || s->phase == 4)
    {
        q->opcode = s->phase == 1 ? 0x10 : 0x12;
        q->data_length = 24;
        memcpy(q->data, s->metadata, 24);
        if (s->phase == 4 && !s->commit_sent)
        {
            s->committed = now;
            s->commit_sent = true;
        }
    }
    else if (s->phase == 2 || s->phase == 3)
    {
        q->opcode = 0x11;
        q->page = s->phase == 2 ? 0 : 1;
        q->data_length = q->page ? 20 : 24;
        memcpy(q->data, s->descriptor + q->page * 24, q->data_length);
    }
    else
    {
        if (!a->next_read)
        {
            s->phase = 0;
            return false;
        }
        q->opcode = 0x14;
        q->operation = a->next_read++;
        q->data_length = 4;
        bodaqs_control_put_u32(q->data, o->operation);
        q->transfer = 0;
    }
    if (s->phase != 5)
        q->transfer = s->next_transfer;
    s->pending = true;
    *out = s->current;
    *type = 6;
    return true;
}
bool bodaqs_control_apply_client_accept(BodaqsControlApplyClient *s,
                                        BodaqsControlAuthorityClient *a, uint8_t type,
                                        const BodaqsControlWrapped *r, uint32_t now)
{
    const BodaqsControlRecord *p = &r->record, *q = &s->current.record;
    BodaqsControlApplyOutcome *o = &s->nodes[s->current.node_address];
    if (!s->pending || r->master_boot_id != s->current.master_boot_id ||
        r->node_address != s->current.node_address || p->node_boot_id != q->node_boot_id ||
        p->session != q->session || p->operation != q->operation || p->transfer != q->transfer ||
        p->endpoint != q->endpoint || p->page != q->page)
        return false;
    if (type == 0x86)
    {
        if (p->data_length != 4 || p->data[3] != q->opcode)
            return false;
        if (p->data[0] >= 3)
        {
            s->pending = false;
            if (p->data[0] == 5)
            {
                s->resume_phase = s->phase == 1 ? 2 : s->phase;
                s->phase = 5;
                s->next_query = now;
            }
            else
            {
                o->kind = 6;
                o->reason = p->data[1];
                o->valid = true;
                o->observed_ms = now;
                s->phase = 0;
            }
        }
        return true;
    }
    if (type != 0x87 || p->data_length != 24 || p->data[3] != q->opcode ||
        (p->opcode != q->opcode && p->opcode != 0x7f) ||
        (bodaqs_control_get_u32(p->data + 4) != o->operation &&
         !(q->opcode == 0x14 && p->data[0] == 1)))
        return false;
    s->pending = false;
    if (p->data[0] == 2 || p->data[0] == 3 || p->data[0] == 4 || p->data[0] == 5)
    {
        bodaqs_control_authority_client_reserve_mutation(a, &s->current, o->operation);
    }
    if (p->data[0] == 2)
    {
        if (s->phase < 5)
            ++s->phase;
        else if (s->resume_phase)
        {
            s->phase = s->resume_phase;
            s->resume_phase = 0;
        }
        s->next_query = now + 100;
        return true;
    }
    o->kind = p->data[0];
    o->reason = p->data[1];
    o->revision = bodaqs_control_get_u64(p->data + 8);
    o->accepted_generation = bodaqs_control_get_u64(p->data + 16);
    o->valid = true;
    o->observed_ms = now;
    s->phase = 0;
    return true;
}

void bodaqs_control_apply_client_transport_timeout(BodaqsControlApplyClient *s, uint32_t now)
{
    BodaqsControlApplyOutcome *o;
    if (!s->pending) return;
    o = &s->nodes[s->current.node_address];
    s->pending = false;
    s->phase = 5;
    s->resume_phase = 0;
    s->next_query = now;
    o->valid = true;
    o->kind = 6;
    o->reason = BODAQS_CONTROL_REASON_TIMEOUT;
    o->observed_ms = now;
}
void bodaqs_control_apply_client_quarantine(BodaqsControlApplyClient *s,
                                            BodaqsControlAuthorityClient *a, uint32_t now)
{
    BodaqsControlApplyOutcome *o;
    if (!s->phase) return;
    o = &s->nodes[s->current.node_address];
    o->kind = 6;
    o->reason = BODAQS_CONTROL_REASON_UNKNOWN_OPERATION;
    o->valid = true;
    o->observed_ms = now;
    bodaqs_control_authority_client_reserve_mutation(a, &s->current, o->operation);
    s->phase = 0;
    s->pending = false;
    s->resume_phase = 0;
}
void bodaqs_control_apply_client_recording_fence(BodaqsControlApplyClient *s,
                                                 BodaqsControlAuthorityClient *a, uint32_t now)
{
    /* Drain a submitted exchange, but abandon staged continuation before COMMIT.
     * A possibly accepted COMMIT permits only read-only outcome inspection. */
    if (s->phase && !s->pending && !s->commit_sent)
        bodaqs_control_apply_client_quarantine(s, a, now);
    if (s->commit_sent) s->resume_phase = 0;
}
