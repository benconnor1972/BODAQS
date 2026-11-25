/* Main-owner prepared-output census, 300s warmup/30s window. Never DMA proof. */
typedef struct {
 uint32_t version,size_bytes,state,reserved;
 uint64_t context,recording;
 uint32_t started_ms,elapsed_ms,frames,packed,legacy,invalid,empty,coalesced,cells[6];
 uint32_t ack_commands,ack_entries,repeated_commands,max_us;
 uint64_t total_us;
} BpDiagnostics;
volatile BpDiagnostics gPackedDiagnostic __attribute__((section(".bodaqs_spi_buffers")));
_Static_assert(sizeof(BpDiagnostics)==112,"Packed diagnostic ABI");
static uint32_t packed_clock(void){
#if defined(BODAQS_MASTER_PHASE_TIMING) && BODAQS_MASTER_PHASE_TIMING
 return bodaqs_master_profile_clock();
#else
 return 0;
#endif
}
static void packed_record(BodaqsMasterService *s,const uint8_t *request,size_t bytes,
 const uint8_t *reply,uint32_t now,uint32_t cost,bool valid,bool repeated){
 if(!s || !gPackedMaster.context || !gPackedMaster.command)return;
 if(gPackedDiagnostic.context!=gPackedMaster.context){
  memset((void*)&gPackedDiagnostic,0,sizeof gPackedDiagnostic);
  gPackedDiagnostic.version=1;gPackedDiagnostic.size_bytes=sizeof gPackedDiagnostic;
  gPackedDiagnostic.context=gPackedMaster.context;gPackedDiagnostic.recording=s->transfer_recording;
  gPackedDiagnostic.started_ms=now+300000U;
 }
 if(gPackedDiagnostic.state==3 || (int32_t)(now-gPackedDiagnostic.started_ms)<0)return;
 const uint32_t elapsed=now-gPackedDiagnostic.started_ms;
 if(elapsed>=30000){gPackedDiagnostic.elapsed_ms=30000;gPackedDiagnostic.state=3;return;}
 gPackedDiagnostic.state=1;gPackedDiagnostic.elapsed_ms=elapsed;
 if(!valid){++gPackedDiagnostic.invalid;return;}
 ++gPackedDiagnostic.frames;gPackedDiagnostic.total_us+=cost;
 if(cost>gPackedDiagnostic.max_us)gPackedDiagnostic.max_us=cost;
 if(bytes==512 && !memcmp(request,"B51C",4)){
  if(request[5]){++gPackedDiagnostic.ack_commands;gPackedDiagnostic.ack_entries+=request[5];}
  if(repeated)++gPackedDiagnostic.repeated_commands;
 }
 if(!memcmp(reply,"B51P",4)){
  ++gPackedDiagnostic.packed;if(!reply[5])++gPackedDiagnostic.empty;
  if(reply[5]>1)++gPackedDiagnostic.coalesced;
  unsigned offset=32;
  for(unsigned i=0;i<reply[5] && i<4 && offset+8<=508;++i){
   const unsigned cls=bodaqs_fragment_class(reply[offset]);
   if(cls<6)++gPackedDiagnostic.cells[cls];
   offset+=8+(unsigned)bodaqs_measurement_get(reply+offset+2,2);
  }
 }else ++gPackedDiagnostic.legacy;
}
