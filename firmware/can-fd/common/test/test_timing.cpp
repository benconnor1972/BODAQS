#include "bodaqs_master_service.h"
#include "bodaqs_timing.h"
#include <cassert>
static unsigned observations;
static uint32_t native_clock(void*,uint32_t* epoch) {++observations;*epoch=7;return 1234567;}
int main() {
 BodaqsMasterService s={};BodaqsMasterIdentity identity={};
 bodaqs_master_service_init(&s,&identity);
 s.measurement.mode.phase=2;s.measurement.mode.context=9;
 s.native_clock=native_clock;
 BodaqsMeasurementSlot request={},response={};uint8_t wire[64],out[84];
 bodaqs_bridge_request(&request,9,42);
 assert(request.body[4]==0x21 && request.body[5]==0xbd && request.body[6]==0xa3 && request.body[7]==0xd1); // independent struct.pack/zlib vector
 bodaqs_measurement_encode(&request,wire,64);
 assert(bodaqs_master_service_process_transfer(&s,wire,64,1,out)==0);
 assert(bodaqs_measurement_decode(out,64,&response));
 assert(bodaqs_bridge_valid(&response,1));
 assert(response.object==42 && bodaqs_measurement_get(response.body+4,4)==1234567);
 assert(bodaqs_measurement_get(response.body+8,4)==7 && observations==1);
 assert(bodaqs_master_service_process_transfer(&s,wire,64,250,out)==0 && observations==1);
 request.body[4]^=1;bodaqs_measurement_encode(&request,wire,64);
 assert(bodaqs_master_service_process_transfer(&s,wire,64,260,out)!=0 && observations==1);
}
