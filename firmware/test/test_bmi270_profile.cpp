#include <cstdio>

#include "BMI270Profile.h"
#include "BMI270Mount.h"
#include "BMI270ImuTiming.h"
#include "BMI270SparseRow.h"

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
    check(BMI270Profile::kInitializationAttempts == 3, "initialization retry count remains bounded");

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
    sample.statusFlags = BMI270ImuStatus::kSensorTimeEstimated;
    sample.acquisitionAnchorUs = 45000;
    BMI270SparseRow::encode(&sample, 50000, sparse, ageUs, ageValid);
    check(sparse[0] == -32768.0f && sparse[1] == 32767.0f && sparse[5] == -1.0f,
          "valid sparse row preserves signed native counts");
    check(sparse[6] == 16777214.0f && sparse[7] == 16777215.0f,
          "valid sparse row emits exact low 24-bit counters");
    check(sparse[8] == -512.0f && sparse[9] == 5000.0f && sparse[11] == 1.0f && ageValid,
          "valid sparse row emits temperature, age, and validity");

    printf("BMI270 profile: %d passed, %d failed\n", passed, failed);
    return failed;
}
