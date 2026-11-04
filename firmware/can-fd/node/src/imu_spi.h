#ifndef BODAQS_NODE_IMU_SPI_H
#define BODAQS_NODE_IMU_SPI_H
#include <stdbool.h>
#include <stdint.h>
int bodaqs_node_imu_register(void *, bool, uint8_t, uint8_t *, uint32_t);
void bodaqs_node_imu_cancel(void *);
#endif
