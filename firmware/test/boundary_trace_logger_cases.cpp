// Included after the actual production manager and existing service fixture.
int main() {
 for(unsigned scenario=0;scenario<5;++scenario) {
  reset();ImuFlowDiagnostics::reset(456,clockMs);
  assert(CanMasterManager::enterMeasurementMode(123,456));
  markerCount=0;foreignCaller=scenario==1;markerFails=scenario==2;
  invalidSequence=scenario==3;
  if(scenario==4) s_diagnostics.measurementConfirmed=false;
  BodaqsMeasurementSlot request={},response={},staged={};
  request.node=255;request.context=456;request.kind=1;request.body[0]=1;
  staged.node=255;staged.context=456;
  uint8_t original[256],mosi[256];
  assert(bodaqs_measurement_encode(&request,mosi,256));
  assert(bodaqs_measurement_encode(&staged,original,256));
  original[0]=0;memcpy(preloaded,original,256);
  const auto slots=CanMasterManager::diagnostics().measurementTiming.slots;
  const auto failures=CanMasterManager::diagnostics().measurementTiming.decodeFailedSlots;
  assert(!CanMasterManager::exchangeMeasurementSlot(request,response));
  const auto& capture=ImuFlowDiagnostics::liveReplies;
  assert(capture.count==unsigned(scenario!=4));
  assert(markerCount==unsigned(scenario<3));
  if(scenario!=4) {
   assert(capture.entries[0].requestValid && !memcmp(capture.entries[0].request,mosi,256));
   assert(!memcmp(capture.entries[0].reply,original,256));
   assert(capture.boundary.attempted);
   assert(capture.boundary.transferred==(scenario<2));
   assert(capture.boundary.adjacent==(scenario==0));
   if(scenario<3) {
    assert(observedMarker.context==456 && observedMarker.object==slots+1);
    assert(bodaqs_measurement_get(observedMarker.body+8,4)==bodaqs_measurement_get(mosi+252,4));
    assert(bodaqs_measurement_get(observedMarker.body+12,4)==bodaqs_measurement_get(original+252,4));
   }
  }
  // The one marker's malformed pipelined MISO was discarded without decoding.
  assert(CanMasterManager::diagnostics().measurementTiming.slots==slots+1);
  assert(CanMasterManager::diagnostics().measurementTiming.decodeFailedSlots==failures+1);
  memcpy(preloaded,original,256);
  assert(!CanMasterManager::exchangeMeasurementSlot(request,response));
  assert(markerCount==unsigned(scenario<3)); // never retries/recurses
 }
 puts("actual manager: original bytes, one marker, confirmed gate, foreign caller, failed/invalid sequence PASS");
}
