#include "BoardSelect.h"

namespace board {

const BoardProfile* gBoard = nullptr;

void SelectBoard(BoardID id) {
  gBoard = &GetBoardProfile(id);
}

} // namespace board
