#include <cassert>
#include <cstdint>
#include <cstring>
struct MCAN_Regs {};
enum {DL_MCAN_OPERATION_MODE_NORMAL=0,DL_MCAN_OPERATION_MODE_SW_INIT=1};
struct DL_MCAN_BitTimingParams {
 uint32_t nomRatePrescalar,nomTimeSeg1,nomTimeSeg2,nomSynchJumpWidth;
 uint32_t dataRatePrescalar,dataTimeSeg1,dataTimeSeg2,dataSynchJumpWidth;
};
static DL_MCAN_BitTimingParams timing={0,62,15,15,0,14,3,3};
static uint32_t mode=0;
static bool reject_write=false,stuck_mode=false;
static void DL_MCAN_getBitTime(const MCAN_Regs*,DL_MCAN_BitTimingParams* out){*out=timing;}
static int32_t DL_MCAN_setBitTime(MCAN_Regs*,const DL_MCAN_BitTimingParams* p){if(reject_write)return -1;timing=*p;return 0;}
static uint32_t DL_MCAN_getOpMode(const MCAN_Regs*){return mode;}
static void DL_MCAN_setOpMode(MCAN_Regs*,uint32_t m){if(!stuck_mode)mode=m;}
#include "bodaqs_can_link_ti.h"
int main() {
 MCAN_Regs can;
 assert(bodaqs_can_link_from_capabilities(0)==BODAQS_CAN_LINK_UNKNOWN);
 assert(bodaqs_can_link_from_capabilities(BODAQS_CAN_LINK_CAP_BRINGUP|BODAQS_CAN_LINK_CAP_ACQUISITION)==BODAQS_CAN_LINK_UNKNOWN);
 assert(bodaqs_can_link_apply(&can,BODAQS_CAN_LINK_BRINGUP));
 assert(bodaqs_can_link_active(&can)==BODAQS_CAN_LINK_BRINGUP);
 assert(bodaqs_can_link_apply(&can,BODAQS_CAN_LINK_ACQUISITION));
 // Independent 40MHz MCAN register values: 40TQ arbitration,10TQ data,80% sample points.
 assert(timing.nomRatePrescalar==0 && timing.nomTimeSeg1==30 && timing.nomTimeSeg2==7 && timing.nomSynchJumpWidth==7);
 assert(timing.dataRatePrescalar==0 && timing.dataTimeSeg1==6 && timing.dataTimeSeg2==1 && timing.dataSynchJumpWidth==1);
 assert(bodaqs_can_link_active(&can)==BODAQS_CAN_LINK_ACQUISITION);
 assert(bodaqs_can_link_arbitration_hz(BODAQS_CAN_LINK_ACQUISITION)==1000000);
 assert(bodaqs_can_link_data_hz(BODAQS_CAN_LINK_ACQUISITION)==4000000);
 assert(!bodaqs_can_link_compatible(BODAQS_CAN_LINK_CAP_ACQUISITION,BODAQS_CAN_LINK_CAP_BRINGUP));
 assert(bodaqs_can_link_compatible(BODAQS_CAN_LINK_CAP_ACQUISITION|1,BODAQS_CAN_LINK_CAP_ACQUISITION|8));
 assert(bodaqs_can_link_apply(&can,BODAQS_CAN_LINK_BRINGUP));
 assert(timing.nomTimeSeg1==62 && timing.nomTimeSeg2==15 && timing.dataTimeSeg1==14 && timing.dataTimeSeg2==3);
 reject_write=true;
 assert(!bodaqs_can_link_apply(&can,BODAQS_CAN_LINK_ACQUISITION));
 assert(bodaqs_can_link_active(&can)==BODAQS_CAN_LINK_UNKNOWN); // Remains stopped on failure.
 reject_write=false;stuck_mode=true;mode=0;
 assert(!bodaqs_can_link_apply(&can,BODAQS_CAN_LINK_ACQUISITION));
 assert(!bodaqs_can_link_apply(&can,99));
}
