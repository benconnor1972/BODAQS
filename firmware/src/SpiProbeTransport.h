#pragma once
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
#include "BoardProfile.h"
#include "TimingStats.h"
namespace SpiProbeTransport {
struct Stats {
  uint32_t slots=0,validResponses=0,uniqueObjects=0,retiredObjects=0;
  uint64_t acceptedBytes=0;
  uint32_t transferErrors=0,wireErrors=0,stale=0,duplicates=0,acceptErrors=0;
  TimingSummary slot,guard,encode,decode;
  bool masterMeasured=false,adapterMeasured=false;
  uint32_t masterBefore[10]={},masterAfter[10]={};
  uint32_t adapterBefore[10]={},adapterAfter[10]={};
};
bool begin(const board::BoardProfile& board,uint32_t caseId,uint16_t bytes,uint32_t hz,uint8_t nodes);
void tick();
bool healthy();
bool stop();
const Stats& stats();
}
#endif
