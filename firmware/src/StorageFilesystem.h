#pragma once
#include "StorageOwnership.h"
#include "SD_MMC.h"

namespace StorageFilesystem {
inline StorageOwnership& ownership() {
  static StorageOwnership value;
  return value;
}

#if defined(ARDUINO_ARCH_ESP32) && BODAQS_A8_USB_DRIVE
// All logger filesystem users go through this card. File handles retain a local
// access lease, so external ownership cannot be granted with an open local file.
class Card : public fs::SDMMCFS {
public:
  Card();
  bool begin(const char* mountpoint = "/sdcard", bool oneBit = false,
             bool format = false, int frequency = BOARD_MAX_SDMMC_FREQ, uint8_t maxFiles = 5);
  void end();
  sdcard_type_t cardType();
  uint64_t cardSize();
  uint64_t totalBytes();
  uint64_t usedBytes();
  // service/reclaim run on the main loop, not USB callbacks. External ownership
  // is published only after the local filesystem has actually been unmounted.
  void service();
  bool reclaim();
private:
  String mountpoint_ = "/sdcard";
  bool oneBit_ = false;
  int frequency_ = BOARD_MAX_SDMMC_FREQ;
  uint8_t maxFiles_ = 5;
};
Card& card();
#else
// Existing host fixtures supply the filesystem stand-in. The portable ownership
// boundary is tested separately; physical FS behavior needs the A8 test build.
inline auto& card() { return SD_MMC; }
#endif
} // namespace StorageFilesystem
