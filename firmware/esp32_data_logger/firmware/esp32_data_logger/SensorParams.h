#ifndef SENSOR_PARAMS_H
#define SENSOR_PARAMS_H

#include <stdint.h>
#include <stddef.h>
#include <string>
#include <Arduino.h>

struct ParamStore {
  static const uint8_t MAX = 16;   // max params per sensor
  char     keys[MAX][24];
  char     vals[MAX][32];
  uint8_t  count = 0;

  void     clear()      { count = 0; }
  uint8_t  size() const { return count; }

  // Convenience helpers so ConfigManager can fill it
  void set(const char* key, const char* val) {
    if (!key || !*key || !val) return;
    for (uint8_t i = 0; i < count; ++i) {
      if (strcasecmp(keys[i], key) == 0) {
        strncpy(vals[i], val, sizeof(vals[i]) - 1);
        vals[i][sizeof(vals[i]) - 1] = '\0';
        return;
      }
    }
    if (count < MAX) {
      strncpy(keys[count], key, sizeof(keys[count]) - 1);
      keys[count][sizeof(keys[count]) - 1] = '\0';
      strncpy(vals[count], val, sizeof(vals[count]) - 1);
      vals[count][sizeof(vals[count]) - 1] = '\0';
      ++count;
    }
  }

  const char* get(const char* key) const {
    if (!key) return nullptr;
    for (uint8_t i = 0; i < count; ++i)
      if (strcasecmp(keys[i], key) == 0) return vals[i];
    return nullptr;
  }
};

// Small schema for per-sensor parameters
enum class ParamType : uint8_t { Bool, Int, Float, String, Enum };

// A single parameter description.
// All numbers are text so we don't pull in std lib parsing here.
struct ParamDef {
  const char* key;      // "pin", "invert", "mode", ...
  ParamType   type;
  const char* def;      // default value as text (e.g. "36", "false", "norm")
  const char* minv;     // optional min  (nullptr if N/A)
  const char* maxv;     // optional max  (nullptr if N/A)
  const char* choices;  // optional CSV for enums ("raw,norm,mm")
  const char* help;     // short help text
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

  void bind(const void* impl) { impl_ = impl; }


  // For debugging / UI
  uint16_t size() const;   // number of key/value pairs

private:
  const void* impl_;       // opaque pointer to ConfigManager-owned storage
  explicit ParamPack(const void* impl) : impl_(impl) {}

  friend class ConfigManager;   // ConfigManager constructs valid ParamPack
};

#endif // SENSOR_PARAMS_H
