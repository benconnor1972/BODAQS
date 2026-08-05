# Review Report: htmx Web UI Migration

**Date**: 2025-06-23
**Status**: PASS (after remediation — B1, W1-W12 fixed)

## Summary

The spec artifacts are well-structured and internally consistent across most dimensions: all 5 invariants trace from design doc through spec, plan, tasks, and verification; all 9 tasks form a clean dependency chain (T00→T08); all 45 acceptance criteria have verification rows; all 13 validation rules and 9 error specs are covered. However, one blocking issue prevents a PASS: the spec returns HTTP 423 for htmx config-lock responses, but htmx v2.0 does not swap response bodies for 4xx status codes by default. The code path trace (Path 4) claims "htmx swaps warn fragment into #save-result" on a 423 response — this will not happen. The user will see no lock feedback. The spec is internally inconsistent on this point: 409 mutation-blocked responses return 200 for htmx (which swaps), but 423 lock responses return 423 for htmx (which does not swap). Twelve non-blocking warnings are also documented below.

## Traceability Matrix

| Design Doc Element | Spec Reference | Plan Phase | Task(s) | Verification |
|---|---|---|---|---|
| INV-1 (no-JS fallback) | Spec: Design Context → Relevant Invariants | Plan: Rule 4 | T05, T06, T07 (DONE WHEN: non-htmx returns 303) | verification.md §3 INV-1; Integration Tests 24, 27 |
| INV-2 (1-year cache + ?v=) | Spec: Design Context → Relevant Invariants | Plan: Rule 8 | T02 (cache header), T03 (?v= in tags) | verification.md §3 INV-2; Unit tests 19, 20, 21, 30; Integration Test 25 |
| INV-3 (2 KB chunked, no full-body heap) | Spec: Design Context → Relevant Invariants | Plan: Rule 5 | T04 (fragment size test) | verification.md §3 INV-3; Unit tests 12, 13 |
| INV-4 (config lock 423 for htmx) | Spec: Design Context → Relevant Invariants | Plan: Rule 6 | T05, T06, T07 (423 .alert-warn fragment) | verification.md §3 INV-4; Integration Tests 9, 10 |
| INV-5 (hx-sync, one request at a time) | Spec: Design Context → Relevant Invariants | Plan: Rule 7 | T05, T06, T07 (hx-sync on forms) | verification.md §3 INV-5; Code review |
| Contract: Static Asset Server | Spec: Component Specs → Static Asset Server | Plan: Phase 1 | T02 (create), T04 (register) | verification.md §1 Static AC1–AC7 |
| Contract: Fragment Responder | Spec: Component Specs → Fragment Responder | Plan: Phase 1 | T03 (isHtmxRequest, htmlFragment, htmlRespond) | verification.md §1 Fragment AC1–AC6 |
| Contract: HtmlUtil (modified) | Spec: Component Specs → HtmlUtil | Plan: Phase 1 | T03 (htmlHeader changes) | verification.md §1 HtmlUtil AC1–AC6 |
| Contract: Route Handlers (Config) | Spec: Component Specs → Config Page | Plan: Phase 2–3 | T05 (config), T06 (sensors) | verification.md §1 Config AC1–AC13 |
| Contract: Route Handlers (Files) | Spec: Component Specs → Files Page | Plan: Phase 4 | T07 (HX-Redirect) | verification.md §1 Files AC1–AC8 |
| Contract: WebServerManager | Spec: Component Specs → WebServerManager | Plan: Phase 1 | T04 (registerStaticRoutes) | verification.md §1 WebServerManager AC1–AC2 |
| Failure: SD card absent | Spec: Design Context → Failure Modes | Plan: Rule 4 (degrade) | T02 (test_static_no_sd_card), T04 | verification.md §9 Edge Case 1; Integration Test 27 |
| Failure: htmx.js fails to load | Spec: Design Context → Failure Modes | Plan: Rule 4 (degrade) | — (browser-side, no task) | verification.md §9 Edge Case 2 |
| Failure: Fragment too large | Spec: Design Context → Failure Modes | Plan: Rule 5 | T04 (test_fragment_size_under_2kb) | verification.md §9 Edge Case 5 |
| Failure: Overlapping requests | Spec: Design Context → Failure Modes | Plan: Rule 7 | T05, T06, T07 (hx-sync) | verification.md §9 Edge Case 3 |
| Failure: Config lock during htmx | Spec: Design Context → Failure Modes | Plan: Rule 6 | T05, T06, T07 (423 .alert-warn) | verification.md §9 Edge Case 4; Integration Tests 9, 10 |
| Goal G1 (no page reload) | Spec: Success Criteria G1 | Plan: Phase 2–3 | T05, T06 | verification.md §4 G1; Integration Test 23 |
| Goal G2 (assets cached) | Spec: Success Criteria G2 | Plan: Phase 1 | T02, T04 | verification.md §4 G2; Integration Test 25 |
| Goal G3 (graceful degradation) | Spec: Success Criteria G3 | Plan: Rule 4 | T05 | verification.md §4 G3; Integration Test 24 |
| Goal G4 (no memory regression) | Spec: Success Criteria G4 | Plan: (no explicit gate) | — (integration only) | verification.md §4 G4; Integration Test 28 |
| Goal G5 (flash < 20 KB) | Spec: Success Criteria G5 | Plan: Quality Gates | T04 (< 5 KB), T08 (< 20 KB total) | verification.md §4 G5; Quality gates |
| Goal G6 (mobile responsive) | Spec: Success Criteria G6 | Plan: Phase 5 | T08 | verification.md §4 G6; Integration Test 26 |

## Issues Found

### Blocking Issues

#### B1: HTTP 423 responses will not be swapped by htmx v2.0 — config lock feedback invisible to user

**Where:** Spec § Key Decisions ("423 preserved for lock state"), Spec § Error Specs (Config Page 423 Locked), verification.md §7 Path 4, plan.md Rule 6, tasks T05/T06/T07.

**The problem:**

htmx v2.0 default response handling does not swap response bodies for 4xx status codes. The default `htmx.config.responseHandling` array specifies `{code: "[45]..", swap: false, error: true}` — meaning 400–499 responses fire `htmx:responseError` and do **not** swap content into the target element.

The spec returns 423 for htmx config-lock responses:

> htmx response: 423, `text/html`, `<div class='alert-warn'>Configuration is locked while <reason>.</div>`

The code path trace (verification.md §7, Path 4) claims:

> Browser (htmx swaps warn fragment into #save-result)

This will not happen. The browser receives the 423 response with the HTML fragment body, but htmx discards it and fires `htmx:responseError`. The `#save-result` div remains empty. The user sees no lock message.

**Internal inconsistency:**

The spec handles 409 mutation-blocked (files page) by returning **200** for htmx — which does swap. But 423 config-lock returns **423** for htmx — which does not swap. The spec's key decision says "423 preserved for lock state to match non-htmx semantics," but the non-htmx 423 response is `text/plain` while the htmx 423 response is `text/html` with a different body format. The responses are already different — preserving only the status code gains nothing semantic while breaking the UX.

**Fix options (pick one):**

1. **Return 200 for htmx 423 lock responses** (recommended — consistent with 409 handling). Update spec error specs, verification.md Path 4, plan Rule 6, and tasks T05/T06/T07 to use `sendText(srv, 200, ...)` instead of `sendText(srv, 423, ...)`.
2. **Add htmx configuration to swap on 423.** Add a `<script>` tag or inline config that extends `htmx.config.responseHandling` to swap on 423. This adds complexity and is not mentioned anywhere in the spec.

**Impact if not fixed:** Users who save config while logging is active will see no feedback. The form will appear to do nothing. This breaks INV-4's intent ("htmx requests receive the same 423 locked response") — the user doesn't receive anything visible.

### Warnings

#### W1: Design doc has Cache-Control typo (max-age=86400 vs 31536000)

**Where:** Design doc, Static Asset Server contract, Contract shape section.

The contract shape says `Cache-Control: max-age=86400` (1 day). The behavioral guarantees section, INV-2, the spec, the plan, all tasks, and all verification rows say `max-age=31536000` (1 year). The 86400 value is a typo. All downstream artifacts use the correct value, so this is cosmetic — but the design doc should be fixed to avoid confusion.

#### W2: htmlFragment signature differs between design doc and spec

**Where:** Design doc Fragment Responder contract vs spec Fragment Responder interface.

The design doc says `String htmlFragment(const String& title, const String& body)`. The spec says `String htmlFragment(const String& body)`. The spec's version is simpler (fragments don't need a title — htmx swaps innerHTML). T03 implements the spec's version. The design doc should be updated to match.

#### W3: htmlFullPage defined in design doc but absent from spec

**Where:** Design doc Fragment Responder contract vs spec Fragment Responder interface.

The design doc defines `String htmlFullPage(const String& title, const String& body)`. The spec replaces this with `String htmlRespond(WebServer& srv, const String& title, const String& body)` — a convenience function that auto-detects htmx vs non-htmx. `htmlRespond` is more useful but is not in the design doc. The design doc should be updated.

#### W4: htmlFooter and htmlEscape lose test coverage after T03

**Where:** T01 creates tests for htmlFooter and htmlEscape. T03 rewrites test_htmlutil.cpp with 13 tests that omit them. verification.md HtmlUtil AC5 references `test_htmlFooter_returns_closing_tags (from T01 baseline)` but this test is not in the final 30-test count.

T01 establishes 8 baseline tests. T03 replaces the file with 13 tests. The 5 tests dropped are: DOCTYPE structure, title tag, `<style>` block (correctly removed), netbar, htmlFooter, htmlEscape (2 tests). Of these, htmlFooter and htmlEscape are unchanged by T03 and should retain coverage. Either keep them in the final 13 (making it 15), or document that they are baseline-only and accept the coverage gap.

#### W5: T00 WebServer stub missing `on()` method

**Where:** T00 stub specification vs T02 test requirements.

T00 lists WebServer stub methods: `hasHeader`, `header`, `hasArg`, `arg`, `argName`, `args`, `send`, `sendHeader`, `setContentLength`, `sendContent`, `uri`, `method`. It does not list `on(uri, method, handler)`.

T02's `registerStaticRoutes` calls `srv.on("/static/*", ...)` to register the route handler. The test needs to invoke this handler to verify behavior. The stub must provide `on()` and a mechanism to invoke registered handlers (e.g., `mockInvokeHandler(uri, method)`).

Without `on()` in the stub, T02's tests cannot compile or run.

#### W6: T04 htmx.min.js location inconsistent

**Where:** T04 SPEC text vs T04 FILES TO CREATE.

T04 SPEC says: "Place it at the project root for copying to SD cards." T04 FILES TO CREATE says: `firmware/www/htmx.min.js`. The FILES TO CREATE path is correct. The SPEC text should say `firmware/www/`.

#### W7: Spec research claim about HX-Request header collection is likely wrong

**Where:** Spec § Research, "ESP32 WebServer header access."

The spec says: "HX-Request does not need pre-collection since hasHeader/header work on any received header."

The ESP32 WebServer's `collectHeaders()` function tells the server which headers to parse and store. `hasHeader()` only returns true for headers in the collected list. The current code collects only `Range`:

```cpp
static const char* kHeaderKeys[] = { "Range" };
g_server->collectHeaders(kHeaderKeys, sizeof(kHeaderKeys) / sizeof(kHeaderKeys[0]));
```

Source code confirms this (WebServerManager.cpp, `prepareServer_()`). `srv.hasHeader("HX-Request")` will likely return false even when the header is present, because "HX-Request" is not in `kHeaderKeys`.

Plan Rule 12 and T04 both hedge with "if needed, add to kHeaderKeys." This is correct — but the spec research claim is misleading. It should say "HX-Request must be added to kHeaderKeys" or at minimum "test early; likely needs collection."

#### W8: T08 test cases are not automated

**Where:** T08 TEST CASES (T1–T7) vs T08 VERIFICATION command.

T08's test cases check that `app.css` contains specific strings (`--shadow-grey: #212227`, `@media (max-width: 480px)`, `.htmx-indicator`, etc.). These are described as manual file content checks. The VERIFICATION command (`make -C test test && pio run`) runs the existing 30 unit tests and the build — it does not verify T08's test cases.

These checks could be automated with a simple test that reads `firmware/www/app.css` and asserts content. Alternatively, document that T08's tests are manual verification only.

#### W9: htmx version not pinned to a specific release

**Where:** Spec, plan, tasks — all say "v2.0.x."

The spec's risk mitigation says "Pin htmx version on SD card" but doesn't specify which version. htmx 2.0.0, 2.0.1, 2.0.2, and 2.0.3 may have behavior differences. T04 says "Download from unpkg.com" without specifying a versioned URL. The download URL should be pinned (e.g., `https://unpkg.com/htmx.org@2.0.3/dist/htmx.min.js`).

#### W10: G4 (memory envelope) not in any task DONE WHEN

**Where:** Spec Success Criteria G4, verification.md §4 G4 / Integration Test 28.

G4 requires `ESP.getFreeHeap()` before and after config page load to be within ±2 KB of baseline. Verification.md maps this to Integration Test 28 (manual, on hardware). No task's DONE WHEN or TEST CASES mentions heap measurement. Since this is a hardware integration test, it can't be in a unit test — but a task should explicitly call it out as a manual verification step.

#### W11: Dead JavaScript code in htmlHeader() not addressed

**Where:** `firmware/src/HtmlUtil.cpp`, `htmlHeader()` function.

The current `htmlHeader()` contains a block of JavaScript (functions `populateSelect`, `loadTransforms`, and a `DOMContentLoaded` listener) that is dead code — it is a standalone string expression statement, not concatenated to the output string `s`. This is a pre-existing bug.

T03 says "Remove the entire `<style>...</style>` block" but does not mention the dead JavaScript. After T03, the dead code will remain between the new `<script>`/`<link>` tags and `</head>`. It is harmless (dead code does nothing), but T03 should clean it up while modifying the function.

#### W12: Spec size estimates for inline CSS are inaccurate

**Where:** T03 SPEC ("currently ~3 KB of inline CSS"), spec HtmlUtil Performance Constraints ("reduced from current ~3 KB").

The actual inline CSS in `htmlHeader()` is approximately 1 KB (measured from source). The entire `htmlHeader()` output is approximately 1.5–2 KB. The "3 KB" estimate is high by a factor of 3. This doesn't affect acceptance criteria (which use binary size delta, not CSS size), but the estimate should be corrected for accuracy.

## Coverage Summary

| Category | Covered | Total | Status |
|----------|---------|-------|--------|
| Invariants | 5 | 5 | ✓ |
| Contracts | 6 | 6 | ✓ |
| Failure modes | 5 | 5 | ✓ |
| Goals | 6 | 6 | ✓ |
| ACs | 45 | 45 | ✓ |
| Validation rules | 13 | 13 | ✓ |
| Error specs | 9 | 9 | ✓ |
| Success criteria | 13 | 13 | ✓ |
| Tasks with tests | 9 | 9 | ✓ |
| Dependencies valid | 9 | 9 | ✓ |

## Recommendations

### Must fix before implementation

1. **Fix B1 (423 swap issue).** Change htmx config-lock responses from 423 to 200. Update:
   - Spec § Error Specs (Config Page 423 Locked): htmx response → 200, `text/html`
   - Spec § Key Decisions: remove "except 423 lock" exception
   - verification.md §7 Path 4: change `sendText(srv, 423, ...)` to `sendText(srv, 200, ...)`
   - verification.md §1 Config AC4: change "then 423" to "then 200"
   - verification.md §2 E2: change htmx response from 423 to 200
   - verification.md §6 Test 9: change expected status from 423 to 200
   - plan.md Rule 6: update 423 reference
   - tasks T05, T06, T07: update code examples from `sendText(srv, 423, ...)` to `sendText(srv, 200, ...)`

### Should fix before implementation

2. **Fix W5 (T00 WebServer stub).** Add `on(uri, method, handler)` and `mockInvokeHandler(uri, method)` to the T00 stub specification. Without this, T02's tests cannot compile.

3. **Fix W7 (HX-Request collection).** Update spec research to state that `HX-Request` must be added to `kHeaderKeys`. Update T04 to add it unconditionally rather than conditionally.

4. **Fix W4 (htmlFooter/htmlEscape coverage).** Either retain htmlFooter and htmlEscape tests in the final 13 (making it 15), or document the coverage gap explicitly.

### Should fix but non-blocking

5. Fix W1 (design doc Cache-Control typo: 86400 → 31536000).
6. Fix W2/W3 (design doc htmlFragment/htmlFullPage signatures to match spec).
7. Fix W6 (T04 htmx.min.js location: "project root" → "firmware/www/").
8. Fix W9 (pin htmx version: "v2.0.x" → specific version like "2.0.3").
9. Fix W11 (T03: remove dead JavaScript from htmlHeader).
10. Fix W12 (correct CSS size estimate from ~3 KB to ~1 KB).
11. Address W8 (automate T08 CSS content checks or document as manual).
12. Address W10 (add G4 heap check to a task's DONE WHEN as manual verification).
