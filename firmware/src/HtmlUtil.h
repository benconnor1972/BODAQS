#pragma once
#include <Arduino.h>  // for String, F(), etc.
#include "FirmwareInfo.h"  // for FirmwareInfo::version()

class WebServer;  // forward declaration — full include in .cpp

// Keep helpers in a namespace to avoid name collisions.
namespace HtmlUtil {

  // Rendering
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

  // htmx fragment support
  bool   isHtmxRequest(WebServer& srv);                    // true if HX-Request: true header
  String htmlFragment(const String& body);                 // body only, no <html>/<head> wrapper
  String htmlRespond(WebServer& srv, const String& title, const String& body);  // fragment if htmx, full page otherwise
}
