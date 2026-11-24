/* Included inside CanMasterManager; acquisition-owner only, one active bank. */
#ifndef BODAQS_PACKED_PSRAM_PAYLOADS
#define BODAQS_PACKED_PSRAM_PAYLOADS 0
#endif
#if BODAQS_PACKED_PSRAM_PAYLOADS != 0 && BODAQS_PACKED_PSRAM_PAYLOADS != 1
#error "Packed PSRAM payloads flag must be0 or1"
#endif
#if BODAQS_PACKED_PSRAM_PAYLOADS && (!defined(BODAQS_PACKED_SEGMENTED_RECEIVER) || !BODAQS_PACKED_SEGMENTED_RECEIVER)
#error "PSRAM payloads require the segmented receiver"
#endif
static BpReceiver* packedReceiver;
static MeasurementTransport* packedTransport;
static bool packedWanted;
static uint32_t packedPackets,packedItems,packedBad,packedCopies;
static bool packedTracksAck_(const BodaqsMeasurementSlot& request){
 const unsigned cls=request.body[0],node=request.node;
 if(!packedReceiver || !request.object || cls<1 || cls>5 || (cls==5?node!=255:node>3))return false;
 const unsigned index=cls==1?node*4+(request.object-1)%4:cls==5?28:16+(cls-2)*4+node;
 const auto& cell=packedReceiver->cells[index];
 return cell.admitted && cell.state.object==request.object && cell.state.checksum==bodaqs_measurement_get(request.body+4,4);
}
#if defined(BODAQS_PACKED_SEGMENTED_RECEIVER) && BODAQS_PACKED_SEGMENTED_RECEIVER
#if defined(ARDUINO_ARCH_ESP32)
static_assert(sizeof(BpReceiver)<=2240,"Bounded segmented receiver header with command cache");
#endif
static void packedMemory_([[maybe_unused]] const char* stage) {
#if defined(ARDUINO_ARCH_ESP32) && BODAQS_PACKED_PSRAM_PAYLOADS
 CANMASTER_LOGI("receiver memory stage=%s payload_location=psram internal_free=%u internal_largest=%u dma_free=%u dma_largest=%u psram_free=%u\n",
   stage,(unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
   (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT),
   (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL|MALLOC_CAP_DMA),
   (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL|MALLOC_CAP_DMA),
   (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT));
#endif
}
static void* packedAllocate_(size_t bytes,[[maybe_unused]] bool payload=false) {
#if defined(ARDUINO_ARCH_ESP32)
#if BODAQS_PACKED_PSRAM_PAYLOADS
 // CPU-only assembly/validation storage. packedAdmit_ copies into the inbox;
 // hardware SPI/DMA buffers and task stacks remain internal. Do not silently
 // fall back to internal RAM and starve SD DMA when PSRAM is unavailable.
 if(payload)return heap_caps_calloc(1,bytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
#endif
 return heap_caps_calloc(1,bytes,MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT);
#else
 return std::calloc(1,bytes);
#endif
}
static void packedFree_(void* p) {
#if defined(ARDUINO_ARCH_ESP32)
 heap_caps_free(p);
#else
 std::free(p);
#endif
}
size_t packedLargestAllocation(){return sizeof(BpReceiver)>468?sizeof(BpReceiver):468;}
#endif
size_t packedReservedBytes(){return sizeof(BpReceiver)+sizeof(packedReceiver)+sizeof(packedTransport)+sizeof(packedWanted)+4*sizeof(uint32_t)
#if defined(BODAQS_PACKED_SEGMENTED_RECEIVER) && BODAQS_PACKED_SEGMENTED_RECEIVER
 +29u*468u
#endif
 ;}
#if defined(BODAQS_PACKED_EARLY_RESERVE) && BODAQS_PACKED_EARLY_RESERVE
bool packedBuffersReserved(){return packedReceiver!=nullptr;}
#endif
bool preparePackedBuffers(){
 if(packedReceiver)return true;
#if defined(BODAQS_PACKED_SEGMENTED_RECEIVER) && BODAQS_PACKED_SEGMENTED_RECEIVER
 packedMemory_("before_reserve");
 auto* pending=static_cast<BpReceiver*>(packedAllocate_(sizeof(BpReceiver)));
 if(!pending){packedMemory_("header_allocation_failed");return false;}
 for(auto& cell:pending->cells) {
  cell.bytes=static_cast<uint8_t*>(packedAllocate_(468,true));
  if(!cell.bytes) {
   for(auto& reserved:pending->cells)if(reserved.bytes)packedFree_(reserved.bytes);
   packedFree_(pending);packedMemory_("payload_allocation_failed");return false;
  }
 }
 packedReceiver=pending;packedMemory_("after_reserve");return true; // Publish only the completely owned bank.
#else
#if defined(ARDUINO_ARCH_ESP32)
 packedReceiver=static_cast<BpReceiver*>(heap_caps_calloc(1,sizeof(BpReceiver),MALLOC_CAP_INTERNAL|MALLOC_CAP_8BIT));
#else
 packedReceiver=new(std::nothrow) BpReceiver{};
#endif
 return packedReceiver!=nullptr;
#endif
}
static MeasurementInbox* packedInbox_(uint8_t cls,uint8_t node,uint32_t object){
 if(!packedTransport || cls<1 || cls>5 || (cls==5?node!=255:node>3))return nullptr;
 if(cls==1)return &sampleWindowInbox(*packedTransport,node,(object-1)%4);
 return &packedTransport->inboxes[cls-1][cls==5?0:node];
}
// Both callers have validated the current pending identity and its exact inbox
// mapping in this acquisition-owner call. No resolved pointer is retained.
static void packedClearConfirmedAt_(MeasurementInbox& inbox,unsigned cls,unsigned node,uint32_t object){
 const unsigned index=cls==1?4*node+(object-1)%4:cls==5?28:16+4*(cls-2)+node;
 const auto& cell=packedReceiver->cells[index];
 if(cell.state.cls==cls && cell.confirmed==object){
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
   if(!BODAQS_PACKED_PROGRESS || cls!=1)ImuFlowDiagnostics::proof(cls,node,object,micros());
#endif
   inbox.ackPending=false;
  }
}
// Late legacy BUSY/duplicate replies may re-arm an already proven ACK. Retain
// that sticky proof using one indexed lookup at the mutation, not global scans.
static void packedClearConfirmed_(MeasurementInbox& inbox){
 if(!packedReceiver || !packedTransport || !inbox.ackPending)return;
 const auto& ack=inbox.pendingAck;const unsigned cls=ack.body[0],node=ack.node;
 if(ack.context!=packedReceiver->context || !ack.object ||
    packedInbox_(cls,node,ack.object)!=&inbox)return;
 packedClearConfirmedAt_(inbox,cls,node,ack.object);
}
static void packedConfirmed_(void*,const BpAck* ack){
 if(!packedReceiver || !packedTransport)return;
 auto* inbox=packedInbox_(ack->cls,ack->node,ack->object);
 if(!inbox || !inbox->ackPending)return;
 const auto& pending=inbox->pendingAck;
 // With an equal object ID, this validated class/node key identifies exactly
 // one inbox. Match it directly instead of resolving the same mapping again.
 if(!pending.object || pending.object!=ack->object || pending.context!=packedReceiver->context ||
    pending.body[0]!=ack->cls || pending.node!=ack->node)return;
 packedClearConfirmedAt_(*inbox,ack->cls,ack->node,ack->object);
}
static bool packedAdmit_(void*,uint8_t kind,uint8_t node,uint32_t object,const uint8_t* bytes,uint16_t total){
 const uint8_t cls=bodaqs_fragment_class(kind);auto* inbox=packedInbox_(cls,node,object);
 if(!inbox)return false;
 if(cls==4 && (packedTransport->terminalNodes&(1U<<node)) && total>=16 && (bytes[12]==0x26 || bytes[12]==0x27)){
  if(inbox->state.object==object && inbox->state.complete)releaseMeasurementObject(*inbox);
  return true; // same terminal renewal-result discard as the legacy receiver
 }
 if(inbox->state.object==object && inbox->state.complete){
#if BODAQS_PACKED_PROGRESS
  // Downstream owned copy exists; release sample ACK scheduling immediately.
  // Cumulative progress still waits for the receiver's ordered custody base.
  if(cls==1 && inbox->admitted)inbox->ackPending=false;
#endif
  return inbox->admitted;
 }
 if(inbox->state.object && (!inbox->admitted || inbox->ackPending))return false;
 // The packed receiver has already validated shape/origin and owns these bytes.
 // Copy into the existing owner bank; ACK waits for its REAL downstream consumer.
 memcpy(inbox->bytes,bytes,total);auto& st=inbox->state;st={};st.context=packedReceiver->context;
 st.object=object;st.node=node;st.cls=cls;st.direction=1;st.total=total;st.mask=1;st.complete=1;
 st.checksum=static_cast<uint32_t>(bodaqs_measurement_get(bytes+total-4,4));st.accepted=1;
 st.accepted_object=object;st.accepted_total=total;st.accepted_checksum=st.checksum;
 inbox->admitted=false;inbox->ackPending=false;inbox->requestedFragments=0;
 ++packedCopies;++s_diagnostics.measurementObjectsReceived;
#if defined(BODAQS_IMU_FLOW_DIAGNOSTICS) && BODAQS_IMU_FLOW_DIAGNOSTICS
 ImuFlowDiagnostics::fragment(cls,true);
#endif
 return false;
}
static bool packedBind_(MeasurementTransport& transport){
 if(!packedReceiver || packedReceiver->context!=transport.context)return false;
 packedTransport=&transport;bpr_pump(packedReceiver,packedAdmit_,nullptr);return !packedReceiver->exhausted;
}

static PackedUtilization packedUtil;
static AckCapacityPhase packedAckCapacity[3];
static bool packedSawRunning;
static uint8_t packedAckPhase;
bool packedDiagnostics(PackedDiagnostics& out){
 if(!packedReceiver || s_diagnostics.measurement.phase!=0)return false;
 out.context=packedReceiver->context;out.packets=packedPackets;out.items=packedItems;out.rejected=packedBad;out.copies=packedCopies;
 for(unsigned i=0;i<3;++i){out.ack_capacity[i]=packedAckCapacity[i];}
#if BODAQS_PACKED_PROGRESS
 out.protocol_version=3;for(unsigned n=0;n<4;++n)out.sample_custody[n]=packedReceiver->custody_units[n];
 out.progress_batch=BODAQS_PACKED_PROGRESS_BATCH;
 out.coalesced_commands=packedReceiver->coalesced_commands;out.unchanged_commands=packedReceiver->unchanged_commands;
 out.progress_hold_max_us=packedReceiver->progress_hold_max_us;
#endif
 out.utilization=packedUtil;out.pending=packedReceiver->awaiting;out.exhausted=packedReceiver->exhausted;return true;
}

// Owner-only counters; frozen/exported only after measurement mode retires.
static uint32_t packedLastObjects[29],packedAckStarted,packedLastExchange;
static bool packedHasExchange;
static void packedCommandObserved_(bool command,uint32_t now){
 if(!packedReceiver)return;
 unsigned credits=0;
 // Four consecutive base-relative IDs always visit every slot of a source's
 // four-cell window. Count those same sixteen cells without remapping IDs.
 for(unsigned i=0;i<16;++i)credits+=!packedReceiver->cells[i].state.complete;
 ++packedUtil.credit_hist[credits];
 if(!command)return;
 ++packedUtil.commands;
#if !BODAQS_PACKED_PROGRESS
 if(packedReceiver->awaiting)++packedUtil.retries;
 else {++packedUtil.new_commands;packedAckStarted=now;}
#else
 (void)now; // v3 counters are recorded after command construction.
#endif
}
static void packedReplyObserved_(const BpReply& reply){
 ++packedUtil.reply_counts[reply.count];
 for(unsigned j=0;j<reply.count;++j){const auto& item=reply.items[j];
  unsigned cls=bodaqs_fragment_class(item.kind),i=cls==1?4*item.node+(item.object-1)%4:cls==5?28:16+4*(cls-2)+item.node;
  ++packedUtil.class_items[cls-1];packedUtil.class_bytes[cls-1]+=item.length;
  packedUtil.used_bytes+=8+item.length;
  if(packedLastObjects[i]==item.object)++packedUtil.repeat_items[cls-1];
  packedLastObjects[i]=item.object;
 }
}

static void packedAckObserved_(bool fresh){
 const bool running=LoggingManager::isRunning();if(running)packedSawRunning=true;
 const unsigned phase=running?1:packedSawRunning?2:0;
 auto& d=packedAckCapacity[phase];const auto& batch=packedReceiver->inflight;
 if(fresh){++d.batches[batch.count];if(batch.count)packedAckPhase=phase;}
 unsigned waiting[5]={};
 // A v3 pump retires admitted samples before returning to its owner. Only
 // metadata cells can await exact ACKs at this diagnostic observation point.
#if BODAQS_PACKED_COMMAND_TEMPLATE
 for(unsigned index=16;index<29;++index){const auto& cell=packedReceiver->cells[index];
#else
 for(const auto& cell:packedReceiver->cells){
#endif
  if(!cell.admitted || cell.retired)continue;
  bool sent=false;
  for(unsigned i=0;i<batch.count;++i){const auto& a=batch.acks[i];
   if(a.cls==cell.state.cls && a.node==cell.state.node && a.object==cell.state.object && a.checksum==cell.state.checksum){sent=true;break;}
  }
  if(!sent && cell.state.cls>=1 && cell.state.cls<=5)++waiting[cell.state.cls-1];
 }
 unsigned total=0;for(unsigned i=0;i<5;++i){total+=waiting[i];d.backlog_sum[i]+=waiting[i];if(waiting[i]>d.backlog_max[i])d.backlog_max[i]=waiting[i];}
 ++d.observations;++d.backlog_hist[total];
 if(fresh && total && batch.count){++d.nonempty_batches_with_waiting;if(batch.count==BP_MAX_ACKS)++d.full_batches_with_waiting;}
}
static void packedAckConfirmed_(uint32_t delay){
 auto& d=packedAckCapacity[packedAckPhase];++d.confirmations;d.delay_total_us+=delay;
 if(delay>d.delay_max_us)d.delay_max_us=delay;
 unsigned bucket=delay<2000?0:delay<4000?1:delay<8000?2:delay<12000?3:delay<20000?4:5;
 ++d.delay_hist[bucket];
}


