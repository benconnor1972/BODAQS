#pragma once

// Consume only a complete gesture which began while the home prompt existed.
// The release of a log-start/menu gesture cannot acknowledge a new prompt.
class HomeRestartGesture {
public:
  bool update(bool prompt, bool pressed, bool released) {
    if (!prompt) { armed_ = false; return false; }
    if (pressed) armed_ = true;
    if (!released) return false;
    const bool restart = armed_;
    armed_ = false;
    return restart;
  }
private:
  bool armed_ = false;
};
