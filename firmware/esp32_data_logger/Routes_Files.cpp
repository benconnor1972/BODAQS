#include "Routes_Files.h"
#include <Arduino.h>
#include <SdFat.h>
#include "SD_MMC.h"

#include "HtmlUtil.h"
#include "WiFiManager.h"
#include "WebServerManager.h"

using namespace HtmlUtil;

// -------------------- Small streaming HTML helpers --------------------

static void sendPageHeader_(WebServer& srv, const __FlashStringHelper* title) {
  // chunked
  srv.setContentLength(CONTENT_LENGTH_UNKNOWN);
  srv.send(200, F("text/html"), "");

  // Keep this lightweight and fully streaming.
  // (We do not call HtmlUtil::htmlHeader() to avoid a big String build.)
  srv.sendContent_P(PSTR("<!DOCTYPE html><html><head><meta charset='utf-8'>"
                         "<meta name='viewport' content='width=device-width, initial-scale=1'>"
                         "<title>"));
  srv.sendContent(String(title)); // small; acceptable
  srv.sendContent_P(PSTR("</title>"
                         "<style>"
                         "body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;"
                         "font-size:14px;line-height:1.35;color:#333;margin:20px}"
                         "h2{margin-top:1.2em;padding-bottom:.2em;border-bottom:1px solid #ccc;font-size:1.1em}"
                         "fieldset{margin:1.2em 0;padding:1em 1.2em;border:1px solid #ddd;border-radius:6px;background:#fafafa}"
                         "legend{font-weight:700;padding:0 6px}"
                         ".row{margin:.4em 0}"
                         "label{display:inline-block;min-width:160px;margin:.4em 0;font-weight:500}"
                         "input,select{margin:.3em 0;padding:.3em .4em;border:1px solid #bbb;border-radius:4px;font-size:.95em}"
                         "small{color:#666;margin-left:.3em}"
                         "button{padding:.45em .9em;border:1px solid #999;border-radius:5px;background:#f5f5f5;cursor:pointer}"
                         "table{border-collapse:collapse;width:100%;max-width:980px}"
                         "th,td{border-bottom:1px solid #eee;padding:6px 8px;text-align:left;vertical-align:top}"
                         "th{background:#fafafa}"
                         "a{color:#1565c0;text-decoration:none}"
                         "a:hover{text-decoration:underline}"
                         ".pill{display:inline-block;padding:1px 6px;border:1px solid #ddd;border-radius:999px;background:#fafafa;font-size:12px}"
                         "</style>"
                         "</head><body>"));
}

static void sendPageFooter_(WebServer& srv) {
  srv.sendContent_P(PSTR("</body></html>"));
  srv.sendContent(""); // end chunked
}

static void sendEsc_(WebServer& srv, const String& s) {
  // HtmlUtil::htmlEscape returns a new String; this is still small per usage.
  srv.sendContent(htmlEscape(s));
}

static void sendBreadcrumbs_(WebServer& srv, const String& dirNorm) {
  // dirNorm is normalized (leading '/', trailing '/' except root is '/')
  srv.sendContent_P(PSTR("<p class='pill'>Path: "));

  if (dirNorm == "/") {
    srv.sendContent_P(PSTR("/</p>"));
    return;
  }

  srv.sendContent_P(PSTR("<a href=\"/files?path=/\">/</a>"));

  // Build segments without allocating a huge String.
  int start = 1; // skip leading '/'
  while (start < (int)dirNorm.length()) {
    int slash = dirNorm.indexOf('/', start);
    if (slash < 0) break;

    String seg = dirNorm.substring(start, slash);
    if (seg.length()) {
      // cumulative path up to this segment
      String cum = dirNorm.substring(0, slash + 1);
      srv.sendContent_P(PSTR(" / <a href=\"/files?path="));
      sendEsc_(srv, cum);
      srv.sendContent_P(PSTR("\">"));
      sendEsc_(srv, seg);
      srv.sendContent_P(PSTR("</a>"));
    }

    start = slash + 1;
  }

  srv.sendContent_P(PSTR("</p>"));
}

static void listDirSpiStream_(WebServer& srv, SdFs* sd, const String& dirNorm) {
  SdFile d;
  if (!d.open(dirNorm.c_str())) {
    srv.sendContent_P(PSTR("<p>Failed to open directory.</p>"));
    return;
  }

  SdFile e;
  char name[128];

  // --- Folders first ---
  d.rewind();
  while (e.openNext(&d, O_READ)) {
    if (!e.isSubDir()) { e.close(); continue; }
    e.getName(name, sizeof(name));
    if (strcmp(name, ".") == 0 || strcmp(name, "..") == 0) { e.close(); continue; }

    String child = normDir(dirNorm) + String(name) + "/";

    srv.sendContent_P(PSTR("<tr><td>📁 <a href=\"/files?path="));
    sendEsc_(srv, child);
    srv.sendContent_P(PSTR("\">"));
    sendEsc_(srv, String(name));
    srv.sendContent_P(PSTR("</a></td><td>-</td><td>"
                           "<a class='delete' href=\"/rmdir?path="));
    sendEsc_(srv, child);
    srv.sendContent_P(PSTR("\">Remove</a>"
                           "</td></tr>"));

    e.close();
    delay(0);
  }

  // --- Files ---
  d.rewind();
  while (e.openNext(&d, O_READ)) {
    if (e.isSubDir()) { e.close(); continue; }
    e.getName(name, sizeof(name));

    String full = normDir(dirNorm) + String(name);

    srv.sendContent_P(PSTR("<tr><td>📄 "));
    sendEsc_(srv, String(name));
    srv.sendContent_P(PSTR("</td><td>"));
    srv.sendContent(String((unsigned long)e.fileSize()));
    srv.sendContent_P(PSTR("</td><td>"
                           "<a class='download' href=\"/download?path="));
    sendEsc_(srv, full);
    srv.sendContent_P(PSTR("\">Download</a> "
                           "<a class='delete' href=\"/delete?path="));
    sendEsc_(srv, full);
    srv.sendContent_P(PSTR("\">Delete</a>"
                           "</td></tr>"));

    e.close();
    delay(0);
  }

  d.close();
}

static void listDirMMCStream_(WebServer& srv, const String& dirNorm) {
  File d = SD_MMC.open(dirNorm.c_str());
  if (!d || !d.isDirectory()) {
    srv.sendContent_P(PSTR("<p>Failed to open directory.</p>"));
    if (d) d.close();
    return;
  }

  // Folders first
  {
    File e = d.openNextFile();
    while (e) {
      const bool isDir = e.isDirectory();
      String nm = e.name();
      if (isDir) {
        // SD_MMC's File::name() can include the full path on some cores; keep only tail.
        int slash = nm.lastIndexOf('/');
        String tail = (slash >= 0) ? nm.substring(slash + 1) : nm;
        if (tail.length() && tail != "." && tail != "..") {
          String child = normDir(dirNorm) + tail + "/";

          srv.sendContent_P(PSTR("<tr><td>📁 <a href=\"/files?path="));
          sendEsc_(srv, child);
          srv.sendContent_P(PSTR("\">"));
          sendEsc_(srv, tail);
          srv.sendContent_P(PSTR("</a></td><td>-</td><td>"
                                 "<a class='delete' href=\"/rmdir?path="));
          sendEsc_(srv, child);
          srv.sendContent_P(PSTR("\">Remove</a>"
                                 "</td></tr>"));
        }
      }
      e.close();
      e = d.openNextFile();
      delay(0);
    }
  }

  // Rewind by closing and reopening
  d.close();
  d = SD_MMC.open(dirNorm.c_str());
  if (!d || !d.isDirectory()) {
    if (d) d.close();
    return;
  }

  // Files
  {
    File e = d.openNextFile();
    while (e) {
      if (!e.isDirectory()) {
        String nm = e.name();
        int slash = nm.lastIndexOf('/');
        String tail = (slash >= 0) ? nm.substring(slash + 1) : nm;

        String full = normDir(dirNorm) + tail;

        srv.sendContent_P(PSTR("<tr><td>📄 "));
        sendEsc_(srv, tail);
        srv.sendContent_P(PSTR("</td><td>"));
        srv.sendContent(String((unsigned long)e.size()));
        srv.sendContent_P(PSTR("</td><td>"
                               "<a class='download' href=\"/download?path="));
        sendEsc_(srv, full);
        srv.sendContent_P(PSTR("\">Download</a> "
                               "<a class='delete' href=\"/delete?path="));
        sendEsc_(srv, full);
        srv.sendContent_P(PSTR("\">Delete</a>"
                               "</td></tr>"));
      }

      e.close();
      e = d.openNextFile();
      delay(0);
    }
  }

  d.close();
}

// -------------------- Routes --------------------

void registerFileRoutes() {

  // ---------- GET /files?path=/dir/ ----------
  g_server.on("/files", HTTP_GET, [](){
    auto& srv = g_server;
    WiFiManager::noteUserActivity();

    SdFs* sd = WebServerManager::sd();
    const bool useSpi = (sd != nullptr);

    String path = srv.hasArg("path") ? srv.arg("path") : "/";
    if (!safeRelPath(path)) { srv.send(400, F("text/plain"), F("Bad path")); return; }
    const String dir = normDir(path);

    sendPageHeader_(srv, F("Files"));

    srv.sendContent_P(PSTR("<h2>Files</h2>"));
    sendBreadcrumbs_(srv, dir);

    // Upload form
    srv.sendContent_P(PSTR("<form method='POST' action='/upload?path="));
    sendEsc_(srv, dir);
    srv.sendContent_P(PSTR("' enctype='multipart/form-data' style='margin:8px 0'>"
                           "<input type='file' name='file' multiple>"
                           "<button type='submit'>Upload</button></form>"));

    // New folder form
    srv.sendContent_P(PSTR("<form method='POST' action='/mkdir' style='margin:8px 0'>"
                           "<input type='hidden' name='path' value='"));
    sendEsc_(srv, dir);
    srv.sendContent_P(PSTR("'>"
                           "<input type='text' name='name' placeholder='New folder name'> "
                           "<button type='submit'>Create folder</button></form>"));

    // Table
    srv.sendContent_P(PSTR("<table><tr><th>Name</th><th>Size</th><th>Action</th></tr>"));

    if (useSpi) listDirSpiStream_(srv, sd, dir);
    else        listDirMMCStream_(srv, dir);

    srv.sendContent_P(PSTR("</table><p><a href='/'>Home</a></p>"));
    sendPageFooter_(srv);
  });

  // ---------- GET /download?path=/dir/file ----------
  g_server.on("/download", HTTP_GET, [](){
    auto& srv = g_server;
    WiFiManager::noteUserActivity();

    SdFs* sd = WebServerManager::sd();
    const bool useSpi = (sd != nullptr);

    if (!srv.hasArg("path")) {
      srv.send(400, F("text/plain"), F("Missing 'path'"));
      return;
    }

    String path = srv.arg("path");
    if (!safeRelPath(path)) {
      srv.send(400, F("text/plain"), F("Bad path"));
      return;
    }

    // Content type (small String)
    String ct = contentTypeFor(path);
    if (!ct.length()) ct = F("application/octet-stream");

    // Force download (simple filename)
    String filename = path;
    int slash = filename.lastIndexOf('/');
    if (slash >= 0) filename = filename.substring(slash + 1);


  WiFiClient client = srv.client();
  if (!client) {
    // Conservative: just bail; connection vanished
    // You *can* log this if you like.
    return;
  }

  // HTTP header
  client.print(F("HTTP/1.1 200 OK\r\n"));
  client.print(F("Content-Type: "));
  client.print(HtmlUtil::contentTypeFor(filename));
  client.print(F("\r\nContent-Disposition: attachment; filename=\""));
  client.print(filename);
  client.print(F("\"\r\nConnection: close\r\n\r\n"));

  static uint8_t buf[2048];
  int32_t n = 0;

  if (!useSpi) {
    // SD_MMC path
    File f = SD_MMC.open(path.c_str(), FILE_READ);
    if (!f) {
      HtmlUtil::sendPlainRaw(srv, 404, F("text/plain"), F("Not found"));
      return;
    }
    while ((n = f.read(buf, sizeof(buf))) > 0) {
      client.write(buf, n);
      delay(0);
    }
    f.close();
  } else {
    // SPI / SdFs path
    SdFs* sd = WebServerManager::sd();
    if (!sd) {
      HtmlUtil::sendPlainRaw(srv, 500, F("text/plain"), F("SPI SD not available"));
      return;
    }
    SdFile in;
    if (!in.open(path.c_str(), O_RDONLY) || in.isDir()) {
      in.close();
      HtmlUtil::sendPlainRaw(srv, 404, F("text/plain"), F("Not found"));
      return;
    }
    while ((n = in.read(buf, sizeof(buf))) > 0) {
      client.write(buf, n);
      delay(0);
    }
    in.close();
  }

  client.flush();
  client.stop();
  });

  // ---------- GET /delete?path=/dir/file ----------
  g_server.on("/delete", HTTP_GET, [](){
    auto& srv = g_server;
    WiFiManager::noteUserActivity();

    SdFs* sd = WebServerManager::sd();
    const bool useSpi = (sd != nullptr);

    if (!srv.hasArg("path")) {
      srv.send(400, F("text/plain"), F("Missing 'path'"));
      return;
    }

    String path = srv.arg("path");
    if (!safeRelPath(path)) {
      srv.send(400, F("text/plain"), F("Bad path"));
      return;
    }

    bool exists = false;
    bool removed = false;

    if (useSpi) {
      exists = sd->exists(path.c_str());
      if (exists) removed = sd->remove(path.c_str());
    } else {
      exists = SD_MMC.exists(path.c_str());
      if (exists) removed = SD_MMC.remove(path.c_str());
    }

    if (!exists) { srv.send(404, F("text/plain"), F("Not found")); return; }
    if (!removed) { srv.send(500, F("text/plain"), F("Delete failed")); return; }

    srv.sendHeader(F("Location"), "/files?path=" + parentDir(path));
    srv.send(303, F("text/plain"), F("Deleted"));
  });

  // ---------- GET /rmdir?path=/dir/ [confirm=1] ----------
  g_server.on("/rmdir", HTTP_GET, [](){
    auto& srv = g_server;
    WiFiManager::noteUserActivity();

    SdFs* sd = WebServerManager::sd();
    const bool useSpi = (sd != nullptr);

    if (!srv.hasArg("path")) { srv.send(400, F("text/plain"), F("Missing 'path'")); return; }

    String p = srv.arg("path");
    p = normDir(p);
    if (!safeRelPath(p)) { srv.send(400, F("text/plain"), F("Bad path")); return; }

    const bool confirmed = srv.hasArg("confirm") && srv.arg("confirm") == "1";
    if (!confirmed) {
      sendPageHeader_(srv, F("Confirm remove folder"));
      srv.sendContent_P(PSTR("<h2>Confirm</h2><p>Remove folder:</p><p><code>"));
      sendEsc_(srv, p);
      srv.sendContent_P(PSTR("</code></p>"
                             "<p>"
                             "<a class='delete' href=\"/rmdir?confirm=1&path="));
      sendEsc_(srv, p);
      srv.sendContent_P(PSTR("\">Yes, remove</a> &nbsp; "
                             "<a href=\"/files?path="));
      sendEsc_(srv, parentDir(p));
      srv.sendContent_P(PSTR("\">Cancel</a>"
                             "</p>"));
      sendPageFooter_(srv);
      return;
    }

    bool ok = false;
    if (useSpi) ok = sd->rmdir(p.c_str());
    else        ok = SD_MMC.rmdir(p.c_str());

    if (!ok) { srv.send(500, F("text/plain"), F("rmdir failed")); return; }

    srv.sendHeader(F("Location"), "/files?path=" + parentDir(p));
    srv.send(303, F("text/plain"), F("Removed"));
  });

  // ---------- POST /mkdir (path + name) ----------
  g_server.on("/mkdir", HTTP_POST, [](){
    auto& srv = g_server;
    WiFiManager::noteUserActivity();

    SdFs* sd = WebServerManager::sd();
    const bool useSpi = (sd != nullptr);

    if (!srv.hasArg("path") || !srv.hasArg("name")) {
      srv.send(400, F("text/plain"), F("Missing args"));
      return;
    }

    String p = srv.arg("path");
    String name = srv.arg("name");
    p = normDir(p);
    name.trim();

    if (!safeRelPath(p) || !safePath(name) || !name.length()) {
      srv.send(400, F("text/plain"), F("Bad path/name"));
      return;
    }

    String full = normDir(p) + name + "/";

    bool ok = false;
    if (useSpi) ok = sd->mkdir(full.c_str());
    else        ok = SD_MMC.mkdir(full.c_str());

    if (!ok) { srv.send(500, F("text/plain"), F("mkdir failed")); return; }

    srv.sendHeader(F("Location"), "/files?path=" + normDir(p));
    srv.send(303, F("text/plain"), F("Created"));
  });

  // ---------- POST /rmdir (path) ----------
  g_server.on("/rmdir", HTTP_POST, [](){
    auto& srv = g_server;
    WiFiManager::noteUserActivity();

    SdFs* sd = WebServerManager::sd();
    const bool useSpi = (sd != nullptr);

    if (!srv.hasArg("path")) { srv.send(400, F("text/plain"), F("Missing 'path'")); return; }

    String p = srv.arg("path");
    p = normDir(p);
    if (!safeRelPath(p)) { srv.send(400, F("text/plain"), F("Bad path")); return; }

    bool ok = false;
    if (useSpi) ok = sd->rmdir(p.c_str());
    else        ok = SD_MMC.rmdir(p.c_str());

    if (!ok) { srv.send(500, F("text/plain"), F("rmdir failed")); return; }

    srv.sendHeader(F("Location"), "/files?path=" + parentDir(p));
    srv.send(303, F("text/plain"), F("Removed"));
  });

  // ---------- POST /upload?path=/dir/ ----------
  // Handler signature: (onRequest, onUpload)
  g_server.on("/upload", HTTP_POST,
    [](){
      auto& srv = g_server;
      WiFiManager::noteUserActivity();

      String p = srv.hasArg("path") ? srv.arg("path") : "/";
      p = normDir(p);
      if (!safeRelPath(p)) { srv.send(400, F("text/plain"), F("Bad path")); return; }

      // After upload completes, redirect back to listing
      srv.sendHeader(F("Location"), "/files?path=" + normDir(p));
      srv.send(303, F("text/plain"), F("OK"));
    },
    [](){
      auto& srv = g_server;

      SdFs* sd = WebServerManager::sd();
      static bool useSpi = false;

      HTTPUpload& up = srv.upload();

      static SdFile outSpi;
      static File   outMMC;
      static String baseDir;
      static String filename;
      static bool opened = false;

      if (up.status == UPLOAD_FILE_START) {
        baseDir = srv.hasArg("path") ? srv.arg("path") : "/";
        baseDir = normDir(baseDir);

        filename = up.filename;
        // basic safety
        if (!safeRelPath(baseDir) || !safePath(filename)) {
          opened = false;
          return;
        }

        useSpi = (sd != nullptr);
        opened = false;

        String full = normDir(baseDir) + filename;

        if (useSpi) {
          outSpi.close();
          if (outSpi.open(full.c_str(), O_WRITE | O_CREAT | O_TRUNC)) opened = true;
        } else {
          outMMC.close();
          outMMC = SD_MMC.open(full.c_str(), FILE_WRITE);
          if (outMMC) opened = true;
        }
      }
      else if (up.status == UPLOAD_FILE_WRITE) {
        if (!opened) return;

        if (useSpi) {
          outSpi.write(up.buf, up.currentSize);
        } else {
          outMMC.write(up.buf, up.currentSize);
        }
      }
      else if (up.status == UPLOAD_FILE_END) {
        if (useSpi) outSpi.close();
        else if (outMMC) outMMC.close();
        opened = false;
      }
      else if (up.status == UPLOAD_FILE_ABORTED) {
        if (useSpi) outSpi.close();
        else if (outMMC) outMMC.close();
        opened = false;
      }
    }
  );
}
