#include <algorithm>
#include <cstdint>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <set>
#include <string>
#include "StartupReportBuffer.h"
#include "StartupLog.h"

class String {
public:
  std::string text;
  String(const char* value = "") : text(value) {}
  size_t length() const { return text.size(); }
  const char* c_str() const { return text.c_str(); }
  bool reserve(size_t size) { text.reserve(size); return true; }
  int lastIndexOf(char c) const { auto p = text.rfind(c); return p == std::string::npos ? -1 : int(p); }
  int indexOf(char c, int begin = 0) const { auto p = text.find(c, begin); return p == std::string::npos ? -1 : int(p); }
  String substring(int begin, int end) const { return text.substr(begin, end - begin).c_str(); }
  bool operator==(const char* value) const { return text == value; }
  String operator+(const char* value) const { return (text + value).c_str(); }
  String& operator+=(const char* value) { text += value; return *this; }
};
#define F(value) value
#define STOR_LOGW(...) ((void)0)
std::map<std::string, std::string> files;
std::set<std::string> directories;
unsigned reads = 0, writes = 0;
bool shortWrite = false, openFailure = false, renameFailure = false;
bool allocationFailure = false;
unsigned allocated = 0, released = 0;
char* allocatedPointer = nullptr;
void* captureMalloc(size_t count) {
  if (allocationFailure) return nullptr;
  ++allocated; allocatedPointer = static_cast<char*>(std::malloc(count));
  return allocatedPointer;
}
void captureFree(void* pointer) { if (pointer) ++released; std::free(pointer); }
const char* FILE_READ = "r";
const char* FILE_WRITE = "w";
constexpr int CARD_NONE = 0;
struct File {
  std::string path;
  bool valid = false;
  operator bool() const { return valid; }
  int read(uint8_t* target, size_t count) {
    ++reads;
    count = std::min(count, files[path].size());
    memcpy(target, files[path].data(), count); return int(count);
  }
  size_t write(const uint8_t* data, size_t count) {
    ++writes; if (shortWrite && count) --count;
    files[path].assign(reinterpret_cast<const char*>(data), count); return count;
  }
  void close() {}
  void flush() {}
};
struct Filesystem {
  int card = 1;
  int cardType() const { return card; }
  bool exists(const char* path) const { return files.count(path) || directories.count(path); }
  bool mkdir(const char* path) { directories.insert(path); return true; }
  bool remove(const char* path) { return files.erase(path) != 0; }
  bool rename(const char* from, const char* to) {
    if (renameFailure && std::string(from).ends_with(".tmp")) return false;
    auto it = files.find(from); if (it == files.end()) return false;
    files[to] = it->second; files.erase(it); return true;
  }
  File open(const char* path, const char* mode) {
    if (openFailure) return {};
    if (strcmp(mode, FILE_WRITE) == 0) { files[path] = ""; return {path, true}; }
    return {path, files.count(path) != 0};
  }
} SD_MMC;
namespace LoggingManager { bool running = false; bool isRunning() { return running; } }
namespace I2CBusScheduler { bool running = false; bool isRunning() { return running; } }
bool s_sdMounted = true;
unsigned nowMs = 1000;
unsigned millis() { return nowMs; }
bool RTCManager_hasValidTime() { return false; }
uint64_t RTCManager_getEpochMs() { return 0; }
struct FakeSerial {
  std::string text;
  void print(const char* value) { text += value; }
  void println(const char* value) { text += value; text += '\n'; }
  void printf(const char* format, ...) {
    char out[1024]; va_list args; va_start(args, format);
    vsnprintf(out, sizeof(out), format, args); va_end(args); text += out;
  }
} Serial;

// PRODUCTION_STORAGE
#define malloc captureMalloc
#define free captureFree
// PRODUCTION_COLLECTOR
#undef malloc
#undef free

unsigned checks = 0, failures = 0;
void check(bool condition, const char* message) {
  ++checks; if (!condition) { ++failures; std::printf("FAIL startup report: %s\n", message); }
}
int main() {
  StartupLog::begin(false);
  StartupLog::printf("serial only\n"); StartupLog::recordf("ignored\n"); StartupLog::finish();
  check(allocated == 0 && writes == 0 && reads == 0, "disabled capture allocates and accesses no SD");
  check(Serial.text == "serial only\n", "serial output remains available when capture disabled");
  check(StartupLog::begin(true), "enabled capture allocates bounded storage");
  StartupLog::printf("attempt ok=0 chip=0x20\n");
  StartupLog::recordf("controller reset\n");
  StartupLog::printf("attempt ok=1 chip=0x24\n");
  check(writes == 0 && reads == 0, "initial attempts and recovery never access SD");
  StartupLog::finish();
  check(!StartupLog::active() && released == allocated, "successful finish releases capture RAM");
  auto report = files["/startup/boot-00.txt"];
  check(report.find("sequence=1") != std::string::npos && report.find("chip=0x20") < report.find("chip=0x24"), "report retains original failure before recovery success");
  check(report.find("controller reset") != std::string::npos && Serial.text.find("controller reset") == std::string::npos, "record-only events are saved without duplicate serial output");
  check(report.find("capture_overflow=0") != std::string::npos && report.find("rtc_valid=0") != std::string::npos, "completion survives invalid RTC and marks completeness");
  unsigned priorWrites = writes;
  StartupLog::printf("later runtime attempt\n"); StartupLog::finish();
  check(writes == priorWrites && report == files["/startup/boot-00.txt"], "post-startup events neither change the report nor write SD");

  StartupLog::begin(true);
  for (unsigned i = 0; i < 1000; ++i) StartupLog::recordf("message %u xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n", i);
  StartupLog::setFinalReadiness(5, 2);
  StartupLog::finish(); report = files["/startup/boot-01.txt"];
  check(report.size() < 33000 && report.find("capture_overflow=1") != std::string::npos, "overflow remains bounded with an explicit footer");
  check(report.find("dropped_messages=0") == std::string::npos && report.find("END ") != std::string::npos, "overflow records dropped-message count and completion");
  check(report.find("readiness_known=1 final_i2c_checked=5 final_i2c_failed=2") != std::string::npos, "final readiness survives capture overflow");
  check(report.find("message 0 ") != std::string::npos && report.find("message 999 ") == std::string::npos, "overflow preserves an ordered prefix of complete messages");
  StartupLog::begin(true);
  StartupLog::recordf("%s", std::string(1000, 'x').c_str());
  StartupLog::recordf("small later message\n"); StartupLog::finish();
  report = files["/startup/boot-02.txt"];
  check(report.find("dropped_messages=2") != std::string::npos && report.find("dropped_bytes=1020") != std::string::npos, "oversized formatting is counted, subsequent messages consistently dropped");

  files.clear();
  for (unsigned i = 1; i <= 40; ++i) {
    char path[48]; check(StorageManager_saveStartupReport("successful boot\n", path, sizeof(path)), "rotated save succeeds");
  }
  check(files.size() == 32, "forty boots retain exactly thirty-two complete reports");
  check(files["/startup/boot-00.txt"].find("sequence=33\n") != std::string::npos &&
        files["/startup/boot-07.txt"].find("sequence=40\n") != std::string::npos &&
        files["/startup/boot-08.txt"].find("sequence=9\n") != std::string::npos,
        "rotation overwrites oldest slots with increasing sequence independent of RTC");
  auto previous = files["/startup/boot-08.txt"];
  shortWrite = true; char path[48] = {};
  check(!StorageManager_saveStartupReport("partial\n", path, sizeof(path)) && !path[0], "short write fails explicitly without reporting a saved path");
  check(files["/startup/boot-08.txt"] == previous && files.size() == 32, "short write preserves previous report and removes incomplete temp");
  shortWrite = false; renameFailure = true;
  check(!StorageManager_saveStartupReport("new\n", path, sizeof(path)), "final rename failure reported");
  check(files["/startup/boot-08.txt"] == previous && files.size() == 32, "rename failure restores previous report from backup");
  renameFailure = false;
  check(StorageManager_saveStartupReport("retry\n", path, sizeof(path)) &&
        files[path].find("sequence=41\n") != std::string::npos, "failed save does not advance sequence");

  priorWrites = writes; s_sdMounted = false;
  check(!StorageManager_saveStartupReport("boot\n", path, sizeof(path)) && writes == priorWrites, "unmounted SD refuses save");
  s_sdMounted = true; SD_MMC.card = CARD_NONE;
  StartupLog::begin(true); StartupLog::finish();
  check(!StartupLog::active() && released == allocated && writes == priorWrites, "missing card releases RAM and adds no runtime retry");
  SD_MMC.card = 1; openFailure = true;
  StartupLog::begin(true); StartupLog::finish();
  check(!StartupLog::active() && released == allocated, "SD open failure releases RAM");
  openFailure = false; LoggingManager::running = true;
  check(!StorageManager_saveStartupReport("boot\n", path, sizeof(path)), "active logger forbids report save");
  LoggingManager::running = false; I2CBusScheduler::running = true;
  check(!StorageManager_saveStartupReport("boot\n", path, sizeof(path)), "active acquisition worker forbids report save");
  I2CBusScheduler::running = false;
  allocationFailure = true;
  check(!StartupLog::begin(true) && !StartupLog::active(), "allocation failure leaves capture disabled");
  StartupLog::finish(); allocationFailure = false;
  check(Serial.text.find("allocation failed") != std::string::npos, "allocation failure visible on serial");
  check(!StorageManager_saveStartupReport(std::string(32769, 'x').c_str(), path, sizeof(path)), "oversize reports cannot defeat retention bound");
  files.clear(); files["/startup/boot-00.txt"] = "corrupt header\n";
  check(StorageManager_saveStartupReport("boot\n", path, sizeof(path)) &&
        files[path].find("sequence=1\n") != std::string::npos, "corrupt sequence header does not prevent future reports");
  std::printf("Startup report production runtime: %u checks, %u failures\n", checks, failures);
  return failures ? 1 : 0;
}
