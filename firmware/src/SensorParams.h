#ifndef SENSOR_PARAMS_H
#define SENSOR_PARAMS_H

#include <stdint.h>
#include <stddef.h>
#include <string>
#include <Arduino.h>

struct ParamStore {
  // Retain existing entries plus retired experiment keys and editor markers.
  // Text is packed into one arena instead of reserving maximum-length key and
  // value arrays for every slot. Offsets make ordinary copies self-contained,
  // which is important for staged configuration transactions.
  static const uint8_t MAX = 36;
  static const uint8_t MAX_KEY_CHARS = 23;
  static const uint8_t MAX_VALUE_CHARS = 31;
  static const uint16_t TEXT_CAPACITY = 1280;

  struct Slot {
    uint16_t keyOffset = 0;
    uint16_t valueOffset = 0;
  };

  Slot     slots[MAX];
  char     text[TEXT_CAPACITY] = {0};
  uint16_t used = 0;
  uint8_t  count = 0;

  void     clear();
  uint8_t  size() const { return count; }
  uint16_t textBytes() const { return used; }
  const char* keyAt(uint8_t index) const;
  const char* valueAt(uint8_t index) const;
  const char* get(const char* key) const;
  bool set(const char* key, const char* value);
  bool remove(const char* key);

private:
  bool append_(const char* key, const char* value);
};

static_assert(sizeof(ParamStore) <= 1440,
              "ParamStore must remain compact enough for 32 configured sensors");

// Small schema for per-sensor parameters
enum class ParamType : uint8_t { Bool, Int, Float, String, Enum };

// A single parameter description.
// All numbers are text so we don't pull in std lib parsing here.
struct ParamDef {
  const char* key;      // "pin", "mode", ...
  ParamType   type;
  const char* def;      // default value as text (e.g. "36", "false", "norm")
  const char* minv;     // optional min  (nullptr if N/A)
  const char* maxv;     // optional max  (nullptr if N/A)
  const char* choices;  // optional CSV for enums ("raw,norm,mm")
  const char* help;     // short help text
  bool hidden = false;  // persisted internal state; not rendered as an editable field
};

// Lightweight, read-only view of key/value params for one sensor instance.
// The actual storage lives in ConfigManager; this is just a handle.
class ParamPack {
public:
  ParamPack() : impl_(nullptr) {}

  // Generic lookups
  bool get(const char* key, String& out) const;
  bool get(const char* key, char*   out, size_t cap) const;

  // Typed convenience
  bool getBool (const char* key, bool&   out) const;
  bool getInt  (const char* key, long&   out) const;
  bool getFloat(const char* key, double& out) const;
  bool set(const char* key, const String& value);
  bool setInt(const char* key, long v);
  bool setFloat(const char* key, double v);
  bool setBool(const char* key, bool v);
  bool clear();

  void bind(const void* impl) { impl_ = impl; }


  // For debugging / UI
  uint16_t size() const;   // number of key/value pairs

private:
  const void* impl_;       // opaque pointer to ConfigManager-owned storage
  explicit ParamPack(const void* impl) : impl_(impl) {}

  friend class ConfigManager;   // ConfigManager constructs valid ParamPack
};

#endif // SENSOR_PARAMS_H
