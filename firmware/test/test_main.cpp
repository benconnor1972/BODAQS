// ─────────────────────────────────────────────────────────────────
// test_main.cpp — verifies stubs compile and basic operations work
//
// Tests:
//   T2: String class supports basic operations
//   T3: WebServer mock state works
//   T4: SD_MMC mock file map works
//   T5: HtmlUtil compiles, links, and runs
// ─────────────────────────────────────────────────────────────────

#include <cstdio>
#include <cstdlib>
#include "Arduino.h"
#include "WebServer.h"
#include "SD_MMC.h"
#include "mocks.h"
#include "HtmlUtil.h"

// Defined in test_htmlutil.cpp
int runHtmlUtilTests();

// Defined in test_routes_static.cpp
int runRoutesStaticTests();

// Defined in test_fragments.cpp
int runFragmentsTests();

// Defined in test_bmi270_profile.cpp
int runBMI270ProfileTests();

// Defined in test_bmi270_fifo.cpp
int runBMI270FifoTests();

static int tests_passed = 0;
static int tests_failed = 0;

#define CHECK(cond) \
    do { \
        if (cond) { \
            tests_passed++; \
        } else { \
            printf("    FAIL: %s:%d: %s\n", __FILE__, __LINE__, #cond); \
            tests_failed++; \
        } \
    } while (0)

int main() {
    printf("Running stub tests...\n\n");

    // ── T2: String operations ──
    printf("T2: String operations\n");
    {
        String s("hello");
        CHECK(s.length() == 5);

        String s2 = s + " world";
        CHECK(s2 == "hello world");
        CHECK(s2.length() == 11);

        String s3 = "world";
        CHECK(s3.startsWith("wor"));
        CHECK(s3.endsWith("rld"));

        String s4 = "  trim  ";
        s4.trim();
        CHECK(s4 == "trim");

        String s5 = "Hello";
        s5.toLowerCase();
        CHECK(s5 == "hello");

        String s6 = "hello";
        CHECK(s6.indexOf('l') == 2);
        CHECK(s6.lastIndexOf('l') == 3);

        String s7 = "hello world";
        CHECK(s7.substring(0, 5) == "hello");
        CHECK(s7.substring(6) == "world");

        String s8 = "hello";
        s8.remove(2);
        CHECK(s8 == "he");

        String s9 = "hello";
        s9 += '!';
        CHECK(s9 == "hello!");

        String s10 = "hello";
        CHECK(s10[0] == 'h');
        CHECK(s10[4] == 'o');

        String s11 = "Hello";
        CHECK(s11.equalsIgnoreCase("hello"));

        String s12 = "/path/to/file";
        CHECK(s12.lastIndexOf('/') == 8);

        String s13 = "test";
        s13.toUpperCase();
        CHECK(s13 == "TEST");

        String s14 = "42";
        CHECK(s14.toInt() == 42);

        // const char* + String
        String s15 = "/" + String("path");
        CHECK(s15 == "/path");

        // F() macro
        String s16 = F("literal");
        CHECK(s16 == "literal");

        // reserve
        String s17;
        s17.reserve(100);
        s17 += "test";
        CHECK(s17 == "test");

        // remove(index, count)
        String s18 = "hello world";
        s18.remove(5, 6);  // remove " world"
        CHECK(s18 == "hello");
    }
    printf("  passed\n\n");

    // ── T3: WebServer mock state ──
    printf("T3: WebServer mock state\n");
    {
        WebServer srv(80);
        mockReset();

        // Header mock
        mockSetHeader("HX-Request", "true");
        CHECK(srv.hasHeader("HX-Request"));
        CHECK(srv.header("HX-Request") == "true");
        CHECK(!srv.hasHeader("Nonexistent"));

        // Arg mock
        mockSetArg("path", "/test");
        CHECK(srv.hasArg("path"));
        CHECK(srv.arg("path") == "/test");
        CHECK(srv.args() == 1);
        CHECK(srv.argName(0) == "path");

        // Send response
        srv.send(200, "text/html", "<p>OK</p>");
        CHECK(mockLastStatus == 200);
        CHECK(mockLastContentType == "text/html");
        CHECK(mockLastBody == "<p>OK</p>");

        // Response headers
        srv.sendHeader("HX-Redirect", "/files");
        CHECK(mockHeaders.count("HX-Redirect") > 0);
        CHECK(mockHeaders["HX-Redirect"] == "/files");

        // Handler registration and invocation
        bool handlerCalled = false;
        srv.on("/test", HTTP_GET, [&handlerCalled]() { handlerCalled = true; });
        srv.mockInvokeHandler("/test", HTTP_GET);
        CHECK(handlerCalled);
        CHECK(srv.uri() == "/test");
        CHECK(srv.method() == HTTP_GET);

        // Wildcard handler matching
        bool wildcardCalled = false;
        srv.on("/static/*", HTTP_GET, [&wildcardCalled]() { wildcardCalled = true; });
        srv.mockInvokeHandler("/static/htmx.min.js", HTTP_GET);
        CHECK(wildcardCalled);

        // sendContent
        mockReset();
        srv.sendContent("chunk1");
        srv.sendContent("chunk2");
        CHECK(mockLastBody == "chunk1chunk2");
    }
    printf("  passed\n\n");

    // ── T4: SD_MMC mock file map ──
    printf("T4: SD_MMC mock file map\n");
    {
        mockSdReset();

        // Set and check file existence
        mockSetFile("/www/htmx.min.js", "htmxcontent");
        CHECK(SD_MMC.exists("/www/htmx.min.js"));
        CHECK(!SD_MMC.exists("/www/nonexistent.js"));

        // Open file
        File f = SD_MMC.open("/www/htmx.min.js");
        CHECK(f);
        CHECK(f.size() == 11);
        CHECK(f.name() == "htmx.min.js");

        // Read file
        uint8_t buf[16] = {0};
        int nread = f.read(buf, 11);
        CHECK(nread == 11);
        CHECK(memcmp(buf, "htmxcontent", 11) == 0);

        // Card type
        CHECK(SD_MMC.cardType() != CARD_NONE);
        mockSetCardType(CARD_NONE);
        CHECK(SD_MMC.cardType() == CARD_NONE);
        mockSetCardType(CARD_MMC);

        // Directory operations
        CHECK(SD_MMC.mkdir("/www/newdir"));
        CHECK(SD_MMC.exists("/www/newdir"));
        CHECK(SD_MMC.rmdir("/www/newdir"));
        CHECK(!SD_MMC.exists("/www/newdir"));

        // Remove file
        CHECK(SD_MMC.remove("/www/htmx.min.js"));
        CHECK(!SD_MMC.exists("/www/htmx.min.js"));
    }
    printf("  passed\n\n");

    // ── T5: HtmlUtil integration ──
    printf("T5: HtmlUtil integration\n");
    {
        mockResetAll();
        mockReset();

        String header = HtmlUtil::htmlHeader("Test");
        CHECK(header.length() > 0);
        CHECK(header.startsWith("<!DOCTYPE html>"));
        CHECK(header.indexOf("BODAQS data logger:") >= 0);
        CHECK(header.indexOf("<title>Test</title>") >= 0);

        String footer = HtmlUtil::htmlFooter();
        CHECK(footer == "</body></html>");

        String escaped = HtmlUtil::htmlEscape("a&b<c>d\"e");
        CHECK(escaped == "a&amp;b&lt;c&gt;d&quot;e");

        // Test with custom logger name
        mockSetLoggerName("MyLogger");
        String header2 = HtmlUtil::htmlHeader("Config");
        CHECK(header2.indexOf("BODAQS data logger: MyLogger") >= 0);

        // Test safePath
        CHECK(HtmlUtil::safePath("file.csv") == true);
        CHECK(HtmlUtil::safePath("") == false);
        CHECK(HtmlUtil::safePath("../etc/passwd") == false);
        CHECK(HtmlUtil::safePath("dir/file") == false);

        // Test safeRelPath
        CHECK(HtmlUtil::safeRelPath("/data/file.csv") == true);
        CHECK(HtmlUtil::safeRelPath("") == false);
        CHECK(HtmlUtil::safeRelPath("data/file.csv") == false);
        CHECK(HtmlUtil::safeRelPath("/../etc") == false);

        // Test normDir
        CHECK(HtmlUtil::normDir("data") == "/data/");
        CHECK(HtmlUtil::normDir("/data/") == "/data/");
        CHECK(HtmlUtil::normDir("/") == "/");

        // Test parentDir
        CHECK(HtmlUtil::parentDir("/data/file.csv") == "/data/");
        CHECK(HtmlUtil::parentDir("/data/") == "/");
        CHECK(HtmlUtil::parentDir("/") == "/");

        // Test contentTypeFor
        CHECK(HtmlUtil::contentTypeFor("test.csv") == "text/csv");
        CHECK(HtmlUtil::contentTypeFor("test.json") == "application/json");
        CHECK(HtmlUtil::contentTypeFor("test.html") == "text/html");
    }
    printf("  passed\n\n");

    printf("%d passed, %d failed\n\n", tests_passed, tests_failed);

    // ── HtmlUtil baseline tests (T01) ──
    printf("Running HtmlUtil baseline tests...\n\n");
    int htmlutil_failed = runHtmlUtilTests();
    tests_failed += htmlutil_failed;

    printf("\n%d passed, %d failed\n", tests_passed, tests_failed);

    // ── Routes_Static tests (T02) ──
    printf("\nRunning Routes_Static tests...\n\n");
    int routes_failed = runRoutesStaticTests();
    tests_failed += routes_failed;

    printf("\n%d passed, %d failed\n", tests_passed, tests_failed);

    // ── Fragments tests (T04) ──
    printf("\nRunning Fragments tests...\n\n");
    int fragments_failed = runFragmentsTests();
    tests_failed += fragments_failed;

    printf("\nRunning BMI270 profile tests...\n\n");
    int bmi270_profile_failed = runBMI270ProfileTests();
    tests_failed += bmi270_profile_failed;

    printf("\nRunning BMI270 FIFO tests...\n\n");
    int bmi270_fifo_failed = runBMI270FifoTests();
    tests_failed += bmi270_fifo_failed;

    printf("\n%d passed, %d failed\n", tests_passed, tests_failed);
    return tests_failed > 0 ? 1 : 0;
}
