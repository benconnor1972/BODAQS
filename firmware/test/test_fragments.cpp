// ─────────────────────────────────────────────────────────────────
// test_fragments.cpp — Fragment response format tests
//
// Tests (5 total):
//   T1: Success fragment format
//   T2: Error fragment format
//   T3: Warning fragment format
//   T4: No HTML wrapper in fragments
//   T5: Fragment size under 2KB
// ─────────────────────────────────────────────────────────────────

#include <cstdio>
#include <cstring>
#include "Arduino.h"
#include "WebServer.h"
#include "mocks.h"
#include "HtmlUtil.h"

// Called from test_main.cpp's main(). Returns number of failures.
int runFragmentsTests() {
    int passed = 0;
    int failed = 0;

    auto check = [&](bool cond, const char* desc) {
        if (cond) {
            passed++;
        } else {
            printf("    FAIL: test_fragments: %s\n", desc);
            failed++;
        }
    };

    mockResetAll();
    mockReset();

    // ── T1: Success fragment format ──
    printf("T1: Success fragment format\n");
    {
        String frag = HtmlUtil::htmlFragment("<div class='alert-ok'>Configuration saved.</div>");
        check(frag == "<div class='alert-ok'>Configuration saved.</div>",
              "success fragment is exactly the alert-ok div");
    }
    printf("  passed\n\n");

    // ── T2: Error fragment format ──
    printf("T2: Error fragment format\n");
    {
        String frag = HtmlUtil::htmlFragment("<div class='alert-err'>Error: Invalid input</div>");
        check(frag == "<div class='alert-err'>Error: Invalid input</div>",
              "error fragment is exactly the alert-err div");
    }
    printf("  passed\n\n");

    // ── T3: Warning fragment format ──
    printf("T3: Warning fragment format\n");
    {
        String frag = HtmlUtil::htmlFragment("<div class='alert-warn'>Configuration is locked while logging is active.</div>");
        check(frag == "<div class='alert-warn'>Configuration is locked while logging is active.</div>",
              "warning fragment is exactly the alert-warn div");
    }
    printf("  passed\n\n");

    // ── T4: No HTML wrapper in fragments ──
    printf("T4: No HTML wrapper in fragments\n");
    {
        String frags[3];
        frags[0] = HtmlUtil::htmlFragment("<div class='alert-ok'>Configuration saved.</div>");
        frags[1] = HtmlUtil::htmlFragment("<div class='alert-err'>Error: Invalid input</div>");
        frags[2] = HtmlUtil::htmlFragment("<div class='alert-warn'>Configuration is locked while logging is active.</div>");

        bool noWrapper = true;
        for (int i = 0; i < 3; ++i) {
            if (frags[i].indexOf("<html>") >= 0)  { noWrapper = false; break; }
            if (frags[i].indexOf("<head>") >= 0)  { noWrapper = false; break; }
            if (frags[i].indexOf("<body>") >= 0)  { noWrapper = false; break; }
            if (frags[i].indexOf("<script") >= 0) { noWrapper = false; break; }
            if (frags[i].indexOf("<link") >= 0)   { noWrapper = false; break; }
        }
        check(noWrapper, "no fragment contains <html>, <head>, <body>, <script>, or <link>");
    }
    printf("  passed\n\n");

    // ── T5: Fragment size under 2KB ──
    printf("T5: Fragment size under 2KB\n");
    {
        String frags[3];
        frags[0] = HtmlUtil::htmlFragment("<div class='alert-ok'>Configuration saved.</div>");
        frags[1] = HtmlUtil::htmlFragment("<div class='alert-err'>Error: Invalid input</div>");
        frags[2] = HtmlUtil::htmlFragment("<div class='alert-warn'>Configuration is locked while logging is active.</div>");

        bool allUnder2KB = true;
        for (int i = 0; i < 3; ++i) {
            if (frags[i].length() >= 2048) { allUnder2KB = false; break; }
        }
        check(allUnder2KB, "all fragment strings are < 2048 bytes");
    }
    printf("  passed\n\n");

    printf("test_fragments: %d tests passed", passed);
    if (failed > 0) printf(", %d failed", failed);
    printf("\n");

    return failed;
}
