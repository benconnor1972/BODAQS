#include <cstdio>

#include "BMI270Profile.h"
#include "BMI270Mount.h"
#include "BMI270ImuTiming.h"
#include "BMI270SparseRow.h"
#include "ImuOrientation.h"

int runBMI270ProfileTests() {
    int passed = 0;
    int failed = 0;

    auto check = [&](bool condition, const char* description) {
        if (condition) {
            ++passed;
        } else {
            printf("    FAIL: test_bmi270_profile: %s\n", description);
            ++failed;
        }
    };

    check(BMI270Profile::isSupportedAddress(0x68), "primary I2C address accepted");
    check(BMI270Profile::isSupportedAddress(0x69), "secondary I2C address accepted");
    check(!BMI270Profile::isSupportedAddress(0x67), "unrelated I2C address rejected");

    BMI270Profile::EffectiveConfig config = BMI270Profile::orientation200Expected();
    check(BMI270Profile::matchesOrientation200(config), "canonical profile matches");

    config.accelOdr = 0;
    check(!BMI270Profile::matchesOrientation200(config), "accelerometer ODR mismatch rejected");
    config = BMI270Profile::orientation200Expected();
    config.accelRange = 0;
    check(!BMI270Profile::matchesOrientation200(config), "accelerometer range mismatch rejected");
    config = BMI270Profile::orientation200Expected();
    config.gyroOdr = 0;
    check(!BMI270Profile::matchesOrientation200(config), "gyroscope ODR mismatch rejected");
    config = BMI270Profile::orientation200Expected();
    config.gyroRange = 1;
    check(!BMI270Profile::matchesOrientation200(config), "gyroscope range mismatch rejected");
    config = BMI270Profile::orientation200Expected();
    config.gyroNoisePerformance = 1;
    check(!BMI270Profile::matchesOrientation200(config), "gyroscope noise mode mismatch rejected");

    check(BMI270Profile::kOdrHz == 200, "native ODR remains 200 Hz");
    check(BMI270Profile::kLoggerRateHz == 500, "logger rate remains 500 Hz");
    check(BMI270Profile::kInitializationAttempts == 5, "initialization retry count remains bounded");

    BMI270MountTransform mount;
    check(BMI270Mount::parseTransform("+x", "+y", "+z", mount),
          "identity mounting transform accepted");
    check(BMI270Mount::determinant(mount) == 1,
          "identity mounting transform is right handed");
    check(BMI270Mount::parseTransform("+y", "-x", "+z", mount),
          "rotated right-handed mounting transform accepted");
    check(!BMI270Mount::parseTransform("+x", "+x", "+z", mount),
          "duplicate sensor axis rejected");
    check(!BMI270Mount::parseTransform("+x", "+y", "-z", mount),
          "left-handed mounting transform rejected");
    check(!BMI270Mount::parseTransform("x", "+y", "+z", mount),
          "unsigned mounting axis rejected");
    check(!BMI270Mount::parseTransform("+X", "+y", "+z", mount),
          "non-canonical mounting axis rejected");

    const float meanAccel[] = {400.0f, 50.0f, 2000.0f};
    float orientation[3][3] {};
    float rollDeviation = 0.0f;
    check(ImuOrientation::solve(
              ImuInstallationPlane::XZ, 1, meanAccel, orientation, rollDeviation),
          "declared-plane gravity orientation solves");
    check(rollDeviation > 1.0f && rollDeviation < ImuOrientation::kMaximumRollDeviationDeg,
          "small observed roll is measured inside the acceptance limit");
    check(fabsf(orientation[1][0]) < 1e-6f &&
              fabsf(orientation[1][1] - 1.0f) < 1e-6f &&
              fabsf(orientation[1][2]) < 1e-6f &&
              fabsf(orientation[2][1]) < 1e-6f,
          "declared normal and projected gravity are exact in saved transform");
    check(ImuOrientation::validateMatrix(orientation),
          "solved orientation is a right-handed rotation matrix");

    float quaternion[4] {};
    float roundTrip[3][3] {};
    ImuOrientation::matrixToQuaternion(orientation, quaternion);
    check(ImuOrientation::quaternionToMatrix(quaternion, roundTrip),
          "orientation quaternion round trip remains valid");
    bool sameOrientation = true;
    for (uint8_t row = 0; row < 3; ++row) {
      for (uint8_t column = 0; column < 3; ++column) {
        if (fabsf(orientation[row][column] - roundTrip[row][column]) > 0.0001f) {
          sameOrientation = false;
        }
      }
    }
    check(sameOrientation, "orientation quaternion round trip preserves matrix");

    const float excessiveRollAccel[] = {0.0f, 110.0f, 2045.0f};
    check(ImuOrientation::solve(
              ImuInstallationPlane::XZ, 1, excessiveRollAccel,
              orientation, rollDeviation) &&
              rollDeviation > ImuOrientation::kMaximumRollDeviationDeg,
          "roll beyond two degrees remains detectable after plane projection");

    uint64_t hostUs = 0;
    check(BMI270ImuTiming::estimateHostSampleTimeUs(256, 128, 100000, hostUs) &&
              hostUs == 95000,
          "one 200 Hz interval projects to 5000 us");
    check(BMI270ImuTiming::estimateHostSampleTimeUs(64, 0xFFFFC0u, 100000, hostUs) &&
              hostUs == 95000,
          "native-time wrap projects continuously");
    check(!BMI270ImuTiming::estimateHostSampleTimeUs(256, 128, 0, hostUs),
          "missing acquisition anchor rejects age estimate");

    float sparse[BMI270SparseRow::kColumnCount];
    uint32_t ageUs = 99;
    bool ageValid = true;
    BMI270SparseRow::encode(nullptr, 50000, sparse, ageUs, ageValid);
    bool invalidZeros = true;
    for (uint8_t i = 0; i < BMI270SparseRow::kColumnCount; ++i) {
      if (i != 9 && sparse[i] != 0.0f) invalidZeros = false;
    }
    check(invalidZeros && isnan(sparse[9]) && !ageValid,
          "invalid sparse row uses zero placeholders and NaN age");

    BMI270ImuSample sample;
    sample.accelX = -32768;
    sample.accelY = 32767;
    sample.gyroZ = -1;
    sample.sensorTime = 0x01FFFFFEu;
    sample.sequence = 0x02FFFFFFu;
    sample.temperatureRaw = -512;
    const uint16_t publicBoundaryStatus =
        BMI270ImuStatus::kFifoDiscontinuityBefore |
        BMI270ImuStatus::kSensorRecoveryBefore |
        BMI270ImuStatus::kTimingDegraded;
    sample.statusFlags = BMI270ImuStatus::kSensorTimeEstimated |
                         BMI270ImuStatus::markPreSessionBoundary(publicBoundaryStatus);
    sample.acquisitionAnchorUs = 45000;
    check(sample.measurementStatusFlags() == BMI270ImuStatus::kSensorTimeEstimated,
          "stationary measurements exclude only declared pre-session boundary status");
    BMI270SparseRow::encode(&sample, 50000, sparse, ageUs, ageValid);
    check(sparse[0] == -32768.0f && sparse[1] == 32767.0f && sparse[5] == -1.0f,
          "valid sparse row preserves signed native counts");
    check(sparse[6] == 16777214.0f && sparse[7] == 16777215.0f,
          "valid sparse row emits exact low 24-bit counters");
    check(sparse[8] == -512.0f && sparse[9] == 5000.0f && sparse[11] == 1.0f && ageValid,
          "valid sparse row emits temperature, age, and validity");
    check(sparse[10] == static_cast<float>(BMI270ImuStatus::kSensorTimeEstimated |
                                           publicBoundaryStatus),
          "logged stream preserves pre-session recovery boundary status");

    printf("BMI270 profile: %d passed, %d failed\n", passed, failed);
    return failed;
}
