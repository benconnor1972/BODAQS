#ifndef BODAQS_CAN_LINK_TI_H
#define BODAQS_CAN_LINK_TI_H
#include "bodaqs_can_link.h"
/* Include after the target SDK declarations. Keeping this adapter separate
 * lets host tests drive the actual register readback/failure boundary. */
static inline bool bodaqs_can_link_timing(uint8_t profile, DL_MCAN_BitTimingParams *p) {
    if (profile != BODAQS_CAN_LINK_BRINGUP && profile != BODAQS_CAN_LINK_ACQUISITION) return false;
    p->nomRatePrescalar = p->dataRatePrescalar = 0;
    p->nomTimeSeg1 = profile == BODAQS_CAN_LINK_BRINGUP ? 62 : 30;
    p->nomTimeSeg2 = p->nomSynchJumpWidth = profile == BODAQS_CAN_LINK_BRINGUP ? 15 : 7;
    p->dataTimeSeg1 = profile == BODAQS_CAN_LINK_BRINGUP ? 14 : 6;
    p->dataTimeSeg2 = p->dataSynchJumpWidth = profile == BODAQS_CAN_LINK_BRINGUP ? 3 : 1;
    return true;
}
static inline bool bodaqs_can_link_same(const DL_MCAN_BitTimingParams *a, const DL_MCAN_BitTimingParams *b) {
    return a->nomRatePrescalar == b->nomRatePrescalar && a->nomTimeSeg1 == b->nomTimeSeg1 &&
        a->nomTimeSeg2 == b->nomTimeSeg2 && a->nomSynchJumpWidth == b->nomSynchJumpWidth &&
        a->dataRatePrescalar == b->dataRatePrescalar && a->dataTimeSeg1 == b->dataTimeSeg1 &&
        a->dataTimeSeg2 == b->dataTimeSeg2 && a->dataSynchJumpWidth == b->dataSynchJumpWidth;
}
static inline uint8_t bodaqs_can_link_active(MCAN_Regs *can) {
    DL_MCAN_BitTimingParams observed, expected;
    uint8_t profile;
    if (DL_MCAN_getOpMode(can) != DL_MCAN_OPERATION_MODE_NORMAL) return BODAQS_CAN_LINK_UNKNOWN;
    DL_MCAN_getBitTime(can, &observed);
    for (profile = BODAQS_CAN_LINK_BRINGUP; profile <= BODAQS_CAN_LINK_ACQUISITION; ++profile) {
        (void)bodaqs_can_link_timing(profile, &expected);
        if (bodaqs_can_link_same(&observed, &expected)) return profile;
    }
    return BODAQS_CAN_LINK_UNKNOWN;
}
static inline bool bodaqs_can_link_apply(MCAN_Regs *can, uint8_t profile) {
    DL_MCAN_BitTimingParams requested, observed;
    uint32_t remaining = 100000U;
    if (!bodaqs_can_link_timing(profile, &requested)) return false;
    if (bodaqs_can_link_active(can) == profile) return true;
    /* Startup only: no application TX or acquisition has begun. Never switch a
     * live recording's bus rate, and leave failed configuration stopped. */
    DL_MCAN_setOpMode(can, DL_MCAN_OPERATION_MODE_SW_INIT);
    while (DL_MCAN_getOpMode(can) != DL_MCAN_OPERATION_MODE_SW_INIT)
        if (!--remaining) return false;
    if (DL_MCAN_setBitTime(can, &requested) != 0) return false;
    DL_MCAN_getBitTime(can, &observed);
    if (!bodaqs_can_link_same(&requested, &observed)) return false;
    DL_MCAN_setOpMode(can, DL_MCAN_OPERATION_MODE_NORMAL);
    remaining = 100000U;
    while (DL_MCAN_getOpMode(can) != DL_MCAN_OPERATION_MODE_NORMAL)
        if (!--remaining) return false;
    return true;
}
#endif
