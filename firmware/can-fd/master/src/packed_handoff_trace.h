#ifndef PACKED_HANDOFF_TRACE_H
#define PACKED_HANDOFF_TRACE_H
#include <stdint.h>
enum { PH_CAPACITY=128, PH_WARMING=1, PH_CAPTURING=2, PH_FROZEN=3 };
enum { PH_FULL=1, PH_COMMAND=2, PH_QUEUED=4, PH_DROPPED=8,
 PH_POPPED=16, PH_VALID=32, PH_ACCEPTED=64, PH_PREPARED=128,
 PH_SELECTED=256, PH_RETURNED=512 };
typedef struct {
 uint32_t physical,cs_tick,epoch,request_sequence,request_acks;
 uint32_t tx_sequence,tx_confirm,depth,pop_tick,accept_tick,prepared_tick;
 uint32_t prepared_sequence,prepared_confirm,selected_tick,returned_tick;
 uint32_t returned_physical,flags,main_flags;
} PackedHandoffRecord;
typedef struct {
 uint32_t version,size_bytes,state,count;
 uint64_t context,recording;
 uint32_t warmup_ms,clock_epoch,main_flags,isr_flags;
 uint32_t first_physical,last_physical,reserved[2];
 PackedHandoffRecord records[PH_CAPACITY];
} PackedHandoffTrace;
_Static_assert(sizeof(PackedHandoffRecord)==72,"Handoff record ABI");
_Static_assert(sizeof(PackedHandoffTrace)==9280,"Handoff trace ABI");
#endif
