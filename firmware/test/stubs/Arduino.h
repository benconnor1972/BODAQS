#pragma once

// ─────────────────────────────────────────────────────────────────
// Host-test stub for Arduino.h
// Provides: String, F(), delay(), millis(), basic types, LOG macros
// ─────────────────────────────────────────────────────────────────

#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>   // strcasecmp
#include <ctype.h>     // isspace, tolower, toupper
#include <stdio.h>

// ── F() macro ──
// Real Arduino wraps in __FlashStringHelper; for host tests, pass-through.
#define F(x) (static_cast<const char*>(x))

// ── delay / millis ──
inline void delay(unsigned long /*ms*/) {}
inline unsigned long millis() {
    static unsigned long m = 0;
    return m++;
}

// ── LOG macros (no-ops) ──
#ifndef LOGE_TAG
#define LOGE_TAG(tag, ...) do{}while(0)
#endif
#ifndef LOGW_TAG
#define LOGW_TAG(tag, ...) do{}while(0)
#endif
#ifndef LOGI_TAG
#define LOGI_TAG(tag, ...) do{}while(0)
#endif
#ifndef LOGD_TAG
#define LOGD_TAG(tag, ...) do{}while(0)
#endif
#ifndef LOGE
#define LOGE(...) do{}while(0)
#endif
#ifndef LOGW
#define LOGW(...) do{}while(0)
#endif
#ifndef LOGI
#define LOGI(...) do{}while(0)
#endif
#ifndef LOGD
#define LOGD(...) do{}while(0)
#endif

// ── String class ──
// Subset of Arduino's String with all methods used by HtmlUtil and route handlers.
class String {
public:
    // Constructors
    String() : buf_(nullptr), len_(0), cap_(0) {}
    String(const char* s) : buf_(nullptr), len_(0), cap_(0) { copy_(s); }
    String(const String& other) : buf_(nullptr), len_(0), cap_(0) {
        copy_(other.c_str(), other.length());
    }
    String(char c) : buf_(nullptr), len_(0), cap_(0) {
        char tmp[2] = {c, '\0'};
        copy_(tmp);
    }

    ~String() { if (buf_) free(buf_); }

    // Assignment
    String& operator=(const String& other) {
        if (this != &other) copy_(other.c_str(), other.length());
        return *this;
    }
    String& operator=(const char* s) { copy_(s); return *this; }
    String& operator=(char c) {
        char tmp[2] = {c, '\0'};
        copy_(tmp);
        return *this;
    }

    // Capacity
    size_t length() const { return len_; }
    void reserve(size_t size) {
        if (size + 1 > cap_) {
            cap_ = size + 1;
            char* nb = (char*)realloc(buf_, cap_);
            if (nb) {
                buf_ = nb;
                if (len_ == 0) buf_[0] = '\0';
            }
        }
    }

    // Access
    const char* c_str() const { return buf_ ? buf_ : ""; }
    char operator[](int idx) const { return buf_ ? buf_[idx] : '\0'; }
    char& operator[](int idx) {
        static char dummy = '\0';
        return buf_ ? buf_[idx] : dummy;
    }
    char charAt(int idx) const { return (*this)[idx]; }

    // Concatenation
    String& operator+=(const String& other) {
        append_(other.c_str(), other.length());
        return *this;
    }
    String& operator+=(const char* s) {
        append_(s ? s : "", s ? strlen(s) : 0);
        return *this;
    }
    String& operator+=(char c) { append_(&c, 1); return *this; }

    String operator+(const String& other) const { String r(*this); r += other; return r; }
    String operator+(const char* s) const { String r(*this); r += s; return r; }
    String operator+(char c) const { String r(*this); r += c; return r; }

    // Comparison
    bool operator==(const String& other) const {
        return strcmp(c_str(), other.c_str()) == 0;
    }
    bool operator==(const char* s) const {
        return s ? strcmp(c_str(), s) == 0 : false;
    }
    bool operator!=(const String& other) const { return !(*this == other); }
    bool operator!=(const char* s) const { return !(*this == s); }

    bool equalsIgnoreCase(const String& other) const {
        return strcasecmp(c_str(), other.c_str()) == 0;
    }
    bool equalsIgnoreCase(const char* s) const {
        return s ? strcasecmp(c_str(), s) == 0 : false;
    }

    // Search
    int indexOf(char c, int from = 0) const {
        if (!buf_ || from < 0 || (size_t)from >= len_) return -1;
        const char* p = strchr(buf_ + from, c);
        return p ? (int)(p - buf_) : -1;
    }
    int indexOf(const char* s, int from = 0) const {
        if (!buf_ || !s || from < 0 || (size_t)from >= len_) return -1;
        const char* p = strstr(buf_ + from, s);
        return p ? (int)(p - buf_) : -1;
    }
    int indexOf(const String& s, int from = 0) const {
        return indexOf(s.c_str(), from);
    }
    int lastIndexOf(char c) const {
        if (!buf_) return -1;
        const char* p = strrchr(buf_, c);
        return p ? (int)(p - buf_) : -1;
    }

    // Substring
    String substring(int start) const {
        if (start < 0) start = 0;
        if ((size_t)start >= len_) return String();
        return String(buf_ + start);
    }
    String substring(int start, int end) const {
        if (start < 0) start = 0;
        if (end < 0) end = 0;
        if ((size_t)start >= len_ || start >= end) return String();
        if ((size_t)end > len_) end = (int)len_;
        int n = end - start;
        String r;
        r.reserve(n);
        memcpy(r.buf_, buf_ + start, n);
        r.len_ = n;
        r.buf_[n] = '\0';
        return r;
    }

    // Modification
    void remove(int index) {
        if (!buf_ || index < 0 || (size_t)index >= len_) return;
        len_ = index;
        buf_[len_] = '\0';
    }
    void remove(int index, int count) {
        if (!buf_ || index < 0 || count <= 0 || (size_t)index >= len_) return;
        if ((size_t)(index + count) > len_) count = (int)(len_ - index);
        memmove(buf_ + index, buf_ + index + count, len_ - index - count + 1);
        len_ -= count;
    }

    void trim() {
        if (!buf_ || len_ == 0) return;
        int start = 0;
        while ((size_t)start < len_ && isspace((unsigned char)buf_[start])) start++;
        int end = (int)len_ - 1;
        while (end >= start && isspace((unsigned char)buf_[end])) end--;
        if (start > 0 || (size_t)(end + 1) < len_) {
            if (end < start) {
                len_ = 0;
                buf_[0] = '\0';
            } else {
                memmove(buf_, buf_ + start, end - start + 1);
                len_ = end - start + 1;
                buf_[len_] = '\0';
            }
        }
    }

    void toLowerCase() {
        if (!buf_) return;
        for (size_t i = 0; i < len_; i++)
            buf_[i] = tolower((unsigned char)buf_[i]);
    }

    void toUpperCase() {
        if (!buf_) return;
        for (size_t i = 0; i < len_; i++)
            buf_[i] = toupper((unsigned char)buf_[i]);
    }

    // Query
    bool endsWith(const char* s) const {
        if (!s) return false;
        size_t slen = strlen(s);
        if (slen > len_) return false;
        return strcmp(buf_ + len_ - slen, s) == 0;
    }
    bool endsWith(const String& s) const { return endsWith(s.c_str()); }

    bool startsWith(const char* s) const {
        if (!s) return false;
        size_t slen = strlen(s);
        if (slen > len_) return false;
        return strncmp(buf_, s, slen) == 0;
    }
    bool startsWith(const String& s) const { return startsWith(s.c_str()); }

    // Conversion
    long toInt() const { return buf_ ? atol(buf_) : 0; }
    float toFloat() const { return buf_ ? strtof(buf_, nullptr) : 0.0f; }

private:
    char*  buf_;
    size_t len_;
    size_t cap_;

    void copy_(const char* s, size_t n = 0) {
        if (!s) {
            if (buf_) buf_[0] = '\0';
            len_ = 0;
            return;
        }
        if (n == 0) n = strlen(s);
        if (n + 1 > cap_) {
            cap_ = n + 1;
            char* nb = (char*)realloc(buf_, cap_);
            if (!nb) return;
            buf_ = nb;
        }
        memcpy(buf_, s, n);
        buf_[n] = '\0';
        len_ = n;
    }

    void append_(const char* s, size_t n) {
        if (!s || n == 0) return;
        if (len_ + n + 1 > cap_) {
            cap_ = len_ + n + 1;
            char* nb = (char*)realloc(buf_, cap_);
            if (!nb) return;
            buf_ = nb;
        }
        memcpy(buf_ + len_, s, n);
        len_ += n;
        buf_[len_] = '\0';
    }

    // Allow substring() to write directly to buf_
    friend String operator+(const char*, const String&);
};

// Free operators for const char* + String
inline String operator+(const char* lhs, const String& rhs) {
    String r(lhs);
    r += rhs;
    return r;
}
inline bool operator==(const char* lhs, const String& rhs) {
    return rhs == lhs;
}
inline bool operator!=(const char* lhs, const String& rhs) {
    return !(rhs == lhs);
}
