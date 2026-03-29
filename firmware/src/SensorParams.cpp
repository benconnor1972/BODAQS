// SensorParams.cpp
#include "SensorParams.h"
#include <strings.h>   // strcasecmp
#include <cstring>     // strncpy, strlen
#include <cstdlib>     // strtol, strtod

// Internal store layout expected by ParamPack::impl_.
// ConfigManager should populate one of these and assign it to ParamPack::impl_.
namespace {
  struct KV { const char* key; const char* val; };

  static const ParamStore* asStore(const void* p) {
    return reinterpret_cast<const ParamStore*>(p);
  }

  static bool findKV(const ParamStore* st, const char* key, const char*& outVal) {
    if (!st || !key || !*key) return false;
    for (uint8_t i = 0; i < st->count; ++i) {
      const char* k = st->keys[i];
      if (k && strcasecmp(k, key) == 0) {
        outVal = st->vals[i];
        return true;
      }
    }
    return false;
  }

  static bool parseBoolStr(const char* s, bool& out) {
    if (!s) return false;
    // trim leading spaces
    while (*s == ' ' || *s == '\t') ++s;
    if (!*s) return false;
    // lower-case compare without allocating
    if (!strcasecmp(s, "1") || !strcasecmp(s, "true") || !strcasecmp(s, "yes") || !strcasecmp(s, "on"))  { out = true;  return true; }
    if (!strcasecmp(s, "0") || !strcasecmp(s, "false")|| !strcasecmp(s, "no")  || !strcasecmp(s, "off")) { out = false; return true; }
    return false;
  }
} // namespace

uint16_t ParamPack::size() const {
  const ParamStore* st = asStore(impl_);
  return st ? st->count : 0;
}

bool ParamPack::get(const char* key, String& out) const {
  const ParamStore* st = asStore(impl_);
  const char* v = nullptr;
  if (!findKV(st, key, v)) return false;
  out = v ? v : "";
  return true;
}

bool ParamPack::get(const char* key, char* out, size_t cap) const {
  if (!out || cap == 0) return false;
  out[0] = '\0';
  const ParamStore* st = asStore(impl_);
  const char* v = nullptr;
  if (!findKV(st, key, v)) return false;
  if (!v) { out[0] = '\0'; return true; }
  size_t n = strlen(v);
  if (n >= cap) n = cap - 1;
  strncpy(out, v, n);
  out[n] = '\0';
  return true;
}

bool ParamPack::getBool(const char* key, bool& out) const {
  const ParamStore* st = asStore(impl_);
  const char* v = nullptr;
  if (!findKV(st, key, v)) return false;
  return parseBoolStr(v, out);
}

bool ParamPack::getInt(const char* key, long& out) const {
  const ParamStore* st = asStore(impl_);
  const char* v = nullptr;
  if (!findKV(st, key, v)) return false;
  char* end = nullptr;
  long val = strtol(v, &end, 10);
  if (end == v) return false;          // no digits
  while (end && (*end == ' ' || *end == '\t')) ++end; // allow trailing space
  if (end && *end != '\0') return false; // junk after number
  out = val;
  return true;
}

bool ParamPack::getFloat(const char* key, double& out) const {
  const ParamStore* st = asStore(impl_);
  const char* v = nullptr;
  if (!findKV(st, key, v)) return false;
  char* end = nullptr;
  double val = strtod(v, &end);
  if (end == v) return false;          // no digits
  while (end && (*end == ' ' || *end == '\t')) ++end;
  if (end && *end != '\0') return false;
  out = val;
  return true;
}

bool ParamPack::set(const char* key, const String& value) {
  // cast the bound opaque pointer back to ParamStore (non-const so we can write)
  ParamStore* st = const_cast<ParamStore*>(reinterpret_cast<const ParamStore*>(impl_));
  if (!st || !key || !*key) return false;

  // update if exists
  for (uint8_t i = 0; i < st->count; ++i) {
    if (strcasecmp(st->keys[i], key) == 0) {
      // write value with truncation + NUL
      strncpy(st->vals[i], value.c_str(), sizeof(st->vals[i]) - 1);
      st->vals[i][sizeof(st->vals[i]) - 1] = '\0';
      return true;
    }
  }

  // append if space
  if (st->count < ParamStore::MAX) {
    // key
    strncpy(st->keys[st->count], key, sizeof(st->keys[st->count]) - 1);
    st->keys[st->count][sizeof(st->keys[st->count]) - 1] = '\0';
    // value
    strncpy(st->vals[st->count], value.c_str(), sizeof(st->vals[st->count]) - 1);
    st->vals[st->count][sizeof(st->vals[st->count]) - 1] = '\0';

    ++st->count;
    return true;
  }
  return false; // no space
}

bool ParamPack::setInt(const char* key, long v) {
  return set(key, String(v));
}

bool ParamPack::setFloat(const char* key, double v) {
  // choose precision you prefer
  return set(key, String(v, 6));
}

bool ParamPack::setBool(const char* key, bool b) {
  return set(key, b ? String("true") : String("false"));
}

bool ParamPack::clear() {
  ParamStore* st = const_cast<ParamStore*>(reinterpret_cast<const ParamStore*>(impl_));
  if (!st) return false;
  st->clear();
  return true;
}

