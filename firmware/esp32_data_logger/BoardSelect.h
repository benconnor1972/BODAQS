#pragma once
#include "BoardProfile.h"

namespace board {

// Exposed globally, read-only
extern const BoardProfile* gBoard;

// Call once at boot
void SelectBoard(BoardID id);

} // namespace board
