#pragma once

#include <stddef.h>
#include <stdint.h>

struct BMI270MountAxis {
  uint8_t sensorAxis = 0; // 0=x, 1=y, 2=z
  int8_t sign = 1;
};

struct BMI270MountTransform {
  BMI270MountAxis body[3] {};
};

namespace BMI270Mount {

inline bool parseAxis(const char* text, BMI270MountAxis& out) {
  if (!text) return false;
  const char sign = text[0];
  const char axis = text[1];
  if ((sign != '+' && sign != '-') || text[2] != '\0') return false;
  if (axis != 'x' && axis != 'y' && axis != 'z') return false;
  out.sensorAxis = static_cast<uint8_t>(axis - 'x');
  out.sign = (sign == '+') ? 1 : -1;
  return true;
}

inline int determinant(const BMI270MountTransform& transform) {
  int matrix[3][3] = {};
  for (uint8_t bodyAxis = 0; bodyAxis < 3; ++bodyAxis) {
    const BMI270MountAxis& axis = transform.body[bodyAxis];
    if (axis.sensorAxis >= 3 || (axis.sign != 1 && axis.sign != -1)) return 0;
    matrix[bodyAxis][axis.sensorAxis] = axis.sign;
  }
  return
      matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1]) -
      matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0]) +
      matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0]);
}

inline bool parseTransform(
    const char* mountX,
    const char* mountY,
    const char* mountZ,
    BMI270MountTransform& out) {
  BMI270MountTransform parsed;
  if (!parseAxis(mountX, parsed.body[0]) ||
      !parseAxis(mountY, parsed.body[1]) ||
      !parseAxis(mountZ, parsed.body[2])) {
    return false;
  }

  uint8_t used = 0;
  for (const BMI270MountAxis& axis : parsed.body) {
    const uint8_t bit = static_cast<uint8_t>(1u << axis.sensorAxis);
    if ((used & bit) != 0) return false;
    used = static_cast<uint8_t>(used | bit);
  }
  if (used != 0x07 || determinant(parsed) != 1) return false;
  out = parsed;
  return true;
}

} // namespace BMI270Mount
