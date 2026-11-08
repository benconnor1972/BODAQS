#pragma once
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
#include "BoardProfile.h"
#include "TimingStats.h"
#include "SharedSpiBus.h"
namespace SpiProbeTransport {
enum class CrcMode { Legacy, Cached };
struct FailureSample {
  uint8_t reason=0,opcode=0,node=0,fragment=0,profile=0;
  uint16_t frameBytes=0;
  uint32_t slot=0,caseId=0,objectId=0,logicalCrc=0;
  SharedSpiBus::ProbeContext bus;
  uint8_t rx[256]={};
};
struct PreviousParticipant {
  int8_t cs=-1;
  uint32_t responses=0,decodeFailures=0;
  bool used=false;
};
struct PreviousOperation {
  SharedSpiBus::ProbeOperation operation;
  int8_t cs=-1;
  uint32_t responses=0,decodeFailures=0;
  bool used=false;
};
struct Stats {
  uint32_t slots=0,validResponses=0,uniqueObjects=0,retiredObjects=0;
  uint64_t acceptedBytes=0;
  uint32_t transferErrors=0,wireErrors=0,stale=0,duplicates=0,acceptErrors=0;
  TimingSummary slot,guard,encode,decode,validate,expectedCrc,objectCrc,iteration,requestInterval;
  // Active request exchanges only: control entry/STATS/STOP are excluded.
  uint32_t decodeCounts[9]={};
  FailureSample failures[4];
  uint8_t failureCount=0;
  uint32_t failureSamplesOmitted=0,pacingDeferred=0,switchTransfers=0,switchFailures=0;
  uint32_t csGuardDeferred=0,intervalDeferred=0;
  PreviousParticipant byPreviousCs[10];
  PreviousOperation byPreviousOperation[16];
  uint32_t operationBucketsOmitted=0;
  // Timed dispatch attempts, including transfers of uncertain delivery.
  bool pipelined=false,clockOnly=false;
  bool flowMeasured=false;
  uint32_t flowBefore[10]={},flowAfter[10]={};
  uint32_t newRequests=0,retryRequests=0,clockRequests=0,retryExhausted=0;
  uint32_t pendingRequests=0,pendingHighWater=0;
  TimingSummary replyAge;
  // STATS2 endpoints: counters wrap; boot maxima/sticky invalid state are not deltas.
  bool diagnosticMeasured=false;
  uint32_t diagnosticBefore[10]={},diagnosticAfter[10]={};
  bool processingMeasured=false;
  uint32_t processingBefore[10]={},processingAfter[10]={};
  uint32_t processingMetaBefore[10]={},processingMetaAfter[10]={};
  bool receiveMeasured=false;
  uint32_t receiveBefore[10]={},receiveAfter[10]={};
  uint32_t turnoverBefore[10]={},turnoverAfter[10]={};
  bool masterMeasured=false,adapterMeasured=false;
  uint32_t masterBefore[10]={},masterAfter[10]={};
  uint32_t adapterBefore[10]={},adapterAfter[10]={};
};
bool begin(const board::BoardProfile& board,uint32_t caseId,uint16_t bytes,uint32_t hz,uint8_t nodes,
    CrcMode crcMode=CrcMode::Legacy,uint32_t startIntervalUs=0,bool switchMode=false,
    bool pipelined=false,bool clockOnly=false);
void tick();
// Owner-loop query for sequential controls; no locks, sleeps or transfers.
bool requestDue();
bool healthy();
bool stop();
const Stats& stats();
}
#endif
