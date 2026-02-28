#include "BoardSelect.h"
#include <ctype.h> 
#include <Arduino.h>

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
      Serial.println("[Board] gBoard=null");
      return;
    }

    const auto& bp = *gBoard;
    Serial.print("[Board] Active profile: ");
    Serial.println(bp.name ? bp.name : "(null)");

    Serial.println("[Board] Buttons:");
    for (uint8_t i = 0; i < bp.buttons.count; ++i) {
      const auto& b = bp.buttons.btn[i];
      if (!b.present) continue;

      Serial.printf("  %u %-12s pin=%d mode=%s active_low=%u pullup=%u\n",
                    (unsigned)i,
                    b.id,
                    (int)b.pin,
                    (b.mode == 1) ? "poll" : "interrupt",
                    (unsigned)b.active_low,
                    (unsigned)b.use_internal_pullup);
    }
  }

} // namespace board
