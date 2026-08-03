STEP 00: Create test stubs and Makefile
=======================================

STATUS
------

Status: COMPLETE
Completed: 2025-07-16
Verified by: implement (independent re-run)

DEPENDS ON: nothing

SPEC
----

Set up the host-based test infrastructure before any production code changes. The test suite compiles production source files against stub headers that replace ESP32/Arduino types. This ensures tests run on the developer machine with `g++` and are never compiled into the firmware binary.

The stubs must provide minimal implementations of the ESP32/Arduino types used by `HtmlUtil.cpp` and (later) `Routes_Static.cpp`. The Makefile compiles stubs + production source + test files with host g++, using `-I test/stubs` before `-I src` so stubs take precedence.

Key types to stub:
- `String` — Arduino's String class. Subset needed: `length()`, `c_str()`, `indexOf()`, `substring()`, `+=` (String, const char*, char), `==` (String, const char*), `F()` macro (returns const char*), constructors from `const char*` and `char`, `reserve()`, `remove()`, `trim()`, `endsWith()`, `startsWith()`, `toUpperCase()`, `toLowerCase()`, `toInt()`, `toFloat()`, operator `[]`
- `WebServer` — ESP32 WebServer. Methods: `hasHeader(name)`, `header(name)`, `hasArg(name)`, `arg(name)`, `argName(i)`, `args()`, `send(status, contentType, body)`, `sendHeader(name, value)`, `setContentLength(len)`, `sendContent(body)`, `uri()`, `method()`, `on(uri, method, handler)`. Mock state: `mockSetHeader(name, value)`, `mockSetArg(name, value)`, `mockReset()`, `mockLastStatus`, `mockLastContentType`, `mockLastBody`, `mockHeaders` (map for verifying HX-Redirect, Cache-Control, etc.), `mockInvokeHandler(uri, method)` (invokes a handler previously registered via `on()`)
- `SD_MMC` — SD card. `cardType()`, `open(path)`, `exists(path)`, `remove(path)`, `mkdir(path)`, `rmdir(path)`. Mock: `mockSetFile(path, contents)`, `mockFileExists(path)`, `mockReset()`. `File` class with `isDirectory()`, `size()`, `read()`, `write()`, `close()`, `openNextFile()`, `name()`
- `FirmwareInfo::version()` — returns configurable string, default `"0.4.1"`
- `ConfigManager::get()` — returns `LoggerConfig` with configurable fields (loggerName, wifiApSsid, wifiApPassword, wifiMode, etc.)
- `WiFiManager::status()` — returns `WiFiStatus` with configurable fields (networkUp, ssid, ip, mode)

FILES TO CREATE
---------------

- `firmware/test/stubs/Arduino.h`: String class, F() macro, delay(), millis(), basic types (uint8_t, uint16_t, uint32_t, int8_t, etc.), LOGI_TAG/LOGW_TAG/LOGE_TAG/LOGD_TAG macros (no-ops)
- `firmware/test/stubs/WebServer.h`: WebServer class with mock state, inspection API, `on()` for route registration, and `mockInvokeHandler()` for test-driven handler invocation
- `firmware/test/stubs/SD_MMC.h`: SD_MMC namespace with mock file map, File class
- `firmware/test/stubs/mocks.h`: FirmwareInfo, ConfigManager, WiFiManager stubs with configurable return values and reset functions
- `firmware/test/Makefile`: Compiles stubs + production source + test files with host g++, runs test binary. Targets: `test` (build + run), `clean`. Uses `-std=gnu++2a -I test/stubs -I src`.

FILES TO MODIFY
---------------

None.

TEST CASES
----------

T1: Makefile compiles with no errors
    `make -C test test` exits 0

T2: Stub String class supports basic operations
    String("hello").length() == 5, String("hello") + " world" == "hello world"

T3: Stub WebServer mock state works
    mockSetHeader("HX-Request", "true"); srv.hasHeader("HX-Request") == true; srv.header("HX-Request") == "true"

T4: Stub SD_MMC mock file map works
    mockSetFile("/www/htmx.min.js", "htmxcontent"); SD_MMC.exists("/www/htmx.min.js") == true

VERIFICATION
------------

  cd firmware && make -C test test

Expected output:
  Compiling test binary...
  Running tests...
  All tests passed.

Exit code: 0

DONE WHEN
---------

- `make -C test test` compiles and exits 0
- Stub String, WebServer, SD_MMC, mocks all provide required methods
- Makefile uses `-I test/stubs` before `-I src`
- No files created in `firmware/src/` (test code only in `firmware/test/`)

Notes
-----

Implemented by: implement-task agent
Date: 2025-06-23

Files created (8 total):
- `firmware/test/stubs/Arduino.h` — String class (full subset), F() macro, delay(), millis(), basic types, LOG macros (no-ops with include guards)
- `firmware/test/stubs/WebServer.h` — WebServer class with mock state, HTTPMethod enum, handler registration with wildcard matching, mockInvokeHandler
- `firmware/test/stubs/SD_MMC.h` — SD_MMC namespace with mock file map, File class, card type constants
- `firmware/test/stubs/mocks.h` — Mock state declarations and helper functions (mockSetLoggerName, mockSetNetworkUp, etc.)
- `firmware/test/stubs/mocks.cpp` — Implementations of ConfigManager::get(), ConfigManager::wifiModeLabel(), WiFiManager::status() (not in FILES TO CREATE but required for linking)
- `firmware/test/stubs/WiFi.h` — wl_status_t enum, IPAddress class (not in FILES TO CREATE but required by WiFiManager.h which includes <WiFi.h>)
- `firmware/test/Makefile` — Build system with -std=gnu++2a, -I stubs before -I ../src
- `firmware/test/test_main.cpp` — Test entry point with 79 assertions covering T2-T5

Additional files beyond FILES TO CREATE:
- `mocks.cpp` — Required because ConfigManager::get(), ConfigManager::wifiModeLabel(), and WiFiManager::status() are declared in real headers (included via quote includes from src/) but implemented in ConfigManager.cpp/WiFiManager.cpp which are not compiled in the test build. Without these implementations, the linker would fail.
- `WiFi.h` — Required because WiFiManager.h includes <WiFi.h> (angle bracket include) for wl_status_t and IPAddress types. Without this stub, the compiler can't find <WiFi.h>.
- `test_main.cpp` — Required as the test binary entry point.

Key design decisions:
1. Real headers (ConfigManager.h, WiFiManager.h, SensorTypes.h, etc.) are used as-is because they're included with quote includes from src/ files, so the compiler finds them in src/ before checking -I paths. The stubs only shadow angle-bracket includes (<Arduino.h>, <WiFi.h>, <WebServer.h>, <SD_MMC.h>).
2. The String class is a complete reimplementation using malloc/realloc/free, not std::string, to match Arduino String semantics (mutable, c_str() returns internal buffer).
3. Mock state uses C++17 inline variables for header-only stubs (WebServer.h, SD_MMC.h), avoiding the need for separate .cpp files for those stubs.
4. FirmwareInfo::version() is provided via -DBODAQS_FW_VERSION="0.4.1" in the Makefile (compile-time, matching the real FirmwareInfo.h which returns the macro). Runtime configurability is provided via mockSetVersion()/mockGetVersion() in mocks.h for future test use, but FirmwareInfo::version() itself returns the compile-time macro value.
5. The Makefile uses single-quote wrapping for -D flags: '-DBODAQS_FW_VERSION="0.4.1"' to avoid shell escaping issues with backslash-quotes.

Verification result:
  cd firmware && make -C test test
  → 79 passed, 0 failed, exit code 0
