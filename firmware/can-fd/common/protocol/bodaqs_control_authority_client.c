#include "bodaqs_control_authority_client.h"
#include <string.h>
void bodaqs_control_authority_client_init(BodaqsControlAuthorityClient *s, uint64_t session)
{
    memset(s, 0, sizeof(*s));
    s->session = session;
    s->next_read = 1;
}
void bodaqs_control_authority_client_node(BodaqsControlAuthorityClient *s, uint8_t a, uint32_t boot, bool available)
{
    BodaqsControlAuthorityPeer *p;
    if (a >= 4)
        return;
    p = &s->nodes[a];
    if (p->boot != boot || !available)
    {
        memset(p, 0, sizeof(*p));
        if (s->pending && s->current.node_address == a)
            s->pending = false;
    }
    p->boot = boot;
    p->available = available && boot;
}
bool bodaqs_control_authority_client_next(BodaqsControlAuthorityClient *s, uint64_t master, BodaqsControlWrapped *q,
                                          uint8_t *type)
{
    unsigned a;
    if (!master || !s->session)
        return false;
    if (s->pending)
    {
        *q = s->current;
        q->record.data_length = 0;
        memset(q->record.data, 0, 24);
        *type = BODAQS_CONTROL_POLL_REQUEST;
        return true;
    }
    for (a = 0; a < 4; a++)
    {
        if (s->nodes[a].available && s->nodes[a].phase == 1)
        {
            s->pending = true;
            *q = s->current;
            *type = BODAQS_CONTROL_SUBMIT_REQUEST;
            s->nodes[a].phase = 2;
            return true;
        }
        BodaqsControlAuthorityPeer *p = &s->nodes[a];
        BodaqsControlRecord *r = &s->current.record;
        if (!p->available || p->phase == 3 || (p->bound && !p->releasing))
            continue;
        if (!s->next_read)
            return false;
        memset(&s->current, 0, sizeof(s->current));
        s->current.master_boot_id = master;
        s->current.node_address = (uint8_t)a;
        r->node_boot_id = p->boot;
        r->endpoint = 255;
        if (p->releasing)
        {
            r->opcode = BODAQS_CONTROL_RELEASE_SESSION;
            r->operation = p->next_mutation;
            r->session = s->session;
        }
        else
        {
            r->opcode = BODAQS_CONTROL_GET_CHALLENGE;
            r->operation = s->next_read++;
            r->data_length = 8;
            bodaqs_control_put_u64(r->data, s->session);
        }
        s->pending = true;
        *q = s->current;
        *type = BODAQS_CONTROL_SUBMIT_REQUEST;
        return true;
    }
    return false;
}
bool bodaqs_control_authority_client_accept(BodaqsControlAuthorityClient *s, uint8_t type,
                                            const BodaqsControlWrapped *reply, uint32_t now)
{
    const BodaqsControlRecord *r = &reply->record;
    BodaqsControlRecord *q = &s->current.record;
    BodaqsControlAuthorityPeer *p;
    (void)now;
    if (!s->pending || reply->node_address != s->current.node_address ||
        reply->master_boot_id != s->current.master_boot_id || r->operation != q->operation ||
        r->node_boot_id != q->node_boot_id || r->endpoint != q->endpoint || r->session != q->session ||
        r->page != q->page)
        return false;
    p = &s->nodes[reply->node_address];
    if (type == BODAQS_CONTROL_RECEIPT_RESPONSE)
    {
        if (r->data_length != 4 || r->data[3] != q->opcode)
            return false;
        if (r->data[0] >= BODAQS_CONTROL_BUSY)
        {
            s->pending = false;
            p->phase = 3;
            p->bound = false;
            p->reason = r->data[1];
        }
        return true;
    }
    if (type != BODAQS_CONTROL_POLL_RESPONSE)
        return false;
    if (r->opcode == BODAQS_CONTROL_GET_CHALLENGE && q->opcode == BODAQS_CONTROL_GET_CHALLENGE && r->transfer &&
        r->data_length == 4 && bodaqs_control_get_u32(r->data) == 5000)
    {
        uint64_t challenge = r->transfer;
        memset(q, 0, sizeof(*q));
        q->opcode = BODAQS_CONTROL_BIND_SESSION;
        q->endpoint = 255;
        q->node_boot_id = p->boot;
        q->operation = 1;
        q->session = s->session;
        q->transfer = challenge;
        /* New exchange must be submitted before polling. */
        p->phase = 1;
        s->pending = false;
        return true;
    }
    if (r->data_length != 24 || r->data[3] != q->opcode ||
        (r->opcode != q->opcode && r->opcode != BODAQS_CONTROL_ERROR))
        return false;
    s->pending = false;
    p->reason = r->data[1];
    if (r->opcode == q->opcode && r->data[0] == 0)
    {
        p->bound = q->opcode == BODAQS_CONTROL_BIND_SESSION;
        p->next_mutation = q->operation + 1;
        p->phase = p->bound ? 2 : 3;
        p->releasing = false;
    }
    else
    {
        p->bound = false;
        p->phase = 3;
    }
    return true;
}
bool bodaqs_control_authority_client_release(BodaqsControlAuthorityClient *s, uint8_t a)
{
    if (a >= 4 || !s->nodes[a].bound || s->pending)
        return false;
    s->nodes[a].releasing = true;
    return true;
}
