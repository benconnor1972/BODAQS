#pragma once

// ─────────────────────────────────────────────────────────────────
// Host-test stub for FirmwareInfo.h
//
// The real FirmwareInfo.h defines inline functions that return
// compile-time macros (BODAQS_FW_VERSION).  This stub declares them
// as regular functions so mocks.cpp can return a configurable value
// at runtime (needed for T13: version changes with firmware).
// ─────────────────────────────────────────────────────────────────

namespace FirmwareInfo {
  const char* name();
  const char* version();
  const char* buildDateTime();
  const char* boardName();
}
