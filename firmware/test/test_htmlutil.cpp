// ─────────────────────────────────────────────────────────────────
// test_htmlutil.cpp — HtmlUtil tests for htmx Web UI migration
//
// Tests (15 total):
//   T1:  htmlHeader includes htmx script with version
//   T2:  htmlHeader includes app.css link with version
//   T3:  htmlHeader does NOT contain inline style
//   T4:  htmlHeader still includes navbar
//   T5:  htmlHeader still includes titlebar
//   T6:  htmlFragment returns body only
//   T7:  htmlFragment has no html wrapper
//   T8:  isHtmxRequest true
//   T9:  isHtmxRequest false when absent
//   T10: isHtmxRequest false when other value
//   T11: htmlRespond fragment mode
//   T12: htmlRespond full page mode
//   T13: Version changes with firmware
//   T14: htmlFooter returns closing tags (retained from baseline)
//   T15: htmlEscape escapes special characters (retained from baseline)
// ─────────────────────────────────────────────────────────────────

#include <cstdio>
#include "Arduino.h"
#include "WebServer.h"
#include "mocks.h"
#include "HtmlUtil.h"

// Called from test_main.cpp's main(). Returns number of failures.
int runHtmlUtilTests() {
    int passed = 0;
    int failed = 0;

    auto check = [&](bool cond, const char* desc) {
        if (cond) {
            passed++;
        } else {
            printf("    FAIL: test_htmlutil: %s\n", desc);
            failed++;
        }
    };

    mockResetAll();
    mockReset();

    // ── T1: htmlHeader includes htmx script with version ──
    printf("T1: htmlHeader includes htmx script with version\n");
    {
        String h = HtmlUtil::htmlHeader("Config");
        check(h.indexOf("<script src='/static/htmx.min.js?v=0.4.1' defer></script>") >= 0,
              "htmlHeader contains htmx script tag with version");
    }
    printf("  passed\n\n");

    // ── T2: htmlHeader includes app.css link with version ──
    printf("T2: htmlHeader includes app.css link with version\n");
    {
        String h = HtmlUtil::htmlHeader("Config");
        check(h.indexOf("<link rel='stylesheet' href='/static/app.css?v=0.4.1'>") >= 0,
              "htmlHeader contains app.css link tag with version");
    }
    printf("  passed\n\n");

    // ── T3: htmlHeader does NOT contain inline style ──
    printf("T3: htmlHeader does NOT contain inline style\n");
    {
        String h = HtmlUtil::htmlHeader("Config");
        check(h.indexOf("<style>") < 0,
              "htmlHeader does not contain <style>");
    }
    printf("  passed\n\n");

    // ── T4: htmlHeader still includes navbar ──
    printf("T4: htmlHeader still includes navbar\n");
    {
        String h = HtmlUtil::htmlHeader("Config");
        check(h.indexOf("href='/files'") >= 0 &&
              h.indexOf("href='/config'") >= 0 &&
              h.indexOf("href='/config/sensors'") >= 0,
              "htmlHeader contains Files, General, Sensors nav links");
    }
    printf("  passed\n\n");

    // ── T5: htmlHeader still includes titlebar ──
    printf("T5: htmlHeader still includes titlebar\n");
    {
        String h = HtmlUtil::htmlHeader("Config");
        check(h.indexOf("BODAQS data logger:") >= 0,
              "htmlHeader contains 'BODAQS data logger:'");
    }
    printf("  passed\n\n");

    // ── T6: htmlFragment returns body only ──
    printf("T6: htmlFragment returns body only\n");
    {
        String frag = HtmlUtil::htmlFragment("<p>Saved.</p>");
        check(frag == "<p>Saved.</p>",
              "htmlFragment returns body exactly");
    }
    printf("  passed\n\n");

    // ── T7: htmlFragment has no html wrapper ──
    printf("T7: htmlFragment has no html wrapper\n");
    {
        String frag = HtmlUtil::htmlFragment("<div>test</div>");
        check(frag.indexOf("<html>") < 0 &&
              frag.indexOf("<head>") < 0 &&
              frag.indexOf("<script") < 0 &&
              frag.indexOf("<link") < 0,
              "htmlFragment has no html/head/script/link tags");
    }
    printf("  passed\n\n");

    // ── T8: isHtmxRequest true ──
    printf("T8: isHtmxRequest true\n");
    {
        mockReset();
        WebServer srv(80);
        mockSetHeader("HX-Request", "true");
        check(HtmlUtil::isHtmxRequest(srv) == true,
              "isHtmxRequest returns true for HX-Request: true");
    }
    printf("  passed\n\n");

    // ── T9: isHtmxRequest false when absent ──
    printf("T9: isHtmxRequest false when absent\n");
    {
        mockReset();
        WebServer srv(80);
        check(HtmlUtil::isHtmxRequest(srv) == false,
              "isHtmxRequest returns false when header absent");
    }
    printf("  passed\n\n");

    // ── T10: isHtmxRequest false when other value ──
    printf("T10: isHtmxRequest false when other value\n");
    {
        mockReset();
        WebServer srv(80);
        mockSetHeader("HX-Request", "false");
        check(HtmlUtil::isHtmxRequest(srv) == false,
              "isHtmxRequest returns false for HX-Request: false");
    }
    printf("  passed\n\n");

    // ── T11: htmlRespond fragment mode ──
    printf("T11: htmlRespond fragment mode\n");
    {
        mockReset();
        WebServer srv(80);
        mockSetHeader("HX-Request", "true");
        String result = HtmlUtil::htmlRespond(srv, "Config", "<p>Saved.</p>");
        check(result.indexOf("<html>") < 0 && result.indexOf("<p>Saved.</p>") >= 0,
              "htmlRespond returns fragment (no <html>) for htmx request");
    }
    printf("  passed\n\n");

    // ── T12: htmlRespond full page mode ──
    printf("T12: htmlRespond full page mode\n");
    {
        mockReset();
        WebServer srv(80);
        // No HX-Request header → non-htmx
        String result = HtmlUtil::htmlRespond(srv, "Config", "<p>Saved.</p>");
        check(result.indexOf("<html>") >= 0 &&
              result.indexOf("<script") >= 0 &&
              result.indexOf("<link") >= 0 &&
              result.indexOf("<p>Saved.</p>") >= 0,
              "htmlRespond returns full page with <html>, <script>, <link> for non-htmx");
    }
    printf("  passed\n\n");

    // ── T13: Version changes with firmware ──
    printf("T13: Version changes with firmware\n");
    {
        mockSetVersion("0.5.0");
        String h = HtmlUtil::htmlHeader("Config");
        check(h.indexOf("?v=0.5.0") >= 0,
              "htmlHeader contains ?v=0.5.0 when version is 0.5.0");
        mockSetVersion(MOCK_DEFAULT_VERSION);  // reset
    }
    printf("  passed\n\n");

    // ── T14: htmlFooter returns closing tags (retained from baseline) ──
    printf("T14: htmlFooter returns closing tags\n");
    {
        String f = HtmlUtil::htmlFooter();
        check(f == "</body></html>",
              "htmlFooter returns exactly </body></html>");
    }
    printf("  passed\n\n");

    // ── T15: htmlEscape escapes special characters (retained from baseline) ──
    printf("T15: htmlEscape escapes special characters\n");
    {
        String e = HtmlUtil::htmlEscape("a&b<c>d\"e");
        check(e == "a&amp;b&lt;c&gt;d&quot;e",
              "htmlEscape escapes & < > \" correctly");
    }
    printf("  passed\n\n");

    printf("test_htmlutil: %d tests passed", passed);
    if (failed > 0) printf(", %d failed", failed);
    printf("\n");

    return failed;
}
