#include "HtmlUtil.h"

namespace HtmlUtil {

  // ---------------------------------------------------------------------------
  // Legacy helpers (String-building)
  // ---------------------------------------------------------------------------

  void emitEnumOptions(String& html, const char* choicesCsv, const String& current) {
    String choices(choicesCsv ? choicesCsv : "");
    int start = 0;
    while (true) {
      int comma = choices.indexOf(',', start);
      String opt = (comma >= 0) ? choices.substring(start, comma) : choices.substring(start);
      opt.trim();
      if (opt.length()) {
        html += "<option value='"; html += opt; html += "'";
        if (opt.equalsIgnoreCase(current)) html += " selected";
        html += ">"; html += opt; html += "</option>";
      }
      if (comma < 0) break;
      start = comma + 1;
    }
  }

  String contentTypeFor(const String& name) {
    String n = name; n.toLowerCase();
    if (n.endsWith(".csv"))  return F("text/csv");
    if (n.endsWith(".txt"))  return F("text/plain");
    if (n.endsWith(".json")) return F("application/json");
    if (n.endsWith(".htm") || n.endsWith(".html")) return F("text/html");
    return F("application/octet-stream");
  }

  // NOTE: Legacy: allocates a large String.
  String htmlHeader(const String& title) {
    String s;
    s.reserve(1024); // rough minimum; still heap

    s += FPSTR(kHtmlHeadPrefix);
    s += title;
    s += FPSTR(kHtmlHeadMid);
    s += FPSTR(kHtmlStyleAndScript);
    s += FPSTR(kHtmlHeadSuffix);
    return s;
  }

  String htmlFooter() {
    return FPSTR(kHtmlFooter);
  }

  String htmlEscape(const String& in) {
    String out;
    out.reserve(in.length() + 8);
    for (size_t i = 0; i < in.length(); ++i) {
      char c = in[i];
      if      (c == '&')   out += F("&amp;");
      else if (c == '<')   out += F("&lt;");
      else if (c == '>')   out += F("&gt;");
      else if (c == '"')   out += F("&quot;");
      else if (c == '\'')  out += F("&#39;");
      else out += c;
    }
    return out;
  }

  bool safePath(const String& name) {
    if (name.length() == 0) return false;
    if (name.indexOf("..") >= 0) return false;
    if (name.indexOf('/') >= 0 || name.indexOf((char)0x5C) >= 0) return false;
    return true;
  }

  bool safeRelPath(const String& p) {
    if (!p.length()) return false;
    if (p[0] != '/') return false;
    if (p.indexOf("..") >= 0) return false;
    if (p.indexOf((char)0x5C) >= 0) return false; // backslash
    if (p.indexOf("//") >= 0) return false;
    return true;
  }

  String normDir(const String& in) {
    String p = in;
    if (!p.length() || p[0] != '/') p = "/" + p;
    while (p.endsWith("/") && p.length() > 1) p.remove(p.length() - 1);
    return (p == "/") ? p : (p + "/");
  }

  String parentDir(const String& in) {
    String p = in;
    if (!p.length()) return "/";
    if (p != "/" && p.endsWith("/")) p.remove(p.length() - 1);
    int slash = p.lastIndexOf('/');
    if (slash <= 0) return "/";
    return p.substring(0, slash) + "/";
  }

  // ---------------------------------------------------------------------------
  // PROGMEM blocks for header/footer
  // ---------------------------------------------------------------------------

  const char kHtmlHeadPrefix[] PROGMEM =
    "<!DOCTYPE html><html><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width, initial-scale=1'>"
    "<title>";

  const char kHtmlHeadMid[] PROGMEM =
    "</title>";

  const char kHtmlStyleAndScript[] PROGMEM = R"rawliteral(
<style>
/* page */
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;
  font-size:14px;line-height:1.35;color:#333;margin:20px}
h2{margin-top:1.6em;padding-bottom:.2em;border-bottom:1px solid #ccc;font-size:1.1em}

/* containers */
fieldset{margin:1.2em 0;padding:1em 1.2em;border:1px solid #ddd;border-radius:6px;background:#fafafa}
legend{font-weight:700;padding:0 6px}

/* rows & controls */
.row{margin:.4em 0}
label{display:inline-block;min-width:160px;margin:.4em 0;font-weight:500}
input,select{margin:.3em 0;padding:.3em .4em;border:1px solid #bbb;border-radius:4px;font-size:.95em}
.row input[type='checkbox']{margin-left:.5em}

/* minor helpers */
small{color:#666;margin-left:.3em}

/* buttons */
button{padding:.45em .9em;border:1px solid #999;border-radius:5px;background:#f5f5f5;cursor:pointer}
button:disabled{opacity:.6;cursor:not-allowed}
</style>

<script>
function populateSelect(selectEl, data, selected) {
  var arr = [];
  if (Array.isArray(data)) {
    arr = data;
  } else if (data.options) {
    arr = data.options;
  } else if (data.items) {
    arr = data.items;
  } else if (data.transforms) {
    arr = data.transforms;
  } else if (data.results) {
    arr = data.results;
  } else if (data.choices) {
    arr = data.choices;
  }
  selectEl.innerHTML = '';
  arr.forEach(function(t) {
    var opt = document.createElement('option');
    opt.value = t.id || t.value || '';
    opt.textContent = (t.label || t.name || t.id || '?') + (t.out_units ? (' [' + t.out_units + ']') : '');
    if (opt.value === selected) {
      opt.selected = true;
    }
    selectEl.appendChild(opt);
  });
}

function loadTransforms(sensorId, selectEl, selected, mode) {
  var url = '/api/transforms/list?sensor=' + encodeURIComponent(sensorId) + '&t=' + Date.now();
  if (mode) url += '&mode=' + encodeURIComponent(mode);
  fetch(url, {cache:'no-store'})
    .then(function(r){ return r.json(); })
    .then(function(data){
      populateSelect(selectEl, data, selected);
    })
    .catch(function(err){
      console.error('Error loading transforms', err);
    });
}

document.addEventListener('DOMContentLoaded', function(){
  document.querySelectorAll('.reload').forEach(function(btn){
    btn.addEventListener('click', function(){
      var block = btn.closest('.tr-block');
      if (!block) return;
      var sensor = block.getAttribute('data-sensor');
      var sel = block.querySelector('select');
      var modeEl = document.getElementById(sensor + '_output_mode');
      var mode = modeEl ? modeEl.value : null;
      loadTransforms(sensor, sel, sel.value, mode);
    });
  });
});
</script>
)rawliteral";

  const char kHtmlHeadSuffix[] PROGMEM =
    "</head><body>";

  const char kHtmlFooter[] PROGMEM =
    "</body></html>";

  // ---------------------------------------------------------------------------
  // Raw-response helpers (bypass WebServer.send()/sendContent())
  // ---------------------------------------------------------------------------

  const char* reasonPhrase(int code) {
    switch (code) {
      case 200: return "OK";
      case 303: return "See Other";
      case 400: return "Bad Request";
      case 404: return "Not Found";
      case 423: return "Locked";
      case 500: return "Internal Server Error";
      default:  return "OK";
    }
  }

  void beginRaw(WebServer& srv, int code,
                const char* contentType,
                int32_t contentLength,
                bool closeConnection) {
    WiFiClient c = srv.client();

    c.printf("HTTP/1.1 %d %s\r\n", code, reasonPhrase(code));
    c.printf("Content-Type: %s\r\n", contentType ? contentType : "text/plain");

    if (closeConnection) c.print("Connection: close\r\n");

    if (contentLength >= 0) {
      c.printf("Content-Length: %ld\r\n", (long)contentLength);
    }

    c.print("\r\n");
  }

  void sendRaw(WebServer& srv, int code, const char* contentType, const char* body) {
    if (!body) body = "";
    const int32_t len = (int32_t)strlen(body);
    beginRaw(srv, code, contentType, len, true);
    srv.client().write((const uint8_t*)body, (size_t)len);
    srv.client().stop();
  }

  void sendRaw_P(WebServer& srv, int code, const char* contentType, PGM_P bodyP) {
    if (!bodyP) bodyP = PSTR("");

    // Compute PROGMEM C-string length
    size_t len = 0;
    while (pgm_read_byte(bodyP + len) != 0) ++len;

    beginRaw(srv, code, contentType, (int32_t)len, true);

    WiFiClient c = srv.client();
    for (size_t i = 0; i < len; ++i) {
      c.write((uint8_t)pgm_read_byte(bodyP + i));
    }
    c.stop();
  }

  void redirect303(WebServer& srv, const String& location, const char* body) {
    if (!body) body = "See Other";

    // Build minimal response. Location header is required.
    WiFiClient c = srv.client();
    const int32_t len = (int32_t)strlen(body);

    c.printf("HTTP/1.1 303 %s\r\n", reasonPhrase(303));
    c.print("Content-Type: text/plain\r\n");
    c.print("Connection: close\r\n");
    c.print("Location: ");
    c.print(location);
    c.print("\r\n");
    c.printf("Content-Length: %ld\r\n", (long)len);
    c.print("\r\n");
    if (len) c.write((const uint8_t*)body, (size_t)len);
    c.stop();
  }

  void writeHtmlEscaped(WebServer& srv, const String& in) {
    WiFiClient c = srv.client();

    // Small staging buffer reduces write calls, no heap.
    char buf[96];
    size_t n = 0;

    auto flush = [&]() {
      if (n) { c.write((const uint8_t*)buf, n); n = 0; }
    };

    for (size_t i = 0; i < in.length(); ++i) {
      const char ch = in[i];
      const char* repl = nullptr;

      switch (ch) {
        case '&':  repl = "&amp;";  break;
        case '<':  repl = "&lt;";   break;
        case '>':  repl = "&gt;";   break;
        case '"':  repl = "&quot;"; break;
        case '\'': repl = "&#39;";  break;
        default:   repl = nullptr;  break;
      }

      if (repl) {
        flush();
        c.print(repl);
      } else {
        if (n + 1 >= sizeof(buf)) flush();
        buf[n++] = ch;
      }
    }

    flush();
  }

  void writeHtmlHeader(WebServer& srv, const String& title) {
    // Assumes caller already did beginHtml()/beginRaw().
    writeF(srv, (const __FlashStringHelper*)kHtmlHeadPrefix);
    writeHtmlEscaped(srv, title);
    writeF(srv, (const __FlashStringHelper*)kHtmlHeadMid);
    writeF(srv, (const __FlashStringHelper*)kHtmlStyleAndScript);
    writeF(srv, (const __FlashStringHelper*)kHtmlHeadSuffix);
  }

  void writeHtmlFooter(WebServer& srv) {
    writeF(srv, (const __FlashStringHelper*)kHtmlFooter);
  }

  // Map status codes to a short reason phrase (optional but nice)
  static const __FlashStringHelper* reasonPhrase_(int code) {
    switch (code) {
      case 200: return F("OK");
      case 303: return F("See Other");
      case 400: return F("Bad Request");
      case 404: return F("Not Found");
      case 415: return F("Unsupported Media Type");
      case 423: return F("Locked");
      case 500: return F("Internal Server Error");
      default:  return F("");
    }
  }

  template<typename ServerT>
  inline void sendPlainRaw(ServerT& srv,
                           int code,
                           const __FlashStringHelper* contentType,
                           const String& body)
  {
    auto client = srv.client();
    if (!client) return;

    client.print(F("HTTP/1.1 "));
    client.print(code);
    client.print(' ');
    client.print(reasonPhrase_(code));
    client.print(F("\r\nContent-Type: "));
    client.print(contentType);
    client.print(F("\r\nConnection: close\r\n\r\n"));

    client.print(body);
    client.flush();
    client.stop();
  }

  template<typename ServerT>
  inline void sendJsonRaw(ServerT& srv, int code, const String& json) {
    sendPlainRaw(srv, code, F("application/json"), json);
  }

  template<typename ServerT>
  inline void sendRedirect303Raw(ServerT& srv, const String& location)
  {
    auto client = srv.client();
    if (!client) return;

    client.print(F("HTTP/1.1 303 See Other\r\n"));
    client.print(F("Location: "));
    client.print(location);
    client.print(F("\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\n"));
    client.print(F("See Other"));
    client.flush();
    client.stop();
  }

  // Explicit template instantiation for your WebServer type (ESP32)
  template void sendPlainRaw<WebServer>(WebServer&, int, const __FlashStringHelper*, const String&);
  template void sendJsonRaw<WebServer>(WebServer&, int, const String&);
  template void sendRedirect303Raw<WebServer>(WebServer&, const String&);


} // namespace HtmlUtil
