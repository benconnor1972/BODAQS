STEP 01: Write initial HtmlUtil tests
=====================================

STATUS
------

Status: COMPLETE
Completed: 2025-07-16
Verified by: implement (independent re-run)

DEPENDS ON: step 00

SPEC
----

Write tests against the current (unmodified) `HtmlUtil.cpp` to establish a baseline. These tests verify the existing behavior of `htmlHeader()`, `htmlFooter()`, and `htmlEscape()` so that when we modify `htmlHeader()` in T03, we can verify what changed.

The tests must pass against the CURRENT unmodified `HtmlUtil.cpp`. This means the stubs must provide enough of `ConfigManager` and `WiFiManager` for `htmlHeader()` to compile and produce output.

Current `htmlHeader()` behavior to test:
- Output contains `<!DOCTYPE html><html><head>`
- Output contains `<title>` with the title argument
- Output contains `<style>` block (inline CSS — this will be removed in T03)
- Output contains `BODAQS data logger:` in titlebar
- Output contains `Files`, `General`, `Sensors` nav links
- Output contains `Network:` in netbar
- `htmlFooter()` returns `</body></html>`
- `htmlEscape()` escapes `&`, `<`, `>`, `"`

FILES TO CREATE
---------------

- `firmware/test/test_htmlutil.cpp`: Initial tests against current HtmlUtil — htmlHeader structure, titlebar, navbar, netbar, htmlFooter, htmlEscape

FILES TO MODIFY
---------------

- `firmware/test/Makefile`: Add `test_htmlutil.cpp` to test source list (if not already globbing)

TEST CASES
----------

T1: htmlHeader contains DOCTYPE and html tag
    Output starts with `<!DOCTYPE html><html><head>`

T2: htmlHeader contains title
    htmlHeader("Config") output contains `<title>Config</title>`

T3: htmlHeader contains titlebar with logger name
    Output contains `BODAQS data logger:` (or configured logger name)

T4: htmlHeader contains nav links
    Output contains `href='/files'`, `href='/config'`, `href='/config/sensors'`

T5: htmlHeader contains netbar
    Output contains `Network:`

T6: htmlFooter returns closing tags
    htmlFooter() returns exactly `</body></html>`

T7: htmlEscape escapes special characters
    htmlEscape("a&b<c>d\"e") returns `a&amp;b&lt;c&gt;d&quot;e`

T8: htmlEscape passes through normal characters
    htmlEscape("hello world") returns `hello world`

VERIFICATION
------------

  cd firmware && make -C test test

Expected output:
  Running tests...
  test_htmlutil: 8 tests passed
  All tests passed.

Exit code: 0

DONE WHEN
---------

- All 8 tests pass against current unmodified `HtmlUtil.cpp`
- `make -C test test` exits 0
- Tests verify existing behavior that will be changed in T03

Notes
-----

- Created `firmware/test/test_htmlutil.cpp` with `runHtmlUtilTests()` function
  containing 8 test cases (10 assertions total — T4 has 3 sub-checks for the
  three nav links).
- Modified `firmware/test/test_main.cpp` to declare and call
  `runHtmlUtilTests()` from `main()`. The Makefile already auto-discovers
  `test_*.cpp` files via `$(wildcard test_*.cpp)`, so no Makefile change was
  needed.
- All tests pass against the current unmodified `HtmlUtil.cpp` (exit code 0).
- The current `htmlHeader()` output includes a `<style>` block with inline CSS
  and dead JavaScript code (a standalone string literal not appended to `s`).
  The tests do NOT assert the presence or absence of `<style>` — they only
  test the 8 cases listed in TEST CASES. T03 will add tests for CSS removal.
