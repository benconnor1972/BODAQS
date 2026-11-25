#ifndef BODAQS_NODE_IMU_SPI_H
#define BODAQS_NODE_IMU_SPI_H
#include <stdbool.h>
#include <stdint.h>
int bodaqs_node_imu_register(void *, bool, uint8_t, uint8_t *, uint32_t);
void bodaqs_node_imu_cancel(void *);
/* Main-loop DMA exchange; payload excludes command-phase RX junk. */
int bodaqs_node_imu_read(uint8_t address, uint16_t bytes, const uint8_t **data, uint32_t now);
void bodaqs_node_imu_spi_irq(void);
bool bodaqs_node_imu_spi_pending(void);
#endif
