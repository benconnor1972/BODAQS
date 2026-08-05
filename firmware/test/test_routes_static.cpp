// ─────────────────────────────────────────────────────────────────
// test_routes_static.cpp — Tests for Routes_Static
//
// Tests the flash-embedded asset serving (not SD-card based).
// Only app.css and htmx.min.js are served; all other paths return 404.
//
// Tests:
//   T1:  Serves htmx.min.js with correct content type
//   T2:  Serves app.css with correct content type
//   T3:  Works without query string
//   T4:  Path traversal blocked (..)
//   T5:  Subdirectory blocked (/)
//   T6:  Backslash blocked (\)
//   T7:  Empty filename blocked
//   T8:  Unknown file returns 404
//   T9:  Cache-Control header present
//  T10:  Response body contains asset data
// ─────────────────────────────────────────────────────────────────

#include <cstdio>
#include "Arduino.h"
#include "WebServer.h"
#include "mocks.h"
#include "Routes_Static.h"
#include "WebAssets.h"

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

    // ── T1: Serves htmx.min.js with correct content type ──
    printf("T1: Serves htmx.min.js with correct content type\n");
    {
        mockReset();
        mockHttpFileSenderReset();

        WebServer srv;
        registerStaticRoutes(srv);
        srv.mockInvokeHandler("/static/htmx.min.js?v=cd38187c", HTTP_GET);

        check(mockLastStatus == 200, "status 200 for JS file");
        check(mockLastContentType == "application/javascript", "content-type application/javascript");
        check(mockSendSdFile_called == 0, "sendSdFile not called for flash-embedded JS");
    }
    printf("  passed\n\n");

    // ── T2: Serves app.css with correct content type ──
    printf("T2: Serves app.css with correct content type\n");
    {
        mockReset();
        mockHttpFileSenderReset();

        WebServer srv;
        registerStaticRoutes(srv);
        srv.mockInvokeHandler("/static/app.css?v=1f2cd37c", HTTP_GET);

        check(mockLastStatus == 200, "status 200 for CSS file");
        check(mockLastContentType == "text/css", "content-type text/css");
        check(mockSendSdFile_called == 0, "sendSdFile not called for flash-embedded CSS");
    }
    printf("  passed\n\n");

    // ── T3: Works without query string ──
    printf("T3: Works without query string\n");
    {
        mockReset();
        mockHttpFileSenderReset();

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

        WebServer srv;
        registerStaticRoutes(srv);
        srv.mockInvokeHandler("/static/../etc/passwd", HTTP_GET);

        check(mockLastStatus == 404, "404 for path traversal");
    }
    printf("  passed\n\n");

    // ── T5: Subdirectory blocked (/) ──
    printf("T5: Subdirectory blocked (/)\n");
    {
        mockReset();
        mockHttpFileSenderReset();

        WebServer srv;
        registerStaticRoutes(srv);
        srv.mockInvokeHandler("/static/subdir/file.js", HTTP_GET);

        check(mockLastStatus == 404, "404 for subdirectory path");
    }
    printf("  passed\n\n");

    // ── T6: Backslash blocked (\) ──
    printf("T6: Backslash blocked (\\)\n");
    {
        mockReset();
        mockHttpFileSenderReset();

        WebServer srv;
        registerStaticRoutes(srv);
        srv.mockInvokeHandler("/static/..\\file", HTTP_GET);

        check(mockLastStatus == 404, "404 for backslash path");
    }
    printf("  passed\n\n");

    // ── T7: Empty filename blocked ──
    printf("T7: Empty filename blocked\n");
    {
        mockReset();
        mockHttpFileSenderReset();

        WebServer srv;
        registerStaticRoutes(srv);
        srv.mockInvokeHandler("/static/", HTTP_GET);

        check(mockLastStatus == 404, "404 for empty filename");
    }
    printf("  passed\n\n");

    // ── T8: Unknown file returns 404 ──
    printf("T8: Unknown file returns 404\n");
    {
        mockReset();
        mockHttpFileSenderReset();

        WebServer srv;
        registerStaticRoutes(srv);
        srv.mockInvokeHandler("/static/missing.js", HTTP_GET);

        check(mockLastStatus == 404, "404 for unknown file");
        check(mockSendSdFile_called == 0, "sendSdFile not called for unknown file");
    }
    printf("  passed\n\n");

    // ── T9: Cache-Control header present ──
    printf("T9: Cache-Control header present\n");
    {
        mockReset();
        mockHttpFileSenderReset();

        WebServer srv;
        registerStaticRoutes(srv);
        srv.mockInvokeHandler("/static/htmx.min.js?v=cd38187c", HTTP_GET);

        auto it = mockHeaders.find("Cache-Control");
        check(it != mockHeaders.end(), "Cache-Control header present");
        if (it != mockHeaders.end()) {
            check(it->second == "max-age=31536000", "Cache-Control value is max-age=31536000");
        }
    }
    printf("  passed\n\n");

    // ── T10: Response body contains asset data ──
    printf("T10: Response body contains asset data\n");
    {
        mockReset();
        mockHttpFileSenderReset();

        WebServer srv;
        registerStaticRoutes(srv);
        srv.mockInvokeHandler("/static/app.css", HTTP_GET);

        // The writeResponseChunk stub is a no-op, so we verify via content length
        // and the fact that the handler set it correctly
        check(mockLastStatus == 200, "status 200 for CSS file");
        check(mockContentLength == app_css_len, "content length matches app_css_len");
    }
    printf("  passed\n\n");

    printf("test_routes_static: %d tests passed", passed);
    if (failed > 0) printf(", %d failed", failed);
    printf("\n");

    return failed;
}
