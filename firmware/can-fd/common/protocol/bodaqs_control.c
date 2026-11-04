#include "bodaqs_control.h"
#include <string.h>
static bool zeros(const uint8_t *p, size_t n)
{
    while (n--)
    {
        if (*p++)
        {
            return false;
        }
    }
    return true;
}

uint32_t bodaqs_control_get_u32(const uint8_t *p)
{
    return (uint32_t) p[0] | ((uint32_t) p[1] << 8) | ((uint32_t) p[2] << 16) |
           ((uint32_t) p[3] << 24);
}

uint64_t bodaqs_control_get_u64(const uint8_t *p)
{
    return bodaqs_control_get_u32(p) |
           ((uint64_t) bodaqs_control_get_u32(p + 4) << 32);
}

void bodaqs_control_put_u32(uint8_t *p, uint32_t v)
{
    unsigned i;
    for (i = 0; i < 4; ++i)
    {
        p[i] = (uint8_t) (v >> (8 * i));
    }
}

void bodaqs_control_put_u64(uint8_t *p, uint64_t v)
{
    unsigned i;
    for (i = 0; i < 8; ++i)
    {
        p[i] = (uint8_t) (v >> (8 * i));
    }
}

bool bodaqs_control_encode_record(const BodaqsControlRecord *r, uint8_t out[52])
{
    if (!r || !out || r->data_length > 24 ||
        !zeros(r->data + r->data_length, 24 - r->data_length))
    {
        return false;
    }
    out[0] = r->opcode;
    out[1] = r->endpoint;
    out[2] = r->page;
    out[3] = r->data_length;
    bodaqs_control_put_u32(out + 4, r->operation);
    bodaqs_control_put_u32(out + 8, r->node_boot_id);
    bodaqs_control_put_u64(out + 12, r->session);
    bodaqs_control_put_u64(out + 20, r->transfer);
    memcpy(out + 28, r->data, 24);
    return true;
}

bool bodaqs_control_decode_record(const uint8_t in[52], BodaqsControlRecord *r)
{
    if (!in || !r || in[3] > 24 || !zeros(in + 28 + in[3], 24 - in[3]))
    {
        return false;
    }
    memset(r, 0, sizeof(*r));
    r->opcode = in[0];
    r->endpoint = in[1];
    r->page = in[2];
    r->data_length = in[3];
    r->operation = bodaqs_control_get_u32(in + 4);
    r->node_boot_id = bodaqs_control_get_u32(in + 8);
    r->session = bodaqs_control_get_u64(in + 12);
    r->transfer = bodaqs_control_get_u64(in + 20);
    memcpy(r->data, in + 28, 24);
    return true;
}

bool bodaqs_control_request_valid(const BodaqsControlRecord *r)
{
    uint8_t encoded[52];
    if (!bodaqs_control_encode_record(r, encoded) || !r->operation ||
        !r->node_boot_id ||
        (r->endpoint > 5 && r->endpoint != BODAQS_CONTROL_NODE_WIDE) ||
        r->opcode == BODAQS_CONTROL_ERROR)
    {
        return false;
    }
    if ((r->opcode == BODAQS_CONTROL_BEGIN_APPLY && r->transfer) ||
        (r->opcode == BODAQS_CONTROL_COMMIT_APPLY && !r->transfer))
    {
        return false;
    }
    switch (r->opcode)
    {
    case BODAQS_CONTROL_GET_CHALLENGE:
        return r->endpoint == BODAQS_CONTROL_NODE_WIDE && !r->page &&
               !r->transfer && r->data_length == 8 &&
               bodaqs_control_get_u64(r->data) != 0;
    case BODAQS_CONTROL_BIND_SESSION:
        return r->endpoint == BODAQS_CONTROL_NODE_WIDE && !r->page &&
               r->session && r->transfer && r->operation == 1 &&
               !r->data_length;
    case BODAQS_CONTROL_RELEASE_SESSION:
        return r->endpoint == BODAQS_CONTROL_NODE_WIDE && !r->page &&
               r->session && !r->transfer && !r->data_length;
    case BODAQS_CONTROL_GET_NODE_STATE:
        return !r->page && !r->transfer && !r->data_length;
    case BODAQS_CONTROL_OPEN_CAPABILITIES:
    case BODAQS_CONTROL_OPEN_EFFECTIVE:
        return r->endpoint < 6 && !r->page && !r->transfer && !r->data_length;
    case BODAQS_CONTROL_READ_PAGE:
        return r->endpoint < 6 && r->transfer && !r->data_length;
    case BODAQS_CONTROL_RELEASE_SNAPSHOT:
        return r->endpoint < 6 && !r->page && r->transfer && !r->data_length;
    case BODAQS_CONTROL_BEGIN_APPLY:
    case BODAQS_CONTROL_COMMIT_APPLY:
        return r->endpoint < 6 && !r->page && r->session &&
               r->data_length == 24 && zeros(r->data + 6, 2);
    case BODAQS_CONTROL_WRITE_PAGE:
        return r->endpoint < 6 && r->session && r->transfer &&
               r->data_length > 0;
    case BODAQS_CONTROL_ABORT_STAGING:
        return r->endpoint < 6 && !r->page && r->session && r->transfer &&
               !r->data_length;
    case BODAQS_CONTROL_GET_OPERATION:
        return !r->page && r->session && !r->transfer && r->data_length == 4 &&
               bodaqs_control_get_u32(r->data) != 0;
    default:
        return true; /* Well-formed future commands receive explicit
                        unsupported. */
    }
}

bool bodaqs_control_encode_can(const BodaqsControlRecord *r, bool result,
                               uint16_t tx, uint8_t out[64])
{
    if (!out || !tx)
    {
        return false;
    }
    memset(out, 0, 64);
    out[0] = 1;
    out[1] = result ? BODAQS_CONTROL_CAN_RESULT : BODAQS_CONTROL_CAN_REQUEST;
    out[2] = 1;
    out[4] = (uint8_t) tx;
    out[5] = (uint8_t) (tx >> 8);
    out[6] = 52;
    return bodaqs_control_encode_record(r, out + 8);
}

bool bodaqs_control_decode_can(const uint8_t *in, size_t length, bool result,
                               uint16_t *tx, BodaqsControlRecord *r)
{
    if (!in || !tx || length != 64 || in[0] != 1 ||
        in[1] !=
            (result ? BODAQS_CONTROL_CAN_RESULT : BODAQS_CONTROL_CAN_REQUEST) ||
        in[2] != 1 || in[3] || in[6] != 52 || in[7] || !zeros(in + 60, 4))
    {
        return false;
    }
    *tx = (uint16_t) (in[4] | ((uint16_t) in[5] << 8));
    return *tx && bodaqs_control_decode_record(in + 8, r);
}

bool bodaqs_control_encode_wrapped(const BodaqsControlWrapped *r,
                                   uint8_t out[64])
{
    if (!r || !out || r->node_address >= 4)
    {
        return false;
    }
    memset(out, 0, 64);
    bodaqs_control_put_u64(out, r->master_boot_id);
    out[8] = r->node_address;
    out[9] = 1;
    return bodaqs_control_encode_record(&r->record, out + 12);
}

bool bodaqs_control_decode_wrapped(const uint8_t *in, size_t length,
                                   BodaqsControlWrapped *r)
{
    if (!in || !r || length != 64 || in[8] >= 4 || in[9] != 1 || in[10] ||
        in[11])
    {
        return false;
    }
    r->master_boot_id = bodaqs_control_get_u64(in);
    r->node_address = in[8];
    return bodaqs_control_decode_record(in + 12, &r->record);
}

void bodaqs_control_info(uint64_t boot, uint8_t out[32])
{
    memset(out, 0, 32);
    bodaqs_control_put_u64(out, boot);
    out[8] = 3;
    out[12] = 1;
    out[14] = 1;
    out[17] = 2;
    out[18] = 24;
    out[19] = 16;
    out[20] = 4;
    out[21] = 1;
    out[24] = 1;
}

bool bodaqs_control_decode_info(const uint8_t *in, size_t length,
                                uint64_t *boot, uint32_t *features)
{
    if (!in || !boot || !features || length != 32 ||
        !bodaqs_control_get_u64(in) || in[12] != 1 || in[13] || in[14] != 1 ||
        in[15] || in[16] || in[17] != 2 || in[18] != 24 || in[19] != 16 ||
        in[20] != 4 || in[21] != 1 || !zeros(in + 22, 2) || in[24] != 1 ||
        !zeros(in + 25, 7))
    {
        return false;
    }
    *boot = bodaqs_control_get_u64(in);
    *features = bodaqs_control_get_u32(in + 8);
    return true;
}

bool bodaqs_control_node_update_clock_fault(BodaqsControlNode *node, bool clock_fault)
{
    unsigned endpoint;
    if (node->epoch_exhausted)
        return false;
    if (!!(node->flags & (1UL << 7)) == clock_fault)
        return true;
    for (endpoint = 0; endpoint < 6; ++endpoint)
    {
        if ((node->endpoint_mask & (1U << endpoint)) &&
            node->endpoint_epoch[endpoint] == UINT64_MAX)
        {
            node->epoch_exhausted = true;
            return false;
        }
    }
    for (endpoint = 0; endpoint < 6; ++endpoint)
        if (node->endpoint_mask & (1U << endpoint))
            ++node->endpoint_epoch[endpoint];
    node->flags = (node->flags & ~(1UL << 7)) | (clock_fault ? (1UL << 7) : 0U);
    return true;
}

bool bodaqs_control_node_process(const BodaqsControlNode *node,
                                 const BodaqsControlRecord *request,
                                 BodaqsControlRecord *reply)
{
    uint8_t reason = 0, field = 0;
    if (!node || !reply || !bodaqs_control_request_valid(request))
    {
        return false;
    }
    *reply = *request;
    reply->data_length = 24;
    memset(reply->data, 0, 24);
    if (request->node_boot_id != node->boot_id)
    {
        reason = BODAQS_CONTROL_REASON_STALE_NODE;
        field = BODAQS_CONTROL_FIELD_NODE_BOOT;
    }
    else if (node->epoch_exhausted)
    {
        reason = BODAQS_CONTROL_REASON_EXHAUSTED;
        field = BODAQS_CONTROL_FIELD_SEQUENCE;
    }
    else if (request->session && request->session != node->active_session)
    {
        reason = 5;
        field = 6;
    }
    else if (request->opcode != BODAQS_CONTROL_GET_NODE_STATE)
    {
        reason = BODAQS_CONTROL_REASON_UNSUPPORTED;
        field = BODAQS_CONTROL_FIELD_RECORD;
    }
    else if (request->endpoint != BODAQS_CONTROL_NODE_WIDE &&
             !(node->endpoint_mask & (1U << request->endpoint)))
    {
        reason = BODAQS_CONTROL_REASON_ENDPOINT;
        field = BODAQS_CONTROL_FIELD_ENDPOINT;
    }
    if (reason)
    {
        reply->opcode = BODAQS_CONTROL_ERROR;
        reply->data[0] = BODAQS_CONTROL_COMMAND_REJECTED;
        reply->data[1] = reason;
        reply->data[2] = field;
        reply->data[3] = request->opcode;
        return true;
    }
    bodaqs_control_put_u64(reply->data, node->active_session);
    if (request->endpoint != BODAQS_CONTROL_NODE_WIDE)
    {
        bodaqs_control_put_u64(reply->data + 8,
                               node->endpoint_epoch[request->endpoint]);
    }
    bodaqs_control_put_u32(reply->data + 16, node->flags);
    bodaqs_control_put_u32(reply->data + 20, node->pending_operation);
    return true;
}

const char *bodaqs_control_reason_key(uint8_t reason)
{
    static const char *const names[] = {"none",
                                        "unsupported_opcode",
                                        "unsupported_schema",
                                        "unsupported_profile",
                                        "stale_node_boot",
                                        "stale_control_session",
                                        "stale_revision",
                                        "busy",
                                        "recording_locked",
                                        "conflicting_transfer",
                                        "transfer_expired",
                                        "incomplete_request",
                                        "identity_reused",
                                        "superseded_outcome",
                                        "sensor_spi_failure",
                                        "sensor_identity_mismatch",
                                        "sensor_reset_timeout",
                                        "register_verification_mismatch",
                                        "application_deadline_exceeded",
                                        "unknown_operation_outcome",
                                        "challenge_expired",
                                        "acquisition_active",
                                        "identity_space_exhausted",
                                        "unsupported_endpoint",
                                        "invalid_request_value",
                                        "stale_master_boot",
                                        "can_exchange_timeout"};
    return reason < sizeof(names) / sizeof(names[0]) ? names[reason]
                                                     : "unknown";
}
