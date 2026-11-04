#ifndef BODAQS_NODE_IMU_ACQUISITION_H
#define BODAQS_NODE_IMU_ACQUISITION_H
#include "bodaqs_control_acquisition.h"
#include "bodaqs_imu_disabled.h"
#include <stddef.h>
typedef bool (*BodaqsNodeCanSend)(uint16_t, const uint8_t *, size_t);
void bodaqs_node_acquisition_init(uint32_t boot, uint8_t address, BodaqsImuDisabled *,
                                  BodaqsNodeCanSend, bool (*transmit_idle)(void));
void bodaqs_node_acquisition_backend(void *, uint8_t, uint32_t, uint64_t, uint32_t,
                                     BodaqsAcquisitionEvent *);
void bodaqs_node_acquisition_service(uint32_t now);
#endif
