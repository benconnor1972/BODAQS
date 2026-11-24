#pragma once
#include <stdint.h>

namespace UsbDriveManager {
bool enabled();
void begin();
void loop();
bool active();
bool enter(bool logging);
void requestExit();
bool cancelExit();
void retry();
bool exitPending();
uint8_t phase();
const char* stateKey();
const char* label();
const char* shortLabel();
#if defined(BODAQS_USB_DIAGNOSTICS)
const char* diagnosticLine(uint8_t row);
#endif
}
