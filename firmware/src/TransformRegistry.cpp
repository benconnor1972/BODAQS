#include "TransformRegistry.h"
#include <ArduinoJson.h>
#include <FS.h>        // fs::FS
#include <SdFat.h>     // SdFat/SdFs
#include <algorithm>

// ---------- utils ----------
static bool endsWith(const String& s, const char* suffix) {
  int n = s.length(), m = (int)strlen(suffix);
  return n >= m && s.substring(n - m) == suffix;
}

static inline void sanitizeId(String& s) {
  s.trim();
  while (s.length()) {
    char c = s[s.length() - 1];
    if (c == ',' || c == ';' || c <= ' ') s.remove(s.length() - 1);
    else break;
  }
}

String TransformRegistry::calDirFor(const String& sensorId) const {
  return String("/cal/") + sensorId + "/";
}

// ---------- public APIs (FS + SdFs) ----------
bool TransformRegistry::loadForSensor(const String& sensorId, SdFs& sd) {
  Serial.println("[XFORM_FAT] HIT loadForSensor(SdFs)");

  sensors_.erase(sensorId);
  const String dir = calDirFor(sensorId);

  Serial.printf("[XFORM_FAT] sensor='%s' dir='%s'\n", sensorId.c_str(), dir.c_str());

  if (!sd.exists(dir.c_str())) {
    Serial.printf("[XFORM_FAT] dir missing: %s\n", dir.c_str());
    return true;
  }

  FsFile d;
  if (!d.open(dir.c_str(), O_RDONLY)) {
    Serial.printf("[XFORM_FAT] dir open FAIL: %s\n", dir.c_str());
    return false;
  }
  if (!d.isDir()) {
    Serial.printf("[XFORM_FAT] not a dir: %s\n", dir.c_str());
    d.close();
    return false;
  }

  FsFile entry;
  while (entry.openNext(&d, O_RDONLY)) {
    char name[96] = {0};
    entry.getName(name, sizeof(name));
    const bool isDir = entry.isDir();
    entry.close();

    String full = dir + name;

    Serial.printf("[XFORM_FAT] entry: %s%s\n", full.c_str(), isDir ? "/" : "");

    if (isDir) continue;

    if (endsWith(full, ".poly.json")) {
      Serial.printf("[XFORM_FAT] load poly json: %s\n", full.c_str());
      loadPoly_sd(sensorId, full, sd);

    } else if (endsWith(full, ".poly.cfg") ||
               endsWith(full, ".poly.txt") ||
               endsWith(full, ".poly")) {
      Serial.printf("[XFORM_FAT] load poly cfg: %s\n", full.c_str());
      loadPoly_cfg_sd(sensorId, full, sd);

    } else if (endsWith(full, ".lut.csv")) {
      Serial.printf("[XFORM_FAT] load lut csv: %s\n", full.c_str());
      loadLUT_sd(sensorId, full, sd);

    } else {
      Serial.printf("[XFORM_FAT] skip (suffix): %s\n", full.c_str());
    }
  }

  d.close();
  return true;
}


bool TransformRegistry::loadForSensor(const String& sensorId, fs::FS& fs) {
  Serial.println("[XFORM_FS] HIT loadForSensor(fs::FS)");

  sensors_.erase(sensorId);
  const String dir = calDirFor(sensorId);

  Serial.printf("[XFORM_FS] sensor='%s' dir='%s'\n", sensorId.c_str(), dir.c_str());

  if (!fs.exists(dir)) {
    Serial.printf("[XFORM_FS] dir missing: %s\n", dir.c_str());
    return true;
  }

  File d = fs.open(dir, FILE_READ);
  if (!d) {
    Serial.printf("[XFORM_FS] dir open FAIL: %s\n", dir.c_str());
    return false;
  }
  if (!d.isDirectory()) {
    Serial.printf("[XFORM_FS] not a dir: %s\n", dir.c_str());
    d.close();
    return false;
  }

  while (true) {
    File f = d.openNextFile();
    if (!f) break;

    const bool isDir = f.isDirectory();

    // On Arduino FS, f.name() is usually the basename; f.path() may not exist on all cores.
    // We'll build full path from dir + "/" + name.
    String name = String(f.name());
    f.close();

    // Ensure dir ends with '/'
    String base = dir;
    if (!base.endsWith("/")) base += "/";

    String full = base + name;

    Serial.printf("[XFORM_FS] entry: %s%s\n", full.c_str(), isDir ? "/" : "");

    if (isDir) continue;

    if (endsWith(full, ".poly.json")) {
      Serial.printf("[XFORM_FS_XX] load poly json: %s\n", full.c_str());
      loadPoly_fs(sensorId, full, fs);

    } else if (endsWith(full, ".poly.cfg") ||
               endsWith(full, ".poly.txt") ||
               endsWith(full, ".poly")) {
      Serial.printf("[XFORM_FS_XX] load poly cfg: %s\n", full.c_str());
      loadPoly_cfg_fs(sensorId, full, fs);

    } else if (endsWith(full, ".lut.csv")) {
      Serial.printf("[XFORM_FS_XX] load lut csv: %s\n", full.c_str());
      loadLUT_fs(sensorId, full, fs);

    } else {
      Serial.printf("[XFORM_FS] skip (suffix): %s\n", full.c_str());
    }
  }

  d.close();
  return true;
}


const OutputTransform* TransformRegistry::get(const String& sensorId, const String& id) const {
  Serial.printf("[XFORM] reg.get(sensor='%s', id='%s')\n", sensorId.c_str(), id.c_str());
  auto it = sensors_.find(sensorId);
  if (it == sensors_.end()) return nullptr;
  auto jt = it->second.byId.find(id);
  if (jt == it->second.byId.end()) return nullptr;
  return jt->second.get();
}

std::vector<TransformMeta> TransformRegistry::list(const String& sensorId) const {
  std::vector<TransformMeta> out;
  auto it = sensors_.find(sensorId);
  if (it == sensors_.end()) return out;
  for (auto& kv : it->second.byId) out.push_back(kv.second->meta);
  return out;
}

// ---------- SdFs back-end loaders ----------
static bool readAllToString(FsFile& f, String& out) {
  out = "";
  const auto sz = (size_t)f.fileSize();
  if (sz > 0) out.reserve(sz + 1);
  int c;
  while ((c = f.read()) >= 0) out.concat((char)c);
  return true;
}

static bool readAllToString(File& f, String& out) {
  out = "";
  while (f.available()) {
    out += char(f.read());
  }
  return true;
}

static bool readLineSd(FsFile& f, String& line) {
  line = "";
  int16_t c;
  while ((c = f.read()) >= 0) {
    if (c == '\r') continue;
    if (c == '\n') break;
    line.concat((char)c);
  }
  return (line.length() > 0) || (f.curPosition() < f.fileSize());
}

static bool readLineFs(File& f, String& line) {
  line = "";
  while (f.available()) {
    char c = f.read();
    if (c == '\n') return true;
    if (c != '\r') line += c;
  }
  return line.length() > 0;
}

// ---------- helpers ----------
static void parseCoeffList(const String& s, std::vector<float>& out) {
  String token; token.reserve(16);
  for (size_t i = 0; i <= s.length(); ++i) {
    char c = (i < s.length()) ? s[i] : ','; // force flush at end
    if (c == ',' || c == ' ' || c == '\t') {
      token.trim();
      if (token.length()) out.push_back(token.toFloat());
      token = "";
    } else {
      token += c;
    }
  }
}

// ---- POLY loader: plain-text (SdFs backend) ----
bool TransformRegistry::loadPoly_cfg_sd(const String& sensorId, const String& path, SdFs& sd) {
  FsFile f;
  if (!f.open(path.c_str(), O_RDONLY)) return false;

  String id, label, inUnits, outUnits, coeffsLine;
  String line; bool sawCoeffs = false;
  while (readLineSd(f, line)) {
    line.trim();
    if (!line.length()) continue;
    if (line[0] == '#' || line[0] == ';') continue;

    int eq = line.indexOf('=');
    if (eq <= 0) continue;
    String key = line.substring(0, eq); key.trim();
    String val = line.substring(eq + 1); val.trim();

    if (key == "id") id = val;
    else if (key == "label") label = val;
    else if (key == "in_units") inUnits = val;
    else if (key == "out_units") outUnits = val;
    else if (key == "coeffs") { coeffsLine = val; sawCoeffs = true; }
  }
  f.close();

  if (!sawCoeffs) return false;

  std::unique_ptr<PolyTransform> t(new PolyTransform());
  parseCoeffList(coeffsLine, t->a);
  if (t->a.empty()) return false;

  if (!id.length()) {
    int slash = path.lastIndexOf('/'); int dot = path.lastIndexOf('.');
    if (dot < 0) dot = path.length();
    id = path.substring(slash + 1, dot);
  }
  sanitizeId(id);
  if (!label.length()) label = id;

  t->meta.type    = "poly";
  t->meta.id      = id;
  t->meta.label   = label;
  t->meta.inUnits = inUnits;
  t->meta.outUnits= outUnits;

  const String key = t->meta.id;
  sensors_[sensorId].byId[key] = std::move(t);
  return true;
}

bool TransformRegistry::loadPoly_sd(const String& sensorId, const String& path, SdFs& sd) {
  FsFile f;
  if (!f.open(path.c_str(), O_RDONLY)) return false;

  String content;
  readAllToString(f, content);
  f.close();

  StaticJsonDocument<2048> doc;
  DeserializationError err = deserializeJson(doc, content);
  if (err) return false;
  if (doc["type"] != "poly") return false;

  std::unique_ptr<PolyTransform> t(new PolyTransform());
  t->meta.type     = "poly";
  t->meta.id       = doc["id"]        | "";
  t->meta.label    = doc["label"]     | "";
  t->meta.inUnits  = doc["in_units"]  | "";
  t->meta.outUnits = doc["out_units"] | "";

  sanitizeId(t->meta.id);
  if (t->meta.id.isEmpty()) {
    Serial.printf("[XFORM] ERROR: missing '#id=' metadata in file: %s (skipping)\n", path.c_str());
    return false;
  }
  if (t->meta.label.isEmpty()) t->meta.label = t->meta.id;

  JsonArray coeffs = doc["coeffs"].as<JsonArray>();
  for (JsonVariant v : coeffs) t->a.push_back(v.as<float>());
  if (t->a.empty()) return false;

  const String key = t->meta.id;
  sensors_[sensorId].byId[key] = std::move(t);
  return true;
}

bool TransformRegistry::loadLUT_sd(const String& sensorId, const String& path, SdFs& sd) {
  FsFile f;
  if (!f.open(path.c_str(), O_RDONLY)) return false;

  std::unique_ptr<LUTTransform> t(new LUTTransform());
  t->meta.type = "lut";
  t->clamp = true;

  String line; bool body = false;
  while (readLineSd(f, line)) {
    line.trim();
    if (!body && line.startsWith("#")) {
      int eq = line.indexOf('=');
      if (eq > 0) {
        String key = line.substring(1, eq); key.trim();
        String val = line.substring(eq + 1); val.trim();
        if (key == "id") t->meta.id = val;
        else if (key == "label") t->meta.label = val;
        else if (key == "in_units") t->meta.inUnits = val;
        else if (key == "out_units") t->meta.outUnits = val;
        else if (key == "extrapolation") t->clamp = (val != "linear");
      }
      continue;
    }
    body = true;
    if (line.startsWith("#")) continue;
    int comma = line.indexOf(','); if (comma < 0) continue;
    String sx = line.substring(0, comma); sx.trim();
    String sy = line.substring(comma + 1); sy.trim();
    LUTTransform::Node n{ sx.toFloat(), sy.toFloat(), 0.0f };
    t->nodes.push_back(n);
  }
  f.close();

  sanitizeId(t->meta.id);
  if (t->meta.id.isEmpty()) {
    Serial.printf("[XFORM] ERROR: missing '#id=' metadata in file: %s (skipping)\n", path.c_str());
    return false;
  }
  if (t->meta.label.isEmpty()) t->meta.label = t->meta.id;
  if (t->nodes.size() < 2) return false;

  std::sort(t->nodes.begin(), t->nodes.end(), [](const auto& a, const auto& b){ return a.x < b.x; });
  for (size_t i = 0; i + 1 < t->nodes.size(); ++i) {
    float dx = t->nodes[i+1].x - t->nodes[i].x;
    float dy = t->nodes[i+1].y - t->nodes[i].y;
    t->nodes[i].slope = (dx != 0.0f) ? (dy / dx) : 0.0f;
  }
  t->nodes.back().slope = t->nodes[t->nodes.size()-2].slope;

  const String key = t->meta.id;
  sensors_[sensorId].byId[key] = std::move(t);
  return true;
}

bool TransformRegistry::loadPoly_fs(const String& sensorId,
                                    const String& path,
                                    fs::FS& fs)
{
  File f = fs.open(path, FILE_READ);
  if (!f) return false;

  String content;
  readAllToString(f, content);
  f.close();

  StaticJsonDocument<2048> doc;
  DeserializationError err = deserializeJson(doc, content);
  if (err) return false;
  if (doc["type"] != "poly") return false;

  std::unique_ptr<PolyTransform> t(new PolyTransform());
  t->meta.type     = "poly";
  t->meta.id       = doc["id"]        | "";
  t->meta.label    = doc["label"]     | "";
  t->meta.inUnits  = doc["in_units"]  | "";
  t->meta.outUnits = doc["out_units"] | "";

  sanitizeId(t->meta.id);
  if (t->meta.id.isEmpty()) {
    Serial.printf("[XFORM] ERROR: missing '#id=' metadata in file: %s (skipping)\n", path.c_str());
    return false;
  }
  if (t->meta.label.isEmpty()) t->meta.label = t->meta.id;

  JsonArray coeffs = doc["coeffs"].as<JsonArray>();
  for (JsonVariant v : coeffs) {
    t->a.push_back(v.as<float>());
  }
  if (t->a.empty()) return false;

  const String key = t->meta.id;
  sensors_[sensorId].byId[key] = std::move(t);
  return true;
}

bool TransformRegistry::loadLUT_fs(const String& sensorId,
                                   const String& path,
                                   fs::FS& fs)
{
  File f = fs.open(path, FILE_READ);
  if (!f) return false;

  std::unique_ptr<LUTTransform> t(new LUTTransform());
  t->meta.type = "lut";
  t->clamp = true;

  String line;
  bool body = false;

  while (readLineFs(f, line)) {
    line.trim();

    if (!body && line.startsWith("#")) {
      int eq = line.indexOf('=');
      if (eq > 0) {
        String key = line.substring(1, eq); key.trim();
        String val = line.substring(eq + 1); val.trim();
        if      (key == "id")             t->meta.id = val;
        else if (key == "label")          t->meta.label = val;
        else if (key == "in_units")       t->meta.inUnits = val;
        else if (key == "out_units")      t->meta.outUnits = val;
        else if (key == "extrapolation")  t->clamp = (val != "linear");
      }
      continue;
    }

    body = true;
    if (line.startsWith("#")) continue;

    int comma = line.indexOf(',');
    if (comma < 0) continue;

    String sx = line.substring(0, comma);  sx.trim();
    String sy = line.substring(comma + 1); sy.trim();

    LUTTransform::Node n{ sx.toFloat(), sy.toFloat(), 0.0f };
    t->nodes.push_back(n);
  }
  f.close();

  sanitizeId(t->meta.id);
  if (t->meta.id.isEmpty()) {
    Serial.printf("[XFORM] ERROR: missing '#id=' metadata in file: %s (skipping)\n", path.c_str());
    return false;
  }
  if (t->meta.label.isEmpty()) t->meta.label = t->meta.id;
  if (t->nodes.size() < 2) return false;

  std::sort(t->nodes.begin(), t->nodes.end(),
            [](const auto& a, const auto& b){ return a.x < b.x; });

  for (size_t i = 0; i + 1 < t->nodes.size(); ++i) {
    float dx = t->nodes[i+1].x - t->nodes[i].x;
    float dy = t->nodes[i+1].y - t->nodes[i].y;
    t->nodes[i].slope = (dx != 0.0f) ? (dy / dx) : 0.0f;
  }
  t->nodes.back().slope = t->nodes[t->nodes.size() - 2].slope;

  const String key = t->meta.id;
  sensors_[sensorId].byId[key] = std::move(t);
  return true;
}

bool TransformRegistry::loadPoly_cfg_fs(const String& sensorId,
                                        const String& path,
                                        fs::FS& fs)
{
  File f = fs.open(path, FILE_READ);
  if (!f) return false;

  String id, label, inUnits, outUnits, coeffsLine;
  String line;
  bool sawCoeffs = false;

  while (readLineFs(f, line)) {
    line.trim();
    if (!line.length()) continue;
    if (line[0] == '#' || line[0] == ';') continue;

    int eq = line.indexOf('=');
    if (eq <= 0) continue;

    String key = line.substring(0, eq); key.trim();
    String val = line.substring(eq + 1); val.trim();

    if (key == "id") id = val;
    else if (key == "label") label = val;
    else if (key == "in_units") inUnits = val;
    else if (key == "out_units") outUnits = val;
    else if (key == "coeffs") { coeffsLine = val; sawCoeffs = true; }
  }
  f.close();

  if (!sawCoeffs) return false;

  std::unique_ptr<PolyTransform> t(new PolyTransform());
  parseCoeffList(coeffsLine, t->a);
  if (t->a.empty()) return false;

  if (!id.length()) {
    int slash = path.lastIndexOf('/');
    int dot   = path.lastIndexOf('.');
    if (dot < 0) dot = path.length();
    id = path.substring(slash + 1, dot);
  }
  sanitizeId(id);
  if (!label.length()) label = id;

  t->meta.type     = "poly";
  t->meta.id       = id;
  t->meta.label    = label;
  t->meta.inUnits  = inUnits;
  t->meta.outUnits = outUnits;

  const String key = t->meta.id;
  sensors_[sensorId].byId[key] = std::move(t);
  return true;
}

OutputTransform* TransformRegistry::identity() {
  static IdentityTransform kId;
  return &kId;
}
