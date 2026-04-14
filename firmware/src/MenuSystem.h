#pragma once
#include <Arduino.h>
#include "ButtonManager.h"  // for ButtonEvent

struct LoggerConfig;
namespace ButtonActions { enum ActionId : uint8_t; }
//class Menu;

namespace MenuSystem {

  enum class State : uint8_t { Inactive, Main, SensorsList, RatePicker, CalibSensors, CalibDetail };
  enum class Dir   : uint8_t { Left, Right, Up, Down, Enter };

  void begin(const LoggerConfig* cfg);
  void setIdleCloseMs(uint32_t ms);
  bool isActive();
  void requestOpen();
  void requestClose();
  void requestSleep();
  void loop();

  // High-level nav helpers (used by ButtonActions)
  void navUp();
  void navDown();
  void navLeft();
  void navRight();
  void select();

  // Generic nav hook (optional—kept if you’re already using it)
  void onNav(Dir d, ButtonEvent ev);
  bool handleAction(ButtonActions::ActionId action, ButtonEvent ev);
  void onMark();  // handle MARK button while menu is open

}
