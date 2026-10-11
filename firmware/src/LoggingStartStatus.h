#pragma once
#include <stdint.h>

enum class LoggingConfigIssue : uint8_t {
  None, Conflict, RestartRequired, InvalidConfig
};
