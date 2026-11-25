#ifndef BODAQS_PACKED_REPLY_H
#define BODAQS_PACKED_REPLY_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#ifndef BODAQS_PACKED_PROGRESS
#define BODAQS_PACKED_PROGRESS 0
#endif
#define BP_WIRE_VERSION (BODAQS_PACKED_PROGRESS ? 3 : 2)
#ifdef __cplusplus
extern "C" {
#endif
/* Private r50 experiment, not a negotiated firmware protocol.
 * Immutable borrowed logical objects; no ACK/custody is implied by decoding.
 * Caller keeps wire storage immutable/alive until all views are consumed.
 * Valid input/output objects must not overlap; encode bodies must not alias
 * its output wire. The codec does not manage pointer ownership. */
enum { BP_BYTES=512, BP_BODY=476, BP_MAX_ITEMS=4, BP_MAX_ACKS=8, BP_COMMAND_BYTES=256 };
typedef struct {
    const uint8_t *body;
    uint32_t object;
    uint16_t length;
    uint8_t kind,node;
} BpItem;
typedef struct {
    uint64_t context;
    uint32_t sequence,confirmed_command;
#if BODAQS_PACKED_PROGRESS
    uint32_t confirmed_metadata;
#endif
    uint8_t count;
    BpItem items[BP_MAX_ITEMS];
} BpReply;
/* Complete objects only; no fragment indices, no ownership mutation.
 * Failed decode leaves output unchanged. Physical sequence is diagnostic:
 * replay/order and logical duplicate handling remain caller responsibilities. */
bool bp_encode(const BpReply *reply,uint8_t wire[BP_BYTES]);
bool bp_decode(const uint8_t *wire,size_t bytes,uint64_t expected_context,BpReply *reply);
typedef struct {
    uint32_t object,checksum;
    uint16_t total;
    uint8_t node,cls,disposition;
} BpAck;
typedef struct {
    uint64_t context;
    uint32_t sequence;
#if BODAQS_PACKED_PROGRESS
    uint32_t metadata_sequence;
#endif
    uint8_t count;
    /* Exact existing per-source sample-base/credit words, interpreted outside
     * this codec by the retained v5 window/credit implementation. */
    uint8_t sample_words[32];
    BpAck acks[BP_MAX_ACKS];
} BpCommand;
bool bp_command_encode(const BpCommand *command,uint8_t wire[BP_COMMAND_BYTES]);
bool bp_command_decode(const uint8_t *wire,size_t bytes,uint64_t expected_context,BpCommand *command);
#ifdef __cplusplus
}
#endif
#endif
