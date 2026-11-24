#ifndef BODAQS_CONTROL_H
#define BODAQS_CONTROL_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C"
{
#endif
#define BODAQS_CONTROL_RECORD_BYTES 52U
#define BODAQS_CONTROL_GET_NODE_STATE 4U
#define BODAQS_CONTROL_ERROR 0x7fU
#define BODAQS_CONTROL_INFO_REQUEST 5U
#define BODAQS_CONTROL_SUBMIT_REQUEST 6U
#define BODAQS_CONTROL_POLL_REQUEST 7U
#define BODAQS_CONTROL_INFO_RESPONSE 0x85U
#define BODAQS_CONTROL_RECEIPT_RESPONSE 0x86U
#define BODAQS_CONTROL_POLL_RESPONSE 0x87U
#define BODAQS_CONTROL_CAPABILITY (1UL << 2)
    enum
    {
        BODAQS_CONTROL_GET_CHALLENGE = 0x01,
        BODAQS_CONTROL_BIND_SESSION = 0x02,
        BODAQS_CONTROL_RELEASE_SESSION = 0x03,
        BODAQS_CONTROL_OPEN_CAPABILITIES = 0x05,
        BODAQS_CONTROL_OPEN_EFFECTIVE = 0x06,
        BODAQS_CONTROL_READ_PAGE = 0x07,
        BODAQS_CONTROL_RELEASE_SNAPSHOT = 0x08,
        BODAQS_CONTROL_BEGIN_APPLY = 0x10,
        BODAQS_CONTROL_WRITE_PAGE = 0x11,
        BODAQS_CONTROL_COMMIT_APPLY = 0x12,
        BODAQS_CONTROL_ABORT_STAGING = 0x13,
        BODAQS_CONTROL_GET_OPERATION = 0x14,
        BODAQS_CONTROL_BEGIN_PREPARE = 0x20,
        BODAQS_CONTROL_WRITE_PREPARE_PAGE = 0x21,
        BODAQS_CONTROL_COMMIT_PREPARE = 0x22,
        BODAQS_CONTROL_ABORT_PREPARE_STAGING = 0x23,
        BODAQS_CONTROL_START = 0x24,
        BODAQS_CONTROL_STOP = 0x25,
        BODAQS_CONTROL_GET_LEASE_CHALLENGE = 0x26,
        BODAQS_CONTROL_RENEW_LEASE = 0x27,
        BODAQS_CONTROL_OPEN_ACQ_STATE = 0x28,
        BODAQS_CONTROL_RELEASE_MEMBERSHIP = 0x29,
        BODAQS_CONTROL_FENCE_OLD_DATA = 0x2A,
        BODAQS_CONTROL_NODE_WIDE = 0xFF,
        BODAQS_CONTROL_RECORD_VERSION = 1,
        BODAQS_CONTROL_CAN_REQUEST = 0x10,
        BODAQS_CONTROL_CAN_RESULT = 0x11,
        BODAQS_CONTROL_FEATURE_TYPED = 1U << 0,
        BODAQS_CONTROL_FEATURE_OBSERVATION = 1U << 1,
        BODAQS_CONTROL_QUEUED = 0,
        BODAQS_CONTROL_WAITING = 1,
        BODAQS_CONTROL_DUPLICATE = 2,
        BODAQS_CONTROL_BUSY = 3,
        BODAQS_CONTROL_REJECTED = 4,
        BODAQS_CONTROL_UNCERTAIN = 5,
        BODAQS_CONTROL_COMMAND_REJECTED = 1,
        BODAQS_CONTROL_REASON_NONE = 0,
        BODAQS_CONTROL_REASON_UNSUPPORTED = 1,
        BODAQS_CONTROL_REASON_STALE_NODE = 4,
        BODAQS_CONTROL_REASON_BUSY = 7,
        BODAQS_CONTROL_REASON_REUSED = 12,
        BODAQS_CONTROL_REASON_UNKNOWN_OPERATION = 19,
        BODAQS_CONTROL_REASON_EXHAUSTED = 22,
        BODAQS_CONTROL_REASON_ENDPOINT = 23,
        BODAQS_CONTROL_REASON_STALE_MASTER = 25,
        BODAQS_CONTROL_REASON_TIMEOUT = 26,
        BODAQS_CONTROL_REASON_NATIVE_NOT_READY = 27,
        BODAQS_CONTROL_REASON_RECORDING_MISMATCH = 28,
        BODAQS_CONTROL_REASON_LEASE_EXPIRED = 29,
        BODAQS_CONTROL_REASON_AUTHORIZATION_TERMINAL = 30,
        BODAQS_CONTROL_REASON_METADATA_UNAVAILABLE = 31,
        BODAQS_CONTROL_REASON_RECOVERY_EXHAUSTED = 32,
        BODAQS_CONTROL_REASON_FENCE_INCOMPLETE = 33,
        BODAQS_CONTROL_REASON_MODEL_CONFLICT = 34,
        BODAQS_CONTROL_REASON_CLOCK_UNTRUSTED = 35,
        BODAQS_CONTROL_REASON_CONTEXT_MISMATCH = 36,
        BODAQS_CONTROL_FIELD_NONE = 0,
        BODAQS_CONTROL_FIELD_RECORD = 1,
        BODAQS_CONTROL_FIELD_NODE_BOOT = 5,
        BODAQS_CONTROL_FIELD_MASTER_BOOT = 7,
        BODAQS_CONTROL_FIELD_SEQUENCE = 18,
        BODAQS_CONTROL_FIELD_ENDPOINT = 19,
        BODAQS_CONTROL_FIELD_RECORDING = 20,
        BODAQS_CONTROL_FIELD_PHASE = 21,
        BODAQS_CONTROL_FIELD_STATE_EPOCH = 22,
        BODAQS_CONTROL_FIELD_NATIVE_CLOCK = 23,
        BODAQS_CONTROL_FIELD_TIMING_MODEL = 24,
        BODAQS_CONTROL_FIELD_DATA_FENCE = 25,
        BODAQS_CONTROL_FIELD_STREAM_EPOCH = 26
    };
    typedef struct
    {
        uint8_t opcode, endpoint, page, data_length;
        uint32_t operation, node_boot_id;
        uint64_t session, transfer;
        uint8_t data[24];
    } BodaqsControlRecord;
    typedef struct
    {
        uint64_t master_boot_id;
        uint8_t node_address;
        BodaqsControlRecord record;
    } BodaqsControlWrapped;
    const char *bodaqs_control_reason_key(uint8_t reason);
    uint64_t bodaqs_control_get_u64(const uint8_t *p);
    uint32_t bodaqs_control_get_u32(const uint8_t *p);
    void bodaqs_control_put_u64(uint8_t *p, uint64_t value);
    void bodaqs_control_put_u32(uint8_t *p, uint32_t value);
    bool bodaqs_control_encode_record(const BodaqsControlRecord *r,
                                      uint8_t out[52]);
    bool bodaqs_control_decode_record(const uint8_t in[52],
                                      BodaqsControlRecord *r);
    bool bodaqs_control_request_valid(const BodaqsControlRecord *r);
    bool bodaqs_control_encode_can(const BodaqsControlRecord *r, bool result,
                                   uint16_t transaction, uint8_t out[64]);
    bool bodaqs_control_decode_can(const uint8_t *in, size_t length,
                                   bool result, uint16_t *transaction,
                                   BodaqsControlRecord *r);
    bool bodaqs_control_encode_wrapped(const BodaqsControlWrapped *r,
                                       uint8_t out[64]);
    bool bodaqs_control_decode_wrapped(const uint8_t *in, size_t length,
                                       BodaqsControlWrapped *r);
    void bodaqs_control_info(uint64_t boot, uint8_t out[32]);
    bool bodaqs_control_decode_info(const uint8_t *in, size_t length,
                                    uint64_t *boot, uint32_t *features);
    /* Pure inspection backend. Future services own authority/application state.
     */
    typedef struct
    {
        uint32_t boot_id;
        uint16_t endpoint_mask;
        uint64_t active_session;
        uint64_t endpoint_epoch[6];
        uint32_t flags;
        uint32_t pending_operation;
        bool epoch_exhausted;
        bool membership_cleanup_allowed; /* Internal stopped/invalid guard, not a wire flag. */
    } BodaqsControlNode;
    /* Update live clock health and fitted-endpoint epochs together. Unchanged
     * health does not consume epochs. False means epoch exhaustion: control
     * remains unavailable until reboot, without wrapping boot-scoped identities. */
    bool bodaqs_control_node_update_clock_fault(BodaqsControlNode *node, bool clock_fault);
    bool bodaqs_control_node_process(const BodaqsControlNode *node,
                                     const BodaqsControlRecord *request,
                                     BodaqsControlRecord *reply);
#ifdef __cplusplus
}
#endif
#endif
