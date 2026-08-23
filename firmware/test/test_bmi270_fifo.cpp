#include <cstdio>

#include "BMI270FifoParser.h"
#include "BMI270FifoReadPlan.h"
#include "BMI270ImuTiming.h"
#include "BMI270ProgressWatchdog.h"
#include "BMI270SessionQuality.h"
#include "FixedSpscQueue.h"
#include "I2CLowPriorityWindow.h"

namespace {

void putI16_(uint8_t* destination, int16_t value) {
    const uint16_t raw = static_cast<uint16_t>(value);
    destination[0] = static_cast<uint8_t>(raw & 0xFFu);
    destination[1] = static_cast<uint8_t>(raw >> 8);
}

void putCombined_(
    uint8_t* destination,
    int16_t gx,
    int16_t gy,
    int16_t gz,
    int16_t ax,
    int16_t ay,
    int16_t az) {
    destination[0] = 0x8C;
    putI16_(&destination[1], gx);
    putI16_(&destination[3], gy);
    putI16_(&destination[5], gz);
    putI16_(&destination[7], ax);
    putI16_(&destination[9], ay);
    putI16_(&destination[11], az);
}

} // namespace

int runBMI270FifoTests() {
    int passed = 0;
    int failed = 0;

    auto check = [&](bool condition, const char* description) {
        if (condition) {
            ++passed;
        } else {
            printf("    FAIL: test_bmi270_fifo: %s\n", description);
            ++failed;
        }
    };

    {
        uint8_t data[17] {};
        putCombined_(data, -1, 2, -32768, 32767, -2, 3);
        data[13] = 0x44;
        data[14] = 0x56;
        data[15] = 0x34;
        data[16] = 0x12;
        BMI270FifoParsedSample output[2] {};
        const BMI270FifoParseResult result =
            BMI270FifoParser::parseHeaderMode(data, sizeof(data), output, 2);

        check(result.samplesWritten == 1, "combined frame parsed once");
        check(result.sampleFrames == 1, "combined frame counted once");
        check(output[0].gyroX == -1 && output[0].gyroY == 2 && output[0].gyroZ == -32768,
              "gyro axes preserve signed little-endian values");
        check(output[0].accelX == 32767 && output[0].accelY == -2 && output[0].accelZ == 3,
              "accel axes preserve signed little-endian values");
        check(result.sensorTimePresent && result.sensorTime == 0x123456,
              "24-bit sensor-time frame parsed");
        check(result.sensorTimeAnchorByteOffset == 13,
              "sensor-time capture byte position is retained for host correlation");
    }

    {
        uint8_t data[15] { 0x40, 0x02 };
        putCombined_(&data[2], 1, 2, 3, 4, 5, 6);
        BMI270FifoParsedSample output[1] {};
        const BMI270FifoParseResult result =
            BMI270FifoParser::parseHeaderMode(data, sizeof(data), output, 1);

        check(result.skippedFrames == 2 && result.skipControlFrames == 1,
              "FIFO skip control frame counted");
        check(output[0].skippedFramesBefore == 2,
              "hardware loss attaches to the following sample");
        check((output[0].statusBefore & BMI270ImuStatus::kFifoDiscontinuityBefore) != 0,
              "following sample carries FIFO discontinuity");
    }

    {
        uint8_t data[20] { 0x84, 1, 0, 2, 0, 3, 0 };
        putCombined_(&data[7], 4, 5, 6, 7, 8, 9);
        BMI270FifoParsedSample output[1] {};
        const BMI270FifoParseResult result =
            BMI270FifoParser::parseHeaderMode(data, sizeof(data), output, 1);

        check(result.unpairedFrames == 1, "unpaired accelerometer frame counted");
        check((output[0].statusBefore & BMI270ImuStatus::kTimingDegraded) != 0,
              "unpaired frame degrades the following sample");
    }

    {
        const uint8_t partial[] = { 0x8C, 1, 2, 3 };
        BMI270FifoParsedSample output[1] {};
        const BMI270FifoParseResult result =
            BMI270FifoParser::parseHeaderMode(partial, sizeof(partial), output, 1);
        check(result.partialFrames == 1 && result.samplesWritten == 0,
              "partial combined frame is rejected and counted");
        check((result.pendingStatus & BMI270ImuStatus::kFifoDiscontinuityBefore) != 0,
              "partial frame marks a future discontinuity");
    }

    {
        const uint8_t controls[] = { 0x48, 1, 2, 3, 4, 0x7C };
        BMI270FifoParsedSample output[1] {};
        const BMI270FifoParseResult result =
            BMI270FifoParser::parseHeaderMode(controls, sizeof(controls), output, 1);
        check(result.inputConfigFrames == 1 && result.invalidHeaders == 1,
              "input-configuration and invalid headers are counted separately");
        check((result.pendingStatus & BMI270ImuStatus::kTimingDegraded) != 0,
              "unexpected control stream degrades future timing");

        const uint8_t overread[] = { 0x80, 0, 0, 0 };
        const BMI270FifoParseResult overreadResult =
            BMI270FifoParser::parseHeaderMode(overread, sizeof(overread), output, 1);
        check(overreadResult.overreadSeen && overreadResult.invalidHeaders == 0,
              "normal FIFO over-read marker terminates parsing without an error");
    }

    {
        uint8_t data[26] {};
        putCombined_(data, 1, 2, 3, 4, 5, 6);
        putCombined_(&data[13], 7, 8, 9, 10, 11, 12);
        BMI270FifoParsedSample ordered[2] {};
        const BMI270FifoParseResult orderedResult =
            BMI270FifoParser::parseHeaderMode(data, sizeof(data), ordered, 2);
        check(orderedResult.samplesWritten == 2 &&
              ordered[0].gyroX == 1 && ordered[1].gyroX == 7 &&
              ordered[0].accelX == 4 && ordered[1].accelX == 10,
              "multi-frame batch preserves sample and axis order");

        BMI270FifoParsedSample output[1] {};
        const BMI270FifoParseResult result =
            BMI270FifoParser::parseHeaderMode(data, sizeof(data), output, 1);
        check(result.sampleFrames == 2 && result.outputDrops == 1,
              "bounded parser output drops only the overflow suffix");
        check((result.pendingStatus & BMI270ImuStatus::kQueueDropBefore) != 0,
              "parser overflow marks the next retained sample");
    }

    {
        BMI270FifoParsedSample parsed[2] {};
        parsed[1].skippedFramesBefore = 1;
        bool havePrevious = false;
        uint32_t previous = 0;
        const bool assigned = BMI270FifoParser::assignSensorTimes200Hz(
            parsed, 2, true, 0x0000C5, havePrevious, previous);

        check(assigned && parsed[1].sensorTime == 0x000080,
              "last sample is aligned to the 200 Hz sensor-time grid");
        check(parsed[0].sensorTime == 0xFFFF80,
              "sensor time backfill accounts for skips and 24-bit wrap");
        check(havePrevious && previous == 0x000080,
              "sensor-time continuation state updated");
        check((parsed[0].statusBefore & BMI270ImuStatus::kSensorTimeEstimated) != 0,
              "backfilled sensor time is explicitly estimated");

        BMI270FifoParsedSample continuedParsed[1] {};
        previous = 0xFFFFC0;
        havePrevious = true;
        BMI270FifoParser::assignSensorTimes200Hz(
            continuedParsed, 1, false, 0, havePrevious, previous);
        check(continuedParsed[0].sensorTime == 0x000040,
              "missing-anchor continuation wraps the native clock explicitly");
        check((continuedParsed[0].statusBefore & BMI270ImuStatus::kTimingDegraded) != 0,
              "missing sensor-time anchor degrades timing confidence");

        BMI270FifoParsedSample unanchored[1] {};
        previous = 0;
        havePrevious = false;
        const bool unanchoredAssigned = BMI270FifoParser::assignSensorTimes200Hz(
            unanchored, 1, false, 0, havePrevious, previous);
        check(!unanchoredAssigned && unanchored[0].sensorTime == 0,
              "an initial batch without sensor time remains explicitly unanchored");

        BMI270FifoParsedSample discontinuous[1] {};
        previous = 0x000080;
        havePrevious = true;
        BMI270FifoParser::assignSensorTimes200Hz(
            discontinuous, 1, true, 0x000285, havePrevious, previous);
        check((discontinuous[0].statusBefore &
               BMI270ImuStatus::kFifoDiscontinuityBefore) != 0,
              "inconsistent consecutive anchors mark a discontinuity");
        check(discontinuous[0].sensorTimeDiscontinuityBefore,
              "native-clock discontinuities remain separately countable");
    }

    {
        BMI270StartupObservation observation;
        observation.begin(3);
        for (uint32_t sequence = 0;
             sequence < BMI270StartupObservation::kSettlingCleanSamples + 600;
             ++sequence) {
            observation.observe(
                sequence,
                0, 0, 2048,
                2, -3, 1,
                512, true,
                BMI270ImuStatus::kSensorTimeEstimated);
        }
        const BMI270StartupObservationResult& result = observation.result();
        check(result.state == BMI270StartupObservationState::Accepted &&
              result.nativeSampleRateHz == 200 &&
              result.minimumValidFraction == 0.5f &&
              result.targetSampleSlots == 600 &&
              result.minimumValidSamples == 300,
              "startup minimum coverage scales with window and native rate");
    }

    {
        BMI270StartupObservation observation;
        observation.begin(3, 100);
        for (uint32_t sequence = 0;
             sequence < BMI270StartupObservation::kSettlingCleanSamples + 150;
             ++sequence) {
            observation.observe(
                sequence,
                0, 0, 2048,
                0, 0, 0,
                0, false,
                0);
        }
        observation.finish();
        check(observation.result().state == BMI270StartupObservationState::Accepted &&
              observation.result().targetSampleSlots == 300 &&
              observation.result().minimumValidSamples == 150,
              "partial startup observations accept at the configured coverage threshold");

        observation.begin(3, 100);
        for (uint32_t sequence = 0;
             sequence < BMI270StartupObservation::kSettlingCleanSamples + 149;
             ++sequence) {
            observation.observe(
                sequence,
                0, 0, 2048,
                0, 0, 0,
                0, false,
                0);
        }
        observation.finish();
        check(observation.result().state == BMI270StartupObservationState::Rejected &&
              (observation.result().rejectionMask &
               BMI270StartupRejection::kInsufficientSamples) != 0,
              "partial startup observations below the coverage threshold are rejected");
    }

    {
        BMI270StartupObservation observation;
        observation.begin(5);
        for (uint32_t sequence = 0;
             sequence < BMI270StartupObservation::kSettlingCleanSamples + 1000;
             ++sequence) {
            observation.observe(
                sequence,
                0, 0, 2048,
                2, -3, 1,
                512, true,
                BMI270ImuStatus::kSensorTimeEstimated);
        }
        const BMI270StartupObservationResult& result = observation.result();
        check(result.state == BMI270StartupObservationState::Accepted &&
              result.rejectionMask == 0,
              "stationary startup observation is accepted");
        check(result.validSamples == 1000 && result.temperatureSamples == 1000,
              "startup observation reports sample coverage");
        check(result.settlingSampleSlots ==
                  BMI270StartupObservation::kSettlingCleanSamples &&
              result.measurementStartSequence ==
                  BMI270StartupObservation::kSettlingCleanSamples,
              "startup observation discards a bounded clean settling window");
        check(result.accelMagnitudeMeanG == 1.0 &&
              result.accelMagnitudeStdG == 0.0,
              "startup observation reports gravity magnitude without changing raw samples");
        check(result.gyroMeanRaw[0] == 2.0 &&
              result.gyroMeanRaw[1] == -3.0 &&
              result.gyroMeanRaw[2] == 1.0,
              "startup observation retains gyro bias estimates in raw counts");
        check(result.temperatureMeanC == 24.0 &&
              result.temperatureMinimumC == 24.0 &&
              result.temperatureMaximumC == 24.0,
              "startup observation reports the fresh temperature range");
    }

    {
        BMI270StartupObservation observation;
        observation.begin(5);
        for (uint32_t sequence = 0;
             sequence < BMI270StartupObservation::kSettlingCleanSamples + 1000;
             ++sequence) {
            BMI270ImuSample sample;
            sample.sequence = sequence;
            sample.accelZ = 2048;
            sample.gyroX = 2;
            sample.gyroY = -3;
            sample.gyroZ = 1;
            sample.statusFlags = BMI270ImuStatus::kSensorTimeEstimated;
            if (sequence == 0) {
                sample.statusFlags |= BMI270ImuStatus::markPreSessionBoundary(
                    BMI270ImuStatus::kFifoDiscontinuityBefore |
                    BMI270ImuStatus::kSensorRecoveryBefore |
                    BMI270ImuStatus::kTimingDegraded);
            }
            observation.observe(
                sample.sequence,
                sample.accelX, sample.accelY, sample.accelZ,
                sample.gyroX, sample.gyroY, sample.gyroZ,
                512, true,
                sample.measurementStatusFlags());
        }
        check(observation.result().state == BMI270StartupObservationState::Accepted,
              "pre-session recovery boundary does not invalidate startup observation");
    }

    {
        BMI270StartupObservation observation;
        observation.begin(5);
        const uint16_t rejectedStatus =
            BMI270ImuStatus::kFifoDiscontinuityBefore |
            BMI270ImuStatus::kTimingDegraded;
        for (uint32_t sequence = 0;
             sequence < BMI270StartupObservation::kSettlingCleanSamples + 1001;
             ++sequence) {
            observation.observe(
                sequence,
                0, 0, 2048,
                0, 0, 0,
                0, false,
                sequence == 0 ? rejectedStatus : 0);
        }
        const BMI270StartupObservationResult& result = observation.result();
        check(result.state == BMI270StartupObservationState::Accepted,
              "a transient post-resume status is excluded by settling");
        check(result.settlingSampleSlots ==
                  BMI270StartupObservation::kSettlingCleanSamples + 1 &&
              result.settlingStatusMask == rejectedStatus &&
              result.measurementStartSequence ==
                  BMI270StartupObservation::kSettlingCleanSamples + 1,
              "settling restarts after a transient and records its status");
    }

    {
        BMI270StartupObservation observation;
        observation.begin(5);
        for (uint32_t sequence = 0;
             sequence < BMI270StartupObservation::kSettlingCleanSamples + 1000;
             ++sequence) {
            const int16_t accelZ = (sequence & 1u) ? 2048 : 2600;
            const int16_t gyroX = (sequence & 1u) ? 100 : -100;
            observation.observe(
                sequence,
                0, 0, accelZ,
                gyroX, 0, 0,
                0, false,
                0);
        }
        const BMI270StartupObservationResult& result = observation.result();
        check(result.state == BMI270StartupObservationState::Rejected,
              "moving startup observation is rejected");
        check((result.rejectionMask &
               BMI270StartupRejection::kAccelMagnitudeUnstable) != 0 &&
              (result.rejectionMask & BMI270StartupRejection::kGyroXUnstable) != 0 &&
              (result.rejectionMask & BMI270StartupRejection::kGyroMotionDetected) != 0,
              "startup rejection identifies motion and instability causes");
    }

    {
        BMI270StartupObservation observation;
        observation.begin(5);
        for (uint32_t sequence = 0;
             sequence < BMI270StartupObservation::kSettlingCleanSamples + 1000;
             ++sequence) {
            observation.observe(
                sequence,
                0, 0, 2048,
                0, 0, 0,
                0, false,
                sequence == BMI270StartupObservation::kSettlingCleanSamples + 500
                    ? BMI270ImuStatus::kTimingDegraded
                    : 0);
        }
        check((observation.result().rejectionMask &
               BMI270StartupRejection::kQualityIncident) != 0,
              "a transport or timing incident invalidates the stationary observation");

        observation.begin(5);
        for (uint32_t sequence = 0;
             sequence < BMI270StartupObservation::kMaximumSettlingSlots;
             ++sequence) {
            observation.observe(
                sequence,
                0, 0, 2048,
                0, 0, 0,
                0, false,
                BMI270ImuStatus::kTimingDegraded);
        }
        check(observation.result().state == BMI270StartupObservationState::Rejected &&
              (observation.result().rejectionMask &
               BMI270StartupRejection::kInsufficientSamples) != 0 &&
              (observation.result().rejectionMask &
               BMI270StartupRejection::kQualityIncident) != 0 &&
              observation.result().settlingStatusMask ==
                  BMI270ImuStatus::kTimingDegraded,
              "settling rejects deterministically when clean data never arrives");

        observation.begin(0);
        check(observation.result().state == BMI270StartupObservationState::Disabled,
              "zero seconds explicitly disables startup observation");
    }

    {
        BMI270AgeHistogram histogram;
        histogram.reset();
        histogram.add(100, true);
        histogram.add(300, true);
        histogram.add(1000, true);
        histogram.add(5000, true);
        histogram.add(70000, true);
        histogram.add(0, false);
        const BMI270AgeSummary result = histogram.summary();
        check(result.count == 5 && result.unavailable == 1 && result.clipped == 1,
              "acquisition-age histogram accounts for valid, unavailable, and clipped rows");
        check(result.minimumUs == 100 && result.maximumUs == 70000 &&
              result.resolutionUs == 256,
              "acquisition-age histogram preserves exact range and declared resolution");
        check(result.medianUs == 1023 && result.p95Us == 65535 &&
              result.p99Us == 65535,
              "acquisition-age percentile upper bounds are deterministic");
    }

    {
        check(BMI270FifoReadPlan::bytesToRead(13) == 43,
              "small FIFO burst includes in-flight frames and sensor time");
        check(BMI270FifoReadPlan::bytesToRead(2048) == 2221,
              "full FIFO burst remains within the configured Wire buffer");
        check(BMI270FifoReadPlan::bytesToRead(0) == 0 &&
              BMI270FifoReadPlan::bytesToRead(2049) == 0,
              "FIFO read planning rejects empty and invalid lengths");

        const uint64_t frameHostUs = BMI270ImuTiming::interpolateTransferTimeUs(
            1000, 2000, 75, 100);
        check(frameHostUs == 1750,
              "sensor-time host anchor is interpolated at its FIFO byte position");
        uint64_t sampleHostUs = 0;
        check(BMI270ImuTiming::estimateHostSampleTimeUs(
                  0x0000C5, 0x000080, 100000, sampleHostUs) &&
              sampleHostUs == 97305,
              "raw sensor-time phase maps a gridded sample into host time");
    }

    {
        BMI270ProgressWatchdog watchdog(250000);
        check(!watchdog.expired(1000), "progress watchdog is inert before session arm");
        watchdog.arm(1000);
        check(!watchdog.expired(250999),
              "progress watchdog leaves the full grace interval available");
        check(watchdog.expired(251000) && watchdog.elapsedUs(251000) == 250000,
              "progress watchdog expires at the configured interval");
        watchdog.recordProgress(200000);
        check(!watchdog.expired(449999) && watchdog.expired(450000),
              "native sample progress restarts the watchdog interval");

        BMI270ProgressWatchdog wrapping(500);
        wrapping.arm(0xFFFFFF00u);
        check(wrapping.expired(0x00000100u) && wrapping.elapsedUs(0x00000100u) == 512,
              "progress watchdog remains correct across micros wrap");
        wrapping.disarm();
        check(!wrapping.expired(0x00010000u),
              "progress watchdog can be disabled outside a logging session");

        BMI270RecoveryBudget recoveryBudget(3);
        check(recoveryBudget.reserveAttempt() && recoveryBudget.reserveAttempt() &&
              recoveryBudget.reserveAttempt(),
              "recovery budget permits the configured attempts without progress");
        check(!recoveryBudget.reserveAttempt() && recoveryBudget.exhausted(),
              "recovery budget prevents an unbounded successful-but-stalled loop");
        recoveryBudget.recordProgress();
        check(!recoveryBudget.exhausted() && recoveryBudget.attemptsWithoutProgress() == 0 &&
              recoveryBudget.reserveAttempt(),
              "a genuinely parsed sample restores the recovery budget");
    }

    {
        check(I2CLowPriorityWindow::fits(5000, 30000, 5000, 50000),
              "OLED transfer fits immediately after FIFO service");
        check(!I2CLowPriorityWindow::fits(16000, 30000, 5000, 50000),
              "low-priority transfer is deferred when FIFO service headroom is insufficient");
        check(!I2CLowPriorityWindow::fits(0, 1000, 1000, 0),
              "a client with no declared gap does not admit a transfer");
    }

    {
        FixedSpscQueue<uint32_t, 4> queue;
        size_t depth = 0;
        check(queue.push(10, &depth) && depth == 1, "queue accepts first item");
        check(queue.push(20) && queue.push(30) && queue.push(40),
              "queue uses its full declared capacity");
        check(!queue.push(50), "queue deterministically drops newest when full");
        uint32_t value = 0;
        check(queue.pop(value) && value == 10, "queue preserves oldest item");
        check(queue.pop(value) && value == 20, "queue preserves FIFO order");
        check(queue.push(50), "queue accepts data after consumer makes room");
        check(queue.size() == 3, "queue depth remains coherent");
        queue.clear();
        check(queue.empty(), "queue clear establishes an empty session boundary");
    }

    printf("BMI270 FIFO: %d passed, %d failed\n", passed, failed);
    return failed;
}
