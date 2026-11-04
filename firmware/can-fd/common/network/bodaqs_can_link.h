#ifndef BODAQS_CAN_LINK_H
#define BODAQS_CAN_LINK_H
#include <stdbool.h>
#include <stdint.h>

#define BODAQS_CAN_LINK_UNKNOWN 0U
#define BODAQS_CAN_LINK_BRINGUP 1U
#define BODAQS_CAN_LINK_ACQUISITION 2U
/* Explicit selected-link observations in existing capability words. These bits
 * do not assert electrical, scheduling or throughput qualification. */
#define BODAQS_CAN_LINK_CAP_BRINGUP (1UL << 28)
#define BODAQS_CAN_LINK_CAP_ACQUISITION (1UL << 29)
#define BODAQS_CAN_LINK_CAP_MASK (BODAQS_CAN_LINK_CAP_BRINGUP | BODAQS_CAN_LINK_CAP_ACQUISITION)
#ifndef BODAQS_CAN_LINK_PROFILE
#define BODAQS_CAN_LINK_PROFILE BODAQS_CAN_LINK_BRINGUP
#endif
#if BODAQS_CAN_LINK_PROFILE != 1 && BODAQS_CAN_LINK_PROFILE != 2
#error Unsupported BODAQS_CAN_LINK_PROFILE
#endif

static inline uint32_t bodaqs_can_link_capability(uint8_t profile) {
    return profile == BODAQS_CAN_LINK_BRINGUP ? BODAQS_CAN_LINK_CAP_BRINGUP :
        profile == BODAQS_CAN_LINK_ACQUISITION ? BODAQS_CAN_LINK_CAP_ACQUISITION : 0;
}
static inline uint8_t bodaqs_can_link_from_capabilities(uint32_t capabilities) {
    const uint32_t selected = capabilities & BODAQS_CAN_LINK_CAP_MASK;
    return selected == BODAQS_CAN_LINK_CAP_BRINGUP ? BODAQS_CAN_LINK_BRINGUP :
        selected == BODAQS_CAN_LINK_CAP_ACQUISITION ? BODAQS_CAN_LINK_ACQUISITION : BODAQS_CAN_LINK_UNKNOWN;
}
static inline bool bodaqs_can_link_compatible(uint32_t master, uint32_t node) {
    const uint8_t selected = bodaqs_can_link_from_capabilities(master);
    return selected != BODAQS_CAN_LINK_UNKNOWN && selected == bodaqs_can_link_from_capabilities(node);
}
static inline uint32_t bodaqs_can_link_arbitration_hz(uint8_t profile) {
    return profile == BODAQS_CAN_LINK_BRINGUP ? 500000U :
        profile == BODAQS_CAN_LINK_ACQUISITION ? 1000000U : 0;
}
static inline uint32_t bodaqs_can_link_data_hz(uint8_t profile) {
    return profile == BODAQS_CAN_LINK_BRINGUP ? 2000000U :
        profile == BODAQS_CAN_LINK_ACQUISITION ? 4000000U : 0;
}
#endif
