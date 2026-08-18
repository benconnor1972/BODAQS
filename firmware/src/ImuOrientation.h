#pragma once

#include <math.h>
#include <stddef.h>
#include <stdint.h>

enum class ImuInstallationPlane : uint8_t {
  XY = 0,
  YZ = 1,
  XZ = 2,
};

namespace ImuOrientationRejection {

inline constexpr uint16_t kInsufficientSamples = 0x0001;
inline constexpr uint16_t kQualityIncident = 0x0002;
inline constexpr uint16_t kAccelMeanOutsideGravityBand = 0x0004;
inline constexpr uint16_t kAccelMagnitudeUnstable = 0x0008;
inline constexpr uint16_t kGyroUnstable = 0x0010;
inline constexpr uint16_t kGyroMotionDetected = 0x0020;
inline constexpr uint16_t kRollOutsideLimit = 0x0040;
inline constexpr uint16_t kInvalidGeometry = 0x0080;

} // namespace ImuOrientationRejection

struct ImuOrientationCalibration {
  bool accepted = false;
  ImuInstallationPlane plane = ImuInstallationPlane::XZ;
  // +1 means the plane's positive sensor-native normal points toward bike
  // +Y (left); -1 means its negative normal points left.
  int8_t normalSign = 1;
  uint16_t rejectionMask = 0;
  uint16_t qualityStatusMask = 0;
  uint16_t settlingStatusMask = 0;
  uint32_t sampleCount = 0;
  uint32_t settlingSampleCount = 0;
  uint64_t capturedAtUnixMs = 0;
  float matrix[3][3] {};
  float quaternionWxyz[4] {1.0f, 0.0f, 0.0f, 0.0f};
  float meanAccelRaw[3] {};
  float accelMagnitudeMeanG = 0.0f;
  float accelMagnitudeStdG = 0.0f;
  float gyroStdMaximumDps = 0.0f;
  float maximumGyroMagnitudeDps = 0.0f;
  float rollDeviationDeg = 0.0f;
};

namespace ImuOrientation {

inline constexpr float kMaximumRollDeviationDeg = 2.0f;

inline const char* planeKey(ImuInstallationPlane plane) {
  switch (plane) {
    case ImuInstallationPlane::XY: return "xy";
    case ImuInstallationPlane::YZ: return "yz";
    case ImuInstallationPlane::XZ:
    default: return "xz";
  }
}

inline bool parsePlane(const char* text, ImuInstallationPlane& out) {
  if (!text) return false;
  if ((text[0] == 'x' || text[0] == 'X') &&
      (text[1] == 'y' || text[1] == 'Y') && text[2] == '\0') {
    out = ImuInstallationPlane::XY;
    return true;
  }
  if ((text[0] == 'y' || text[0] == 'Y') &&
      (text[1] == 'z' || text[1] == 'Z') && text[2] == '\0') {
    out = ImuInstallationPlane::YZ;
    return true;
  }
  if ((text[0] == 'x' || text[0] == 'X') &&
      (text[1] == 'z' || text[1] == 'Z') && text[2] == '\0') {
    out = ImuInstallationPlane::XZ;
    return true;
  }
  return false;
}

inline uint8_t normalAxis(ImuInstallationPlane plane) {
  switch (plane) {
    case ImuInstallationPlane::XY: return 2;
    case ImuInstallationPlane::YZ: return 0;
    case ImuInstallationPlane::XZ:
    default: return 1;
  }
}

inline float determinant(const float matrix[3][3]) {
  return
      matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1]) -
      matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0]) +
      matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0]);
}

inline bool validateMatrix(const float matrix[3][3], float tolerance = 0.002f) {
  for (uint8_t row = 0; row < 3; ++row) {
    float norm = 0.0f;
    for (uint8_t column = 0; column < 3; ++column) {
      if (!isfinite(matrix[row][column])) return false;
      norm += matrix[row][column] * matrix[row][column];
    }
    if (fabsf(norm - 1.0f) > tolerance) return false;
    for (uint8_t other = 0; other < row; ++other) {
      float dot = 0.0f;
      for (uint8_t column = 0; column < 3; ++column) {
        dot += matrix[row][column] * matrix[other][column];
      }
      if (fabsf(dot) > tolerance) return false;
    }
  }
  return fabsf(determinant(matrix) - 1.0f) <= tolerance * 2.0f;
}

inline void matrixToQuaternion(const float matrix[3][3], float out[4]) {
  const float trace = matrix[0][0] + matrix[1][1] + matrix[2][2];
  if (trace > 0.0f) {
    const float s = sqrtf(trace + 1.0f) * 2.0f;
    out[0] = 0.25f * s;
    out[1] = (matrix[2][1] - matrix[1][2]) / s;
    out[2] = (matrix[0][2] - matrix[2][0]) / s;
    out[3] = (matrix[1][0] - matrix[0][1]) / s;
  } else if (matrix[0][0] > matrix[1][1] && matrix[0][0] > matrix[2][2]) {
    const float s = sqrtf(1.0f + matrix[0][0] - matrix[1][1] - matrix[2][2]) * 2.0f;
    out[0] = (matrix[2][1] - matrix[1][2]) / s;
    out[1] = 0.25f * s;
    out[2] = (matrix[0][1] + matrix[1][0]) / s;
    out[3] = (matrix[0][2] + matrix[2][0]) / s;
  } else if (matrix[1][1] > matrix[2][2]) {
    const float s = sqrtf(1.0f + matrix[1][1] - matrix[0][0] - matrix[2][2]) * 2.0f;
    out[0] = (matrix[0][2] - matrix[2][0]) / s;
    out[1] = (matrix[0][1] + matrix[1][0]) / s;
    out[2] = 0.25f * s;
    out[3] = (matrix[1][2] + matrix[2][1]) / s;
  } else {
    const float s = sqrtf(1.0f + matrix[2][2] - matrix[0][0] - matrix[1][1]) * 2.0f;
    out[0] = (matrix[1][0] - matrix[0][1]) / s;
    out[1] = (matrix[0][2] + matrix[2][0]) / s;
    out[2] = (matrix[1][2] + matrix[2][1]) / s;
    out[3] = 0.25f * s;
  }
  if (out[0] < 0.0f) {
    for (uint8_t i = 0; i < 4; ++i) out[i] = -out[i];
  }
}

inline bool quaternionToMatrix(const float quaternionWxyz[4], float out[3][3]) {
  float q[4] = {
      quaternionWxyz[0], quaternionWxyz[1], quaternionWxyz[2], quaternionWxyz[3]};
  float norm = 0.0f;
  for (float value : q) {
    if (!isfinite(value)) return false;
    norm += value * value;
  }
  if (norm <= 1e-8f) return false;
  const float inverse = 1.0f / sqrtf(norm);
  for (float& value : q) value *= inverse;
  const float w = q[0], x = q[1], y = q[2], z = q[3];
  out[0][0] = 1.0f - 2.0f * (y * y + z * z);
  out[0][1] = 2.0f * (x * y - z * w);
  out[0][2] = 2.0f * (x * z + y * w);
  out[1][0] = 2.0f * (x * y + z * w);
  out[1][1] = 1.0f - 2.0f * (x * x + z * z);
  out[1][2] = 2.0f * (y * z - x * w);
  out[2][0] = 2.0f * (x * z - y * w);
  out[2][1] = 2.0f * (y * z + x * w);
  out[2][2] = 1.0f - 2.0f * (x * x + y * y);
  return validateMatrix(out);
}

inline bool solve(
    ImuInstallationPlane plane,
    int8_t normalSign,
    const float meanAccelRaw[3],
    float matrix[3][3],
    float& rollDeviationDeg) {
  if (!meanAccelRaw || (normalSign != 1 && normalSign != -1)) return false;
  const float magnitude = sqrtf(
      meanAccelRaw[0] * meanAccelRaw[0] +
      meanAccelRaw[1] * meanAccelRaw[1] +
      meanAccelRaw[2] * meanAccelRaw[2]);
  if (!isfinite(magnitude) || magnitude <= 1e-6f) return false;

  float bodyY[3] {};
  bodyY[normalAxis(plane)] = static_cast<float>(normalSign);
  float gravityUnit[3] = {
      meanAccelRaw[0] / magnitude,
      meanAccelRaw[1] / magnitude,
      meanAccelRaw[2] / magnitude,
  };
  float lateral = 0.0f;
  for (uint8_t axis = 0; axis < 3; ++axis) lateral += gravityUnit[axis] * bodyY[axis];
  const float bounded = fminf(1.0f, fabsf(lateral));
  rollDeviationDeg = asinf(bounded) * 180.0f / 3.14159265358979323846f;

  // Force the true gravity vector into the user-declared installation plane.
  // This removes accepted small roll error from the saved transform.
  float bodyZ[3];
  float projectedNorm = 0.0f;
  for (uint8_t axis = 0; axis < 3; ++axis) {
    bodyZ[axis] = gravityUnit[axis] - lateral * bodyY[axis];
    projectedNorm += bodyZ[axis] * bodyZ[axis];
  }
  if (projectedNorm <= 1e-8f) return false;
  const float inverseProjectedNorm = 1.0f / sqrtf(projectedNorm);
  for (float& value : bodyZ) value *= inverseProjectedNorm;

  const float bodyX[3] = {
      bodyY[1] * bodyZ[2] - bodyY[2] * bodyZ[1],
      bodyY[2] * bodyZ[0] - bodyY[0] * bodyZ[2],
      bodyY[0] * bodyZ[1] - bodyY[1] * bodyZ[0],
  };
  for (uint8_t axis = 0; axis < 3; ++axis) {
    matrix[0][axis] = bodyX[axis];
    matrix[1][axis] = bodyY[axis];
    matrix[2][axis] = bodyZ[axis];
  }
  return validateMatrix(matrix);
}

} // namespace ImuOrientation
