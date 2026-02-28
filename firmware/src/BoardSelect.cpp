#include "BoardSelect.h"
#include <ctype.h> 
#include <Arduino.h>
#include "DebugLog.h"

namespace board {

  const BoardProfile* gBoard = nullptr;

  void SelectBoard(BoardID id) {
    gBoard = &GetBoardProfile(id);
  }

  static bool equalsIgnoreCase_(const char* a, const char* b) {
    if (a == b) return true;
    if (!a || !b) return false;
    while (*a && *b) {
      char ca = (char)tolower((unsigned char)*a++);
      char cb = (char)tolower((unsigned char)*b++);
      if (ca != cb) return false;
    }
    return (*a == '\0' && *b == '\0');
  }

  int FindButtonIndexById(const char* id) {
    if (!id || !*id) return -1;
    if (!gBoard) return -1;

    const auto& bp = *gBoard;

    // Use the board’s declared count; btn[] itself is fixed-size (6 in your profile)
    const uint8_t n = bp.buttons.count;

    for (uint8_t i = 0; i < n; ++i) {
      const auto& b = bp.buttons.btn[i];
      if (!b.present) continue;
      if (equalsIgnoreCase_(b.id, id)) return (int)i;
    }
    return -1;
  }

  void DumpActiveBoardButtons() {
    if (!gBoard) {
      LOGW_TAG("Board", "gBoard=null\n");
      return;
    }

    const auto& bp = *gBoard;
    LOGI_TAG("Board", "Active profile: %s\n", bp.name ? bp.name : "(null)");

    LOGI_TAG("Board", "Buttons:\n");
    for (uint8_t i = 0; i < bp.buttons.count; ++i) {
      const auto& b = bp.buttons.btn[i];
      if (!b.present) continue;

      LOGI("  %u %-12s pin=%d mode=%s active_low=%u pullup=%u\n",
           (unsigned)i,
           b.id,
           (int)b.pin,
           (b.mode == 1) ? "poll" : "interrupt",
           (unsigned)b.active_low,
           (unsigned)b.use_internal_pullup);
    }
  }

} // namespace board
