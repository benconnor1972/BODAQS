#pragma once

// ─────────────────────────────────────────────────────────────────
// Host-test stub for SD_MMC.h
// Provides: SD_MMC as an object (matching ESP32 API), File class
// ─────────────────────────────────────────────────────────────────

#include "Arduino.h"
#include <map>
#include <string>

// Card type constants (match ESP32 SD_MMC)
#define CARD_NONE  0
#define CARD_MMC   1
#define CARD_SD    2
#define CARD_SDHC  3

// ── File class ──

class File {
public:
    File() : valid_(false), isDir_(false), data_(""), pos_(0) {}
    File(const String& path, const String& data, bool isDir = false)
        : valid_(true), isDir_(isDir), path_(path), data_(data), pos_(0) {}

    // Validity
    operator bool() const { return valid_; }

    // Properties
    bool isDirectory() const { return isDir_; }
    size_t size() const { return data_.length(); }
    String name() const {
        // Return last path component
        int slash = path_.lastIndexOf('/');
        return (slash >= 0) ? path_.substring(slash + 1) : path_;
    }

    // I/O
    int read(uint8_t* buf, size_t n) {
        if (!valid_ || pos_ >= data_.length()) return 0;
        size_t avail = data_.length() - pos_;
        size_t toRead = (n < avail) ? n : avail;
        memcpy(buf, data_.c_str() + pos_, toRead);
        pos_ += toRead;
        return (int)toRead;
    }
    size_t write(const uint8_t* buf, size_t n) {
        if (!valid_) return 0;
        // Append to data (simplified mock)
        for (size_t i = 0; i < n; i++) {
            data_ += (char)buf[i];
        }
        return n;
    }
    void close() { valid_ = false; }

    // Directory iteration (simplified — returns empty in mock)
    File openNextFile() { return File(); }

private:
    bool   valid_;
    bool   isDir_;
    String path_;
    String data_;
    size_t pos_;
};

// ── Mock state (global, accessible from tests) ──

inline std::map<std::string, std::string> mockSdFiles;
inline std::map<std::string, bool> mockSdDirs;
inline int mockSdCardType = CARD_MMC;  // default: card present

// Mock setup functions (global, callable from tests)
inline void mockSetFile(const String& path, const String& contents) {
    mockSdFiles[path.c_str()] = contents.c_str();
}
inline void mockSetFile(const char* path, const char* contents) {
    mockSdFiles[path] = contents ? contents : "";
}

inline bool mockFileExists(const String& path) {
    return mockSdFiles.count(path.c_str()) > 0 || mockSdDirs.count(path.c_str()) > 0;
}

inline void mockSetCardType(int type) { mockSdCardType = type; }

inline void mockSdReset() {
    mockSdFiles.clear();
    mockSdDirs.clear();
    mockSdCardType = CARD_MMC;
}

// ── SD_MMC class (instance matches ESP32 API: SD_MMC.cardType(), SD_MMC.exists(), etc.) ──

class SdMmcClass {
public:
    int cardType() const { return mockSdCardType; }

    File open(const String& path, const char* mode = "r") {
        auto it = mockSdFiles.find(path.c_str());
        if (it != mockSdFiles.end()) {
            return File(path, String(it->second.c_str()), false);
        }
        auto dit = mockSdDirs.find(path.c_str());
        if (dit != mockSdDirs.end()) {
            return File(path, "", true);
        }
        return File();  // invalid
    }

    bool exists(const String& path) const {
        return mockSdFiles.count(path.c_str()) > 0 || mockSdDirs.count(path.c_str()) > 0;
    }

    bool remove(const String& path) const {
        auto it = mockSdFiles.find(path.c_str());
        if (it != mockSdFiles.end()) {
            mockSdFiles.erase(it);
            return true;
        }
        return false;
    }

    bool mkdir(const String& path) const {
        mockSdDirs[path.c_str()] = true;
        return true;
    }

    bool rmdir(const String& path) const {
        auto it = mockSdDirs.find(path.c_str());
        if (it != mockSdDirs.end()) {
            mockSdDirs.erase(it);
            return true;
        }
        return false;
    }

    uint64_t cardSize() const { return 8ULL * 1024 * 1024 * 1024; }  // 8 GB
    uint64_t totalBytes() const { return 8ULL * 1024 * 1024 * 1024; }
    uint64_t usedBytes() const { return 0; }
};

// Global instance — matches ESP32 API: SD_MMC.cardType(), SD_MMC.exists(), etc.
inline SdMmcClass SD_MMC;
