// ─────────────────────────────────────────────────────────────────
// test_routes_static.cpp — Tests for Routes_Static
//
// Tests:
//   T1:  Serves JS file with correct content type
//   T2:  Serves CSS file with correct content type
//   T3:  Works without query string
//   T4:  Path traversal blocked (..)
//   T5:  Subdirectory blocked (/)
//   T6:  Backslash blocked (\)
//   T7:  Empty filename blocked
//   T8:  File not found returns 404
//   T9:  No SD card returns 404
//   T10: Content type for .js
//   T11: Content type for .css
//   T12: Cache-Control header present
// ─────────────────────────────────────────────────────────────────

#include <cstdio>
#include "Arduino.h"
#include "WebServer.h"
#include "SD_MMC.h"
#include "mocks.h"
#include "Routes_Static.h"

// HttpFileSender stub state (from HttpFileSender_stub.cpp)
extern int    mockSendSdFile_called;
extern String mockSendSdFile_path;
extern String mockSendSdFile_contentType;
extern String mockSendSdFile_cacheControl;
extern void   mockHttpFileSenderReset();

int runRoutesStaticTests() {
    int passed = 0;
    int failed = 0;

    auto check = [&](bool cond, const char* desc) {
        if (cond) {
            passed++;
        } else {
            printf("    FAIL: test_routes_static: %s\n", desc);
            failed++;
        }
    };

    // ── T1: Serves JS file with correct content type ──
    printf("T1: Serves JS file with correct content type\n");
    {
        mockReset();
        mockHttpFileSenderReset();
        mockSdReset();
        mockSetFile("/www/htmx.min.js", "htmx-content");

        WebServer srv;
        registerStaticRoutes(srv);
        srv.mockInvokeHandler("/static/htmx.min.js?v=0.4.1", HTTP_GET);

        check(mockLastStatus == 200, "status 200 for JS file");
        check(mockLastContentType == "application/javascript", "content-type application/javascript");
    }
    printf("  passed\n\n");

    // ── T2: Serves CSS file with correct content type ──
    printf("T2: Serves CSS file with correct content type\n");
    {
        mockReset();
        mockHttpFileSenderReset();
        mockSdReset();
        mockSetFile("/www/app.css", "css-content");

        WebServer srv;
        registerStaticRoutes(srv);
        srv.mockInvokeHandler("/static/app.css?v=0.4.1", HTTP_GET);

        check(mockLastStatus == 200, "status 200 for CSS file");
        check(mockLastContentType == "text/css", "content-type text/css");
    }
    printf("  passed\n\n");

    // ── T3: Works without query string ──
    printf("T3: Works without query string\n");
    {
        mockReset();
        mockHttpFileSenderReset();
        mockSdReset();
        mockSetFile("/www/htmx.min.js", "htmx-content");

        WebServer srv;
        registerStaticRoutes(srv);
        srv.mockInvokeHandler("/static/htmx.min.js", HTTP_GET);

        check(mockLastStatus == 200, "status 200 without query string");
    }
    printf("  passed\n\n");

    // ── T4: Path traversal blocked (..) ──
    printf("T4: Path traversal blocked (..)\n");
    {
        mockReset();
        mockHttpFileSenderReset();
        mockSdReset();
        mockSetFile("/www/htmx.min.js", "htmx-content");

        WebServer srv;
        registerStaticRoutes(srv);
        srv.mockInvokeHandler("/static/../etc/passwd", HTTP_GET);

        check(mockLastStatus == 404, "404 for path traversal");
        check(mockSendSdFile_called == 0, "sendSdFile not called for traversal");
    }
    printf("  passed\n\n");

    // ── T5: Subdirectory blocked (/) ──
    printf("T5: Subdirectory blocked (/)\n");
    {
        mockReset();
        mockHttpFileSenderReset();
        mockSdReset();

        WebServer srv;
        registerStaticRoutes(srv);
        srv.mockInvokeHandler("/static/subdir/file.js", HTTP_GET);

        check(mockLastStatus == 404, "404 for subdirectory path");
        check(mockSendSdFile_called == 0, "sendSdFile not called for subdirectory");
    }
    printf("  passed\n\n");

    // ── T6: Backslash blocked (\) ──
    printf("T6: Backslash blocked (\\)\n");
    {
        mockReset();
        mockHttpFileSenderReset();
        mockSdReset();

        WebServer srv;
        registerStaticRoutes(srv);
        srv.mockInvokeHandler("/static/..\\file", HTTP_GET);

        check(mockLastStatus == 404, "404 for backslash path");
        check(mockSendSdFile_called == 0, "sendSdFile not called for backslash");
    }
    printf("  passed\n\n");

    // ── T7: Empty filename blocked ──
    printf("T7: Empty filename blocked\n");
    {
        mockReset();
        mockHttpFileSenderReset();
        mockSdReset();

        WebServer srv;
        registerStaticRoutes(srv);
        srv.mockInvokeHandler("/static/", HTTP_GET);

        check(mockLastStatus == 404, "404 for empty filename");
        check(mockSendSdFile_called == 0, "sendSdFile not called for empty filename");
    }
    printf("  passed\n\n");

    // ── T8: File not found returns 404 ──
    printf("T8: File not found returns 404\n");
    {
        mockReset();
        mockHttpFileSenderReset();
        mockSdReset();
        // SD card present but file doesn't exist

        WebServer srv;
        registerStaticRoutes(srv);
        srv.mockInvokeHandler("/static/missing.js", HTTP_GET);

        check(mockLastStatus == 404, "404 for missing file");
        check(mockSendSdFile_called == 0, "sendSdFile not called for missing file");
    }
    printf("  passed\n\n");

    // ── T9: No SD card returns 404 ──
    printf("T9: No SD card returns 404\n");
    {
        mockReset();
        mockHttpFileSenderReset();
        mockSdReset();
        mockSetCardType(CARD_NONE);

        WebServer srv;
        registerStaticRoutes(srv);
        srv.mockInvokeHandler("/static/htmx.min.js", HTTP_GET);

        check(mockLastStatus == 404, "404 when no SD card");
        check(mockSendSdFile_called == 0, "sendSdFile not called when no SD card");
    }
    printf("  passed\n\n");

    // ── T10: Content type for .js ──
    printf("T10: Content type for .js\n");
    {
        mockReset();
        mockHttpFileSenderReset();
        mockSdReset();
        mockSetFile("/www/test.js", "js");

        WebServer srv;
        registerStaticRoutes(srv);
        srv.mockInvokeHandler("/static/test.js", HTTP_GET);

        check(mockSendSdFile_contentType == "application/javascript",
              "sendSdFile called with application/javascript for .js");
    }
    printf("  passed\n\n");

    // ── T11: Content type for .css ──
    printf("T11: Content type for .css\n");
    {
        mockReset();
        mockHttpFileSenderReset();
        mockSdReset();
        mockSetFile("/www/test.css", "css");

        WebServer srv;
        registerStaticRoutes(srv);
        srv.mockInvokeHandler("/static/test.css", HTTP_GET);

        check(mockSendSdFile_contentType == "text/css",
              "sendSdFile called with text/css for .css");
    }
    printf("  passed\n\n");

    // ── T12: Cache-Control header present ──
    printf("T12: Cache-Control header present\n");
    {
        mockReset();
        mockHttpFileSenderReset();
        mockSdReset();
        mockSetFile("/www/htmx.min.js", "htmx-content");

        WebServer srv;
        registerStaticRoutes(srv);
        srv.mockInvokeHandler("/static/htmx.min.js?v=0.4.1", HTTP_GET);

        // The stub sendSdFile sets Cache-Control header on the server
        auto it = mockHeaders.find("Cache-Control");
        check(it != mockHeaders.end(), "Cache-Control header present");
        if (it != mockHeaders.end()) {
            check(it->second == "max-age=31536000", "Cache-Control value is max-age=31536000");
        }
    }
    printf("  passed\n\n");

    printf("test_routes_static: %d tests passed", passed);
    if (failed > 0) printf(", %d failed", failed);
    printf("\n");

    return failed;
}
