#pragma once

#include "BoardSelect.h"

#ifndef BODAQS_FW_VERSION
#define BODAQS_FW_VERSION "0.0.0-dev"
#endif

#ifndef BODAQS_FW_NAME
#define BODAQS_FW_NAME "BODAQS"
#endif

namespace FirmwareInfo {

inline const char* name() {
  return BODAQS_FW_NAME;
}

inline const char* version() {
  return BODAQS_FW_VERSION;
}

inline const char* buildDateTime() {
  return __DATE__ " " __TIME__;
}

inline const char* boardName() {
  return (board::gBoard && board::gBoard->name) ? board::gBoard->name : "Unknown board";
}

} // namespace FirmwareInfo
