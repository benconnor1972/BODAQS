#ifndef BP_RECEIVER_H
#define BP_RECEIVER_H
#include "packed_reply.h"
#include "bodaqs_fragment_transport.h"
#ifndef BODAQS_PACKED_COMMAND_TEMPLATE
#define BODAQS_PACKED_COMMAND_TEMPLATE 0
#endif
#if BODAQS_PACKED_COMMAND_TEMPLATE != 0 && BODAQS_PACKED_COMMAND_TEMPLATE != 1
#error "Command template must be0 or1"
#endif
#if BODAQS_PACKED_COMMAND_TEMPLATE && !BODAQS_PACKED_PROGRESS
#error "Command template requires cumulative sample progress"
#endif
#ifndef BODAQS_PACKED_PROGRESS_BATCH
#define BODAQS_PACKED_PROGRESS_BATCH 0
#endif
#if BODAQS_PACKED_PROGRESS_BATCH != 0 && BODAQS_PACKED_PROGRESS_BATCH != 1
#error "Progress batching flag must be0 or1"
#endif
#if BODAQS_PACKED_PROGRESS_BATCH && !BODAQS_PACKED_PROGRESS
#error "Progress batching requires packed progress v3"
#endif
#ifdef __cplusplus
extern "C" {
#endif
typedef struct {
 BodaqsFragmentState state;
#if defined(BODAQS_PACKED_SEGMENTED_RECEIVER) && BODAQS_PACKED_SEGMENTED_RECEIVER
 uint8_t *bytes; /* Bound fixed 468-byte owned storage, not a DMA borrow. */
#else
 uint8_t bytes[468];
#endif
 uint32_t confirmed;
 bool admitted,retired;
} BpReceiverCell;
typedef bool (*BpAdmit)(void*,uint8_t kind,uint8_t node,uint32_t object,const uint8_t*,uint16_t);
/* Synchronous notification after full batch confirmation, before item admission.
 * Borrowed ACK is immutable for this call. Callback must not reenter receiver. */
typedef void (*BpConfirmed)(void*,const BpAck*);
typedef struct {
 uint64_t context;
 uint32_t sequence,base[4],next[4],rejected;
#if BODAQS_PACKED_PROGRESS
 uint32_t metadata_sequence,custody_units[4];
 uint8_t sample_words[32]; /* Canonical current bases/held bits; owner updates. */
 uint32_t pending_custody,progress_started_us;
 uint32_t coalesced_commands,unchanged_commands,progress_hold_max_us;
 bool samples_dirty,metadata_dirty,progress_timer;
#endif
 bool awaiting,exhausted;
 uint8_t ack_cursor,protected_cursor; /* Advance only for a newly built command. */
 BpCommand inflight;
 uint8_t command_wire[BP_COMMAND_BYTES]; /* Owned immutable bytes while awaiting. */
 BpReceiverCell cells[29];
} BpReceiver;
/* Fresh zeroed state or externally fenced old state; selected matched profile.
 * Segmented profile requires all 29 byte pointers bound before initialization;
 * reset preserves their identity and clears their contents, without allocation. */
bool bpr_init(BpReceiver*,uint64_t context,bool selected);
/* Callback true means an owned downstream copy/consumption, never borrowed DMA.
 * False is temporary backpressure. No ACK until it returns true. */
bool bpr_receive(BpReceiver*,const uint8_t wire[512],BpAdmit,void*);
/* Private integration seam: reply MUST come from successful bp_decode for this
 * receiver context. Borrowed views stay immutable/alive through this call. */
bool bpr_receive_decoded(BpReceiver*,const BpReply*,BpAdmit,void*);
bool bpr_receive_decoded_notify(BpReceiver*,const BpReply*,BpAdmit,void*,BpConfirmed,void*);
void bpr_pump(BpReceiver*,BpAdmit,void*);
bool bpr_command(BpReceiver*,uint8_t wire[BP_COMMAND_BYTES]);
#if BODAQS_PACKED_PROGRESS
/* Logger-only scheduling policy; no wire change. Force flushes pending receipt
 * during START/cleanup. The4000us limit is checked at packed command attempts,
 * not a promise of execution while this owner is unscheduled. */
bool bpr_command_at(BpReceiver*,uint8_t wire[BP_COMMAND_BYTES],uint32_t now_us,bool force);
#endif
#ifdef __cplusplus
}
#endif
#endif
