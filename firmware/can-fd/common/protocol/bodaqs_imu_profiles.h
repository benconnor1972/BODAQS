#ifndef BODAQS_IMU_PROFILES_H
#define BODAQS_IMU_PROFILES_H
#include <stdint.h>
/* Stable native six-axis identities. Version1 retains32g/2000dps and the
 * existing optional-filter bypass policy; these are nominal rates, not clocks. */
static inline uint32_t bodaqs_imu_profile_rate(uint16_t id) {
    return id==1?3333U:id==2?1667U:id==3?833U:0U;
}
static inline uint8_t bodaqs_imu_profile_odr(uint16_t id) {
    return id==1?0x90:id==2?0x80:id==3?0x70:0;
}
static inline const char *bodaqs_imu_profile_name(uint16_t id) {
    return id==1?"imu6_3333_32g_2000dps_v1":id==2?"imu6_1667_32g_2000dps_v1":id==3?"imu6_833_32g_2000dps_v1":"";
}
static inline int bodaqs_imu_profile_supported(uint16_t id,uint16_t version) {
    return version==1 && bodaqs_imu_profile_rate(id)!=0;
}
/* Profile identity and nominal rates travel together in schema3/v1. */
static inline uint32_t bodaqs_imu_profile_u32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1]<<8) | ((uint32_t)p[2]<<16) | ((uint32_t)p[3]<<24);
}
static inline int bodaqs_imu_profile_matches_effective(uint16_t id,const uint8_t *d) {
    const uint32_t rate=bodaqs_imu_profile_rate(id);
    return d && rate && d[40]==id && !d[41] && d[42]==1 && !d[43] &&
        bodaqs_imu_profile_u32(d+48)==rate && bodaqs_imu_profile_u32(d+52)==1 &&
        bodaqs_imu_profile_u32(d+56)==rate && bodaqs_imu_profile_u32(d+60)==1;
}
#endif
