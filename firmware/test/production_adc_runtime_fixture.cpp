// BASE_ADC_MODEL

std::vector<RawAdcRecord> captured;
unsigned targetRows = 16;
LocalAnalogRecordingPlan expectedPlan;
bool captureProductionRow() {
  RawAdcRecord record;
  uint32_t missed = 0;
  uint64_t deadline = 0, observed = 0;
  assert(AnalogInputManager::recordingRowTiming(record.sequence, missed, deadline));
  assert(uint64_t(nowUs) >= deadline);
  assert(AnalogInputManager::captureRawPair(record, observed));
  assert(observed >= deadline);
  for (unsigned field = 0; field < expectedPlan.columns(); ++field) {
    const auto& input = expectedPlan.column(field);
    const auto conversion = input.external ? delivered[input.adc][input.channel] : 0;
    const uint16_t expected = input.external
        ? (conversion < 0 ? 0 : uint16_t(double(conversion) * 4095.0 / 8388607.0 + 0.5)) : 123;
    assert(record.counts[field] == expected);
  }
  uint8_t encoded[sizeof(RawAdcRecord)] = {};
  assert(RawAdcRecording::encode(record, encoded, sizeof(encoded), expectedPlan.columns()));
  assert(!memcmp(encoded, &record, RawAdcRecording::recordBytes(expectedPlan.columns())));
  captured.push_back(record);
  if (captured.size() == targetRows) s_scanRun.store(false);
  return true;
}

void run(const LocalAnalogRecordingPlan& plan, bool delayed = false, bool badReadback = false) {
  auto board = profile();
  AnalogInputManager::begin(board);
  assert(resolution == 12);
  LoggerConfig config;
  config.sampleRateHz = plan.rateHz();
  assert(AnalogInputManager::configureFromConfig(config, plan.rateHz()) == plan.rateHz());
  assert(AnalogInputManager::reserveScanTask());
  assert(AnalogInputManager::setRecordingPlan(plan));
  expectedPlan = plan;
  assert(AnalogInputManager::setScanRowCapture(captureProductionRow));
  captured.clear(); notifications = 0;
  AnalogInputManager::onLoggingStart();
  assert(AnalogInputManager::continuousHealthy());
  assert(!s_scanRun.load() && !s_timingWorkers.load()); // preparation cannot publish rows
  assert(AnalogInputManager::activateRecordingPlan());
  wire.clear();
  lateWake = delayed ? 7000 : 0;
  corruptReadback = badReadback;
  earlyHints = true;
  try { concentratedTask_(nullptr); } catch (const Parked&) {}
  assert(!s_timingWorkers.load() && !timer.armed);
  if (badReadback) {
    assert(s_scanFault.load() && captured.empty());
  } else {
    assert(captured.size() == targetRows);
    bool gap = false;
    for (unsigned i = 1; i < captured.size(); ++i) {
      assert(captured[i].sequence > captured[i-1].sequence);
      gap |= captured[i].sequence != captured[i-1].sequence + 1;
    }
    assert(!delayed || gap || captured.front().sequence > 0);
  }
  for (const auto& transaction : wire)
    assert(plan.mask(unsigned(transaction.cs - 10))); // no conversion on idle ADC
  assert(AnalogInputManager::retireScanRowCapture());
  AnalogInputManager::onLoggingStop();
  assert(AnalogInputManager::stoppedTimingStats());
}

int main() {
  LocalAnalogRecordingPlan plan;
  assert(plan.configure(500));
  assert(plan.addExternal(0, 0, 0) && plan.addExternal(1, 1, 0));
  run(plan);
  negativeConversions = true;
  run(plan);
  for (const auto& row : captured) assert(row.counts[0] == 0 && row.counts[1] == 0);
  negativeConversions = false;
  assert(earlyWakeCount > 0); // exercised stale wake hints, not just exact deadlines
  // Deliberately non-diagnostic column order and unequal sparse physical masks.
  assert(plan.configure(650));
  assert(plan.addExternal(7, 0, 3) && plan.addExternal(2, 1, 2) && plan.addExternal(3, 0, 1));
  run(plan);
  run(plan, true);
  assert(plan.configure(1200) && plan.addExternal(0, 1, 3));
  run(plan); // ADC0 idle, fractional row period
  assert(plan.configure(700) && plan.addGpio(0, 12));
  run(plan); // both external ADCs idle
  assert(plan.configure(1000) && plan.addExternal(0, 0, 2));
  run(plan, false, true); // full register proof rejects a wrong channel image
  run(plan); // retired failure must not poison the next explicit session
  auto board = profile();
  AnalogInputManager::begin(board);
  assert(AnalogInputManager::setRecordingPlan(plan));
  assert(AnalogInputManager::setScanRowCapture(captureProductionRow));
  captured.clear(); notifications = 0;
  AnalogInputManager::onLoggingStart();
  assert(AnalogInputManager::activateRecordingPlan());
  failArm = true;
  try { concentratedTask_(nullptr); } catch (const Parked&) {}
  assert(s_scanFault.load() && !s_timingWorkers.load() && captured.empty());
  failArm = false;
  AnalogInputManager::onLoggingStop();
  puts("Production ADC owner: sparse/unequal/idle/direct, fractional timer, late/stale wakes, register proof, timer failure and restart passed");
}
