#pragma once

#ifndef BODAQS_I2C_TRANSFER_PRIORITY
#define BODAQS_I2C_TRANSFER_PRIORITY 0
#endif

namespace I2CTransferPriority {

// The scope ends before FIFO parsing, sensor diagnostics processing, or the
// scheduler's next wait. Nested scopes must not lower an existing priority.
template <typename Tasks>
class Scope {
public:
  explicit Scope(unsigned targetPriority = BODAQS_I2C_TRANSFER_PRIORITY) {
    if (targetPriority == 0 || !Tasks::eligible()) return;
    previousPriority_ = Tasks::priority();
    if (previousPriority_ >= targetPriority) return;
    Tasks::setPriority(targetPriority);
    changed_ = true;
  }

  ~Scope() {
    if (changed_) Tasks::setPriority(previousPriority_);
  }

  Scope(const Scope&) = delete;
  Scope& operator=(const Scope&) = delete;

private:
  unsigned previousPriority_ = 0;
  bool changed_ = false;
};

} // namespace I2CTransferPriority

#if defined(ESP32) && BODAQS_I2C_TRANSFER_PRIORITY > 0
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "I2CBusScheduler.h"

namespace I2CTransferPriority {
struct RuntimeTasks {
  static bool eligible() { return I2CBusScheduler::isCurrentTask(); }
  static unsigned priority() { return uxTaskPriorityGet(nullptr); }
  static void setPriority(unsigned value) { vTaskPrioritySet(nullptr, value); }
};
} // namespace I2CTransferPriority
#else
namespace I2CTransferPriority {
struct RuntimeTasks {
  static bool eligible() { return false; }
  static unsigned priority() { return 0; }
  static void setPriority(unsigned) {}
};
} // namespace I2CTransferPriority
#endif

using I2CTransferPriorityScope =
    I2CTransferPriority::Scope<I2CTransferPriority::RuntimeTasks>;
