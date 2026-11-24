#pragma once

#include <Arduino.h>
#include <stdint.h>
#include "BoardProfile.h"
#include "TimingStats.h"
#include "LocalRowHandoff.h"
#include "RawAdcRecording.h"

#ifndef BODAQS_ADC_ROW_HANDOFF
#define BODAQS_ADC_ROW_HANDOFF 0
#endif
#ifndef BODAQS_ADC_COMBINED_CAPTURE
#define BODAQS_ADC_COMBINED_CAPTURE 0
#endif
#if BODAQS_ADC_COMBINED_CAPTURE && !BODAQS_ADC_ROW_HANDOFF
#error "Combined capture requires the immutable row handoff"
#endif
#if BODAQS_ADC_ROW_HANDOFF && (!BODAQS_ADC_CONCENTRATED_SCAN_BENCH || !BODAQS_ADC_SCAN_PIPELINE)
#error "Row handoff requires the verified concentrated pipeline bench"
#endif

struct LoggerConfig;

#ifndef BODAQS_ADC_ROW_PACING
#define BODAQS_ADC_ROW_PACING 0
#endif
#if BODAQS_ADC_ROW_PACING != 0 && BODAQS_ADC_ROW_PACING != 1
#error "ADC row pacing must be 0 or 1"
#endif
#ifndef BODAQS_ADC_CONTINUOUS_LATEST
#define BODAQS_ADC_CONTINUOUS_LATEST 0
#endif
#if BODAQS_ADC_CONTINUOUS_LATEST != 0 && BODAQS_ADC_CONTINUOUS_LATEST != 1
#error "Continuous latest flag must be 0 or 1"
#endif
#if BODAQS_ADC_CONTINUOUS_LATEST && BODAQS_ADC_ROW_PACING
#error "Continuous latest and row-paced conversion are mutually exclusive"
#endif
#ifndef BODAQS_ADC_SCAN_ROW_PHASE
#define BODAQS_ADC_SCAN_ROW_PHASE 0
#endif
#if BODAQS_ADC_SCAN_ROW_PHASE && !BODAQS_ADC_SCAN_PIPELINE
#error "Row phase requires pipeline"
#endif
namespace AnalogInputManager {
#if BODAQS_ADC_COMBINED_CAPTURE
  // Idle START only; immutable until scan retirement. Called by the scan owner
  // after all selected channels on both ADCs verify; never STOP/wait on its owner.
  bool scanRowCaptureEligible();
  bool setScanRowCapture(bool (*capture)());
  // STOP: retire the producer but retain cache/snapshot session until rows drain.
  bool retireScanRowCapture();
#endif
#if BODAQS_ADC_ROW_HANDOFF
  bool rowHandoffActive();
  bool captureRowSnapshot(LocalAdcSnapshot& snapshot);
#if BODAQS_ADC_RAW_RECORDING_BENCH
  // Verified scan owner only; exact ADC0/ADC1 channel0 raw trial, no sensor calls.
  bool captureRawPair(RawAdcRecord& record,uint64_t& capturedUs);
#endif
  // Consumer task only; caller retains snapshot through sampleValues and clears
  // before returning. Other tasks continue to see the ordinary live cache.
  void useRowSnapshot(const LocalAdcSnapshot* snapshot);
  // Row owner only: same freshness accounting, with an explicitly borrowed view.
  // Preview tasks must continue using readCounts().
  bool readSnapshotCounts(uint8_t ain, int32_t& counts, const LocalAdcSnapshot& snapshot);
#endif
#if BODAQS_ADC_SCAN_ROW_PHASE
  bool scanRowPhaseActive();
  // Pending until the first validated pipeline publication; no hardware access.
  bool scanRowDeadline(int64_t nowUs,int64_t& deadline);
#endif
#if BODAQS_ADC_CONCENTRATED_SCAN_BENCH
  // Idle startup only, after configureFromConfig and Wi-Fi shutdown, before
  // recording buffers/SD I/O. No-op outside the explicitly selected bench scope.
  // Retains one parked worker across recordings; never starts ADC acquisition.
  bool reserveScanTask();
#endif
#if BODAQS_ADC_CONTINUOUS_LATEST
  bool continuousHealthy();
#endif
#if BODAQS_ADC_ROW_PACING
  // Startup only. Returns first row deadline, or zero if resources/scope failed.
  int64_t beginRowPacing();
#endif


  void begin(const board::BoardProfile& board);

  bool available(uint8_t ain);
  bool inputIsExternal(uint8_t ain);
  int8_t pinForAin(uint8_t ain);

  bool readCounts(uint8_t ain, int32_t& outCounts);

  // Scans configured, unmuted analog sensors and selects an effective logging
  // rate that each external ADC can actually service.
  uint16_t configureFromConfig(const LoggerConfig& cfg, uint16_t requestedHz);
  uint16_t effectiveSampleRateHz();
  uint16_t requestedSampleRateHz();
  uint8_t activeChannelCount(uint8_t externalAdcIndex);
  uint16_t configuredDataRateSps(uint8_t externalAdcIndex);
  void resetTimingStats();
  const ExternalAdcTimingStats& timingStats();
  // Finalization only, after the row producer stops. Null while an ADC worker
  // can still mutate timing totals; a non-null result remains valid until start.
  const ExternalAdcTimingStats* stoppedTimingStats();
  void onLoggingStart();
  void onLoggingStop();

  // Called once around each logger sample so external ADC channels can be
  // converted once and then reused by all sensor columns in that row.
  void beginSample();
  void endSample();

} // namespace AnalogInputManager
