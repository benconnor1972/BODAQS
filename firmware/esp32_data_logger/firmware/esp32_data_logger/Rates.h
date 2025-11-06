// Rates.h (new)  — keep tiny and focused
#pragma once
#include <stdint.h>

namespace Rates {
  static constexpr uint16_t kList[] = {10, 20, 50, 100, 200, 500, 1000};
  static constexpr size_t   kCount  = sizeof(kList)/sizeof(kList[0]);

  inline int indexOf(uint16_t hz) {
    for (size_t i = 0; i < kCount; ++i) if (kList[i] == hz) return (int)i;
    return -1;
  }
}
