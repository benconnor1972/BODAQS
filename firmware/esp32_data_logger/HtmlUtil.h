#pragma once

#include <Arduino.h>   // String, F(), PSTR, etc.
#include <WebServer.h> // WebServer
#include <WiFiClient.h>

namespace HtmlUtil {

  // ---------------------------------------------------------------------------
  // Legacy (heap-building) helpers
  // ---------------------------------------------------------------------------

  // Rendering (legacy)
  String htmlHeader(const String& title);
  String htmlFooter();
  String htmlEscape(const String& in);

  // Content / options
  String contentTypeFor(const String& name);
  void   emitEnumOptions(String& html, const char* choicesCsv, const String& current);
  String normDir(const String& in);         // ensures leading '/', trailing '/' (except root)
  String parentDir(const String& in);       // parent path, always ends with '/', root→"/"

  // Safety
  bool   safePath(const String& name);
  bool   safeRelPath(const String& path);   // allows '/', forbids '..', '\\', '//' etc.

  // ---------------------------------------------------------------------------
  // PROGMEM blocks for header/footer (shared by legacy + raw streaming)
  // ---------------------------------------------------------------------------
  extern const char kHtmlHeadPrefix[] PROGMEM;       // up to and including "<title>"
  extern const char kHtmlHeadMid[] PROGMEM;          // closes title ("</title>")
  extern const char kHtmlStyleAndScript[] PROGMEM;   // <style> + <script> block
  extern const char kHtmlHeadSuffix[] PROGMEM;       // closes head and opens body
  extern const char kHtmlFooter[] PROGMEM;           // "</body></html>"

  // ---------------------------------------------------------------------------
  // Raw-response helpers (bypass WebServer.send()/sendContent())
  // ---------------------------------------------------------------------------

  // Reason phrase for status line (small set; others map to "OK")
  const char* reasonPhrase(int code);

  // Begin a response.
  // If contentLength < 0, we omit Content-Length and use close-delimited body.
  void beginRaw(WebServer& srv, int code,
                const char* contentType,
                int32_t contentLength = -1,
                bool closeConnection = true);

  // Convenience: begin HTML close-delimited response
  inline void beginHtml(WebServer& srv, int code = 200) {
    beginRaw(srv, code, "text/html", -1, true);
  }

  // Write helpers (no heap): RAM / PROGMEM / numbers
  inline void write(WebServer& srv, const char* s)                 { srv.client().print(s); }
  inline void write(WebServer& srv, const String& s)               { srv.client().print(s); }
  inline void writeF(WebServer& srv, const __FlashStringHelper* f) { srv.client().print(f); }
  inline void writeP(WebServer& srv, PGM_P p) {
    srv.client().print(reinterpret_cast<const __FlashStringHelper*>(p));
  }
  inline void writeU32(WebServer& srv, uint32_t v) { srv.client().print(v); }
  inline void writeI32(WebServer& srv, int32_t v)  { srv.client().print(v); }

  // End/close connection
  inline void endRaw(WebServer& srv) { srv.client().stop(); }

  // Send a complete small body (RAM string)
  void sendRaw(WebServer& srv, int code, const char* contentType, const char* body);

  // Send a complete small body (PROGMEM string)
  void sendRaw_P(WebServer& srv, int code, const char* contentType, PGM_P bodyP);

  // 303 redirect helper
  void redirect303(WebServer& srv, const String& location, const char* body = "See Other");

  // Stream HTML-escaped String directly to client (no new String allocation)
  void writeHtmlEscaped(WebServer& srv, const String& in);

  // Stream attribute-escaped String (same escaping, handy semantic alias)
  inline void writeAttrEscaped(WebServer& srv, const String& in) { writeHtmlEscaped(srv, in); }

  // Write the standard header/footer via raw client writes
  void writeHtmlHeader(WebServer& srv, const String& title);
  void writeHtmlFooter(WebServer& srv);

  // ---------------------------------------------------------------------------
  // Low-level HTTP helpers (bypass WebServer::send)
  // ---------------------------------------------------------------------------

  // Generic small plain-text response (e.g. errors).
  template <typename ServerT>
  inline void sendPlainText(
      ServerT& srv,
      int statusCode,
      const __FlashStringHelper* reason,
      const __FlashStringHelper* bodyF
  ) {
    auto client = srv.client();
    if (!client) return;

    String body(bodyF ? String(bodyF) : String(""));

    client.print(F("HTTP/1.1 "));
    client.print(statusCode);
    client.print(' ');
    if (reason) client.print(reason);
    client.print(F("\r\n"));

    client.print(F("Content-Type: text/plain\r\n"));
    client.print(F("Connection: close\r\n"));
    client.print(F("Content-Length: "));
    client.print(body.length());
    client.print(F("\r\n\r\n"));

    if (body.length()) {
      client.print(body);
    }

    client.flush();
    client.stop();
  }

  // 303 redirect with small plain-text body.
  template <typename ServerT>
  inline void sendRedirect303(
      ServerT& srv,
      const String& location,
      const String& body
  ) {
    auto client = srv.client();
    if (!client) return;

    client.print(F("HTTP/1.1 303 See Other\r\n"));
    client.print(F("Location: "));
    client.print(location);
    client.print(F("\r\n"));

    client.print(F("Content-Type: text/plain\r\n"));
    client.print(F("Connection: close\r\n"));
    client.print(F("Content-Length: "));
    client.print(body.length());
    client.print(F("\r\n\r\n"));

    if (body.length()) {
      client.print(body);
    }

    client.flush();
    client.stop();
  }

  // Convenience overload for F("...") bodies.
  template<typename ServerT>
  inline void sendPlainRaw(ServerT& srv,
                           int code,
                           const __FlashStringHelper* contentType,
                           const String& body);

  template<typename ServerT>
  inline void sendJsonRaw(ServerT& srv, int code, const String& json);

  template <typename ServerT>
  inline void sendRedirect303(ServerT& srv, const String& location) {
    srv.sendHeader("Location", location);
    // Minimal body – content doesn't really matter for a redirect.
    srv.send(303, F("text/plain"), F("Saved"));
  }

  // Stream an HTML-escaped version of a String without allocating another String.
  template <typename ServerT>
  inline void sendHtmlEscaped(ServerT& srv, const String& in) {
    char buf[96];
    size_t n = 0;

    auto flush = [&]() {
      if (n) {
        buf[n] = '\0';
        srv.sendContent(buf);
        n = 0;
      }
    };

    for (size_t i = 0; i < in.length(); ++i) {
      const char c = in[i];
      const char* repl = nullptr;

      switch (c) {
        case '&':  repl = "&amp;";  break;
        case '<':  repl = "&lt;";   break;
        case '>':  repl = "&gt;";   break;
        case '"':  repl = "&quot;"; break;
        case '\'': repl = "&#39;";  break;
        default:   repl = nullptr;  break;
      }

      if (repl) {
        flush();
        srv.sendContent(repl);
      } else {
        if (n + 2 >= sizeof(buf)) flush();
        buf[n++] = c;
      }
    }

    flush();
  }

  // Stream the standard HTML header.
  template <typename ServerT>
  inline void sendHtmlHeader(ServerT& srv, const String& title) {
    srv.sendContent_P(kHtmlHeadPrefix);
    sendHtmlEscaped(srv, title);
    srv.sendContent_P(kHtmlHeadMid);
    srv.sendContent_P(kHtmlStyleAndScript);
    srv.sendContent_P(kHtmlHeadSuffix);
  }

  // Stream the standard HTML footer.
  template <typename ServerT>
  inline void sendHtmlFooter(ServerT& srv) {
    srv.sendContent_P(kHtmlFooter);
  }

} // namespace HtmlUtil
