#pragma once

// ─────────────────────────────────────────────────────────────────
// Host-test stub for WebServer.h
// Provides: WebServer class with mock state for testing route handlers
// ─────────────────────────────────────────────────────────────────

#include "Arduino.h"
#include <map>
#include <string>
#include <functional>
#include <vector>

// HTTPMethod — matches ESP32 WebServer enum
enum HTTPMethod {
    HTTP_ANY,
    HTTP_GET,
    HTTP_POST,
    HTTP_PUT,
    HTTP_PATCH,
    HTTP_DELETE,
    HTTP_OPTIONS
};

// ── Mock state (global, accessible from tests) ──

// Request state (set by mockSetHeader/mockSetArg, read by hasHeader/header/arg)
inline std::map<std::string, std::string> mockRequestHeaders;
inline std::map<std::string, std::string> mockRequestArgs;

// Response state (set by send/sendHeader, read by tests)
inline int     mockLastStatus = 0;
inline String  mockLastContentType;
inline String  mockLastBody;
inline std::map<std::string, std::string> mockHeaders;  // response headers
inline size_t  mockContentLength = 0;

// Current request state (set by mockInvokeHandler, read by uri()/method())
inline String     mockCurrentUri;
inline HTTPMethod mockCurrentMethod = HTTP_GET;

// ── Mock setup functions ──

inline void mockSetHeader(const char* name, const char* value) {
    mockRequestHeaders[name] = value ? value : "";
}
inline void mockSetHeader(const String& name, const String& value) {
    mockRequestHeaders[name.c_str()] = value.c_str();
}

inline void mockSetArg(const char* name, const char* value) {
    mockRequestArgs[name] = value ? value : "";
}
inline void mockSetArg(const String& name, const String& value) {
    mockRequestArgs[name.c_str()] = value.c_str();
}

inline void mockReset() {
    mockRequestHeaders.clear();
    mockRequestArgs.clear();
    mockLastStatus = 0;
    mockLastContentType = "";
    mockLastBody = "";
    mockHeaders.clear();
    mockContentLength = 0;
    mockCurrentUri = "";
    mockCurrentMethod = HTTP_GET;
}

// ── WebServer class ──

class WebServer {
public:
    WebServer(int port = 80) : port_(port) {}

    // Request header access
    bool hasHeader(const String& name) const {
        return mockRequestHeaders.count(name.c_str()) > 0;
    }
    String header(const String& name) const {
        auto it = mockRequestHeaders.find(name.c_str());
        return (it != mockRequestHeaders.end()) ? String(it->second.c_str()) : String();
    }

    // Request arg access
    bool hasArg(const String& name) const {
        return mockRequestArgs.count(name.c_str()) > 0;
    }
    String arg(const String& name) const {
        auto it = mockRequestArgs.find(name.c_str());
        return (it != mockRequestArgs.end()) ? String(it->second.c_str()) : String();
    }
    String argName(int i) const {
        if (i < 0 || (size_t)i >= mockRequestArgs.size()) return String();
        auto it = mockRequestArgs.begin();
        std::advance(it, i);
        return String(it->first.c_str());
    }
    int args() const { return (int)mockRequestArgs.size(); }

    // Request info
    String uri() const { return mockCurrentUri; }
    HTTPMethod method() const { return mockCurrentMethod; }

    // Response methods
    void send(int code, const String& contentType, const String& body) {
        mockLastStatus = code;
        mockLastContentType = contentType;
        mockLastBody = body;
    }
    void send(int code, const char* contentType, const char* body) {
        send(code, String(contentType), String(body));
    }
    void send(int code, const String& contentType, const String& body, const String& /*cacheControl*/) {
        send(code, contentType, body);
    }

    void sendHeader(const String& name, const String& value) {
        mockHeaders[name.c_str()] = value.c_str();
    }
    void sendHeader(const char* name, const char* value) {
        mockHeaders[name ? name : ""] = value ? value : "";
    }

    void setContentLength(size_t len) { mockContentLength = len; }

    void sendContent(const String& content) { mockLastBody += content; }
    void sendContent(const char* content) { mockLastBody += content; }

    // Route registration
    void on(const String& uri, HTTPMethod method, std::function<void()> handler) {
        handlers_.push_back({uri, method, std::move(handler)});
    }
    void on(const String& uri, std::function<void()> handler) {
        on(uri, HTTP_ANY, std::move(handler));
    }
    void on(const char* uri, HTTPMethod method, std::function<void()> handler) {
        on(String(uri), method, std::move(handler));
    }

    // Test-driven handler invocation
    void mockInvokeHandler(const String& uri, HTTPMethod method) {
        mockCurrentUri = uri;
        mockCurrentMethod = method;
        for (auto& h : handlers_) {
            if (matchUri_(h.uri, uri) && (h.method == HTTP_ANY || h.method == method)) {
                h.fn();
                return;
            }
        }
    }
    void mockInvokeHandler(const char* uri, HTTPMethod method) {
        mockInvokeHandler(String(uri), method);
    }

private:
    int port_;

    struct Handler {
        String     uri;
        HTTPMethod method;
        std::function<void()> fn;
    };
    std::vector<Handler> handlers_;

    // Match URI with support for trailing * wildcard
    static bool matchUri_(const String& pattern, const String& uri) {
        // Check for wildcard at end: "/static/*"
        if (pattern.endsWith("/*")) {
            String prefix = pattern.substring(0, pattern.length() - 1); // remove *
            return uri.startsWith(prefix);
        }
        return pattern == uri;
    }
};
