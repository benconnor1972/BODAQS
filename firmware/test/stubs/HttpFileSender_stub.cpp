// ─────────────────────────────────────────────────────────────────
// Host-test stub for HttpFileSender functions
// Provides mock implementations that record call parameters
// ─────────────────────────────────────────────────────────────────

#include "HttpFileSender.h"
#include <string>

// Mock state (non-inline — this is a .cpp file)
int    mockSendSdFile_called = 0;
String mockSendSdFile_path;
String mockSendSdFile_contentType;
String mockSendSdFile_downloadName;
String mockSendSdFile_cacheControl;
bool   mockSendSdFile_returnValue = true;

int    mockSendText_called = 0;
int    mockSendText_status = 0;
String mockSendText_contentType;
String mockSendText_body;
String mockSendText_cacheControl;
bool   mockSendText_returnValue = true;

void mockHttpFileSenderReset() {
    mockSendSdFile_called = 0;
    mockSendSdFile_path = "";
    mockSendSdFile_contentType = "";
    mockSendSdFile_downloadName = "";
    mockSendSdFile_cacheControl = "";
    mockSendSdFile_returnValue = true;
    mockSendText_called = 0;
    mockSendText_status = 0;
    mockSendText_contentType = "";
    mockSendText_body = "";
    mockSendText_cacheControl = "";
    mockSendText_returnValue = true;
}

namespace HttpFileSender {

bool sendText(WebServer& srv,
              int statusCode,
              const String& contentType,
              const String& body,
              const String& cacheControl) {
    mockSendText_called++;
    mockSendText_status = statusCode;
    mockSendText_contentType = contentType;
    mockSendText_body = body;
    mockSendText_cacheControl = cacheControl;

    // Simulate what sendText does: set headers and send response
    if (cacheControl.length()) {
        srv.sendHeader("Cache-Control", cacheControl);
    }
    srv.setContentLength(body.length());
    srv.send(statusCode, contentType, body);
    return mockSendText_returnValue;
}

bool sendSdFile(WebServer& srv,
                const String& path,
                const String& contentType,
                const String& downloadName,
                const String& cacheControl) {
    mockSendSdFile_called++;
    mockSendSdFile_path = path;
    mockSendSdFile_contentType = contentType;
    mockSendSdFile_downloadName = downloadName;
    mockSendSdFile_cacheControl = cacheControl;

    if (!mockSendSdFile_returnValue) {
        return false;
    }

    // Simulate what sendSdFile does: set cache header, send 200 with content type
    if (cacheControl.length()) {
        srv.sendHeader("Cache-Control", cacheControl);
    }
    srv.sendHeader("Accept-Ranges", "bytes");
    srv.send(200, contentType, "file-contents");
    return true;
}

bool writeResponseChunk(WebServer& /*srv*/, const void* /*data*/, size_t /*len*/) {
    return true;
}

}  // namespace HttpFileSender
