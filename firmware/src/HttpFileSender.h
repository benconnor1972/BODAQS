#pragma once

#include <Arduino.h>
#include <WebServer.h>

namespace HttpFileSender {

bool writeResponseChunk(WebServer& srv, const void* data, size_t len);
bool sendText(WebServer& srv,
              int statusCode,
              const String& contentType,
              const String& body,
              const String& cacheControl = String());

bool sendSdFile(WebServer& srv,
                const String& path,
                const String& contentType,
                const String& downloadName,
                const String& cacheControl = String());

}
