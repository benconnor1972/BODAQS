#pragma once
#include <stdint.h>
#include <stddef.h>
#define MSBFIRST 1
#define SPI_MODE0 0
#define SPI_MODE1 1
struct SPISettings {
  uint32_t hz; uint8_t order, mode;
  SPISettings(uint32_t h=1000000, uint8_t o=MSBFIRST, uint8_t m=SPI_MODE0):hz(h),order(o),mode(m){}
};
struct SPIClass {
  void begin(int8_t, int8_t, int8_t);
  void beginTransaction(const SPISettings& settings);
  void endTransaction();
  void transferBytes(const uint8_t* tx, uint8_t* rx, size_t length);
};
extern SPIClass SPI;
