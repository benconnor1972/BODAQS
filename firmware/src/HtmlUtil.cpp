#include "HtmlUtil.h"
#include "ConfigManager.h"
#include "WiFiManager.h"
#include "WebAssets.h"
#include <WebServer.h>
#include <WiFi.h>

namespace HtmlUtil {
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
    if (n.endsWith(".bdq"))  return F("application/octet-stream");
    if (n.endsWith(".txt"))  return F("text/plain");
    if (n.endsWith(".json")) return F("application/json");
    if (n.endsWith(".htm") || n.endsWith(".html")) return F("text/html");
    return F("application/octet-stream");
  }

  String htmlHeader(const String& title) {
    String s = F("<!DOCTYPE html><html><head><meta charset='utf-8'>");
    s += F("<meta name='viewport' content='width=device-width, initial-scale=1'>");
    s += "<title>" + title + "</title>";
    s += F("<script src='/static/htmx.min.js?v=");
    s += htmx_js_hash;
    s += F("' defer></script>");
    s += F("<link rel='stylesheet' href='/static/app.css?v=");
    s += app_css_hash;
    s += F("'>");

    s += F("</head><body>");

    String loggerName = ConfigManager::get().loggerName;
    loggerName.trim();
    if (!loggerName.length()) loggerName = F("BODAQS");

    const auto wifiStatus = WiFiManager::status();
    String ssid = wifiStatus.ssid;
    ssid.trim();
    if (!wifiStatus.networkUp || !ssid.length()) ssid = F("not connected");
    String ip = wifiStatus.networkUp ? wifiStatus.ip : String("-");
    String mode = ConfigManager::wifiModeLabel(wifiStatus.mode);

    s += F("<div class='titlebar'>BODAQS data logger: ");
    s += htmlEscape(loggerName);
    s += F("</div>");
    s += F("<div class='netbar'>Network: ");
    s += htmlEscape(mode);
    s += F(" / ");
    s += htmlEscape(ssid);
    s += F(" &nbsp; IP: ");
    s += htmlEscape(ip);
    s += F("</div>");
    s += F("<div class='topnav'>");
    s += F("<a href='/files'>Files</a>");
    s += F("<a href='/config'>General</a>");
    s += F("<a href='/config/sensors'>Sensors</a>");
    s += F("</div>");
    return s;
  }

  String htmlFooter() {
    return F("</body></html>");
  }

  String htmlEscape(const String& in) {
    String out; out.reserve(in.length() + 8);
    for (size_t i = 0; i < in.length(); ++i) {
      char c = in[i];
      if      (c == '&')  out += F("&amp;");
      else if (c == '<')  out += F("&lt;");
      else if (c == '>')  out += F("&gt;");
      else if (c == '"')  out += F("&quot;");
      else out += c;
    }
    return out;
  }

  bool isHtmxRequest(WebServer& srv) {
    if (!srv.hasHeader(F("HX-Request"))) return false;
    String val = srv.header(F("HX-Request"));
    val.trim();
    val.toLowerCase();
    return val == "true";
  }

  String htmlFragment(const String& body) {
    return body;
  }

  String htmlRespond(WebServer& srv, const String& title, const String& body) {
    if (isHtmxRequest(srv)) {
      return htmlFragment(body);
    }
    return htmlHeader(title) + body + htmlFooter();
  }

  bool safePath(const String& name) {
    if (name.length() == 0) return false;
    if (name.indexOf("..") >= 0) return false;
    // disallow dir separators (both / and \)
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
  // remove trailing slashes (leave single '/' intact)
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

}
