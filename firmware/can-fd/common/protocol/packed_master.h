#ifndef BP_MASTER_H
#define BP_MASTER_H
#ifndef BODAQS_PACKED_SAMPLE_VIEW
#define BODAQS_PACKED_SAMPLE_VIEW 0
#endif
#if BODAQS_PACKED_SAMPLE_VIEW != 0 && BODAQS_PACKED_SAMPLE_VIEW != 1
#error "Packed sample view must be0 or1"
#endif
#include "packed_reply.h"
#include "bodaqs_master_service.h"
#ifdef __cplusplus
extern "C" {
#endif
typedef struct {
 uint8_t wire[512];
 uint32_t generation;
 bool owned;
} BpPhysicalSlot;
typedef struct {
 uint64_t context;
 uint32_t command,physical;
#if BODAQS_PACKED_PROGRESS
 uint32_t sample_base[4],metadata_sequence;
 uint8_t metadata_count,metadata_wire[128];
#endif
 uint8_t last_command[BP_COMMAND_BYTES],turn,node;
 BpPhysicalSlot slots[2];
} BpMaster;
/* Explicit selected experimental capability and an already verified context.
 * Caller must fence before reinitializing this state. No live rebind. */
bool bpm_init(BpMaster*,BodaqsMasterService*,bool selected);
/* Packed data commands only. Legacy controls route to the real service below.
 * All exact ACKs and credits validate before any release. Failed calls publish
 * no slot and do not change ACK ownership; selection follows successful ACKs. */
bool bpm_prepare(BpMaster*,BodaqsMasterService*,const uint8_t command[BP_COMMAND_BYTES],uint32_t now,
 unsigned slot,uint32_t *generation);
bool bpm_legacy(BpMaster*,BodaqsMasterService*,const uint8_t *request,size_t length,uint32_t now,
 unsigned slot,uint32_t *generation);
/* Completion of a short clock/DMA interrupt is insufficient. */
bool bpm_retire(BpMaster*,unsigned slot,uint32_t generation,bool full_transfer,bool cs_retired);
#ifdef __cplusplus
}
#endif
#endif
