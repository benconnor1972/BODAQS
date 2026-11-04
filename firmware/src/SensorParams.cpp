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
      const char* k = st->keyAt(i);
      if (k && strcasecmp(k, key) == 0) {
        outVal = st->valueAt(i);
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

void ParamStore::clear() {
  count = 0;
  used = 0;
  text[0] = '\0';
}

const char* ParamStore::keyAt(uint8_t index) const {
  return index < count && slots[index].keyOffset < used
      ? text + slots[index].keyOffset : nullptr;
}

const char* ParamStore::valueAt(uint8_t index) const {
  return index < count && slots[index].valueOffset < used
      ? text + slots[index].valueOffset : nullptr;
}

const char* ParamStore::get(const char* key) const {
  if (!key || !*key) return nullptr;
  for (uint8_t i = 0; i < count; ++i) {
    const char* candidate = keyAt(i);
    if (candidate && strcasecmp(candidate, key) == 0) return valueAt(i);
  }
  return nullptr;
}

bool ParamStore::append_(const char* key, const char* value) {
  if (!key || !*key || !value || count >= MAX) return false;

  const size_t keyLength = strnlen(key, MAX_KEY_CHARS);
  const size_t valueLength = strnlen(value, MAX_VALUE_CHARS);
  const size_t required = keyLength + 1 + valueLength + 1;
  if (required > size_t(TEXT_CAPACITY - used)) return false;

  Slot& slot = slots[count];
  slot.keyOffset = used;
  memcpy(text + used, key, keyLength);
  used += (uint16_t)keyLength;
  text[used++] = '\0';

  slot.valueOffset = used;
  memcpy(text + used, value, valueLength);
  used += (uint16_t)valueLength;
  text[used++] = '\0';
  ++count;
  return true;
}

bool ParamStore::set(const char* key, const char* value) {
  if (!key || !*key || !value) return false;

  int replacementIndex = -1;
  for (uint8_t i = 0; i < count; ++i) {
    const char* candidate = keyAt(i);
    if (candidate && strcasecmp(candidate, key) == 0) {
      replacementIndex = i;
      break;
    }
  }

  ParamStore rebuilt;
  for (uint8_t i = 0; i < count; ++i) {
    const char* existingKey = keyAt(i);
    const char* existingValue = valueAt(i);
    if (!rebuilt.append_(existingKey, i == replacementIndex ? value : existingValue)) {
      return false;
    }
  }
  if (replacementIndex < 0 && !rebuilt.append_(key, value)) return false;
  *this = rebuilt;
  return true;
}

bool ParamStore::remove(const char* key) {
  if (!key || !*key) return false;
  bool removed = false;
  ParamStore rebuilt;
  for (uint8_t i = 0; i < count; ++i) {
    const char* existingKey = keyAt(i);
    if (!removed && existingKey && strcasecmp(existingKey, key) == 0) {
      removed = true;
      continue;
    }
    if (!rebuilt.append_(existingKey, valueAt(i))) return false;
  }
  if (removed) *this = rebuilt;
  return removed;
}

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

  return st->set(key, value.c_str());
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

