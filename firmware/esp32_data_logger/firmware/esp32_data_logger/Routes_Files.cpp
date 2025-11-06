#include "Routes_Files.h"
#include <Arduino.h>
#include <SdFat.h>

#include "HtmlUtil.h"
#include "WiFiManager.h"
#include "WebServerManager.h"

using namespace HtmlUtil;

static bool ensureSd_(SdFat*& out) {
  out = WebServerManager::sd();
  if (!out) {
    Serial.println(F("[FILES] SdFat* is null (call WebServerManager::begin first)"));
    return false;
  }
  return true;
}

static String prettySize_(uint64_t bytes) {
  if (bytes < 1024ULL) {
    return String(bytes) + F(" B");
  }
  double val = bytes / 1024.0;
  if (val < 1024.0) {
    char buf[16];
    snprintf(buf, sizeof(buf), "%.1f KB", val);
    return String(buf);
  }
  val /= 1024.0;
  if (val < 1024.0) {
    char buf[16];
    snprintf(buf, sizeof(buf), "%.2f MB", val);
    return String(buf);
  }
  val /= 1024.0;
  char buf[16];
  snprintf(buf, sizeof(buf), "%.2f GB", val);
  return String(buf);
}

static void listDir_(SdFat* sd, const String& dir, String& html) {
  SdFile d;
  if (!d.open(dir.c_str())) { html += F("<p>Failed to open directory.</p>"); return; }

  SdFile e;
  char name[128];

  // --- Folders first ---
  d.rewind();
  while (e.openNext(&d, O_READ)) {
    if (!e.isSubDir()) { e.close(); continue; }
    e.getName(name, sizeof(name));
    if (strcmp(name, ".") == 0 || strcmp(name, "..") == 0) { e.close(); continue; }

    html += F("<tr><td>📁 <a href=\"/files?path=");
    html += htmlEscape(normDir(dir) + String(name) + "/");
    html += F("\">");
    html += htmlEscape(String(name));
    html += F("</a></td><td>-</td><td>"
              "<a class='delete' href=\"/rmdir?path=");
    html += htmlEscape(normDir(dir) + String(name) + "/");
    html += F("\">Remove</a>"
              "</td></tr>");

    e.close();
    delay(0);
  }

  // --- Files ---
  d.rewind();
  while (e.openNext(&d, O_READ)) {
    if (e.isSubDir()) { e.close(); continue; }
    e.getName(name, sizeof(name));
    const uint32_t sz = e.fileSize();

    const String full = normDir(dir) + String(name);
    html += F("<tr><td>");
    html += htmlEscape(String(name));
    html += F("</td><td>");
    html += prettySize_(sz);
    html += F("</td><td>"
              "<a class='download' href=\"/download?path=");
    html += htmlEscape(full);
    html += F("\">Download</a> "
              "<a class='delete' href=\"/delete?path=");
    html += htmlEscape(full);
    html += F("\">Delete</a></td></tr>");

    e.close();
    delay(0);
  }

  d.close();
}

static void emitBreadcrumbs_(const String& dir, String& html) {
  // dir is normalized (leading '/', trailing '/' unless root)
  html += F("<p>");
  html += F("<a href='/files?path=/'>/</a>");
  if (dir == "/") { html += F("</p>"); return; }

  String acc = "/";
  // iterate segments
  for (int i = 1; i < (int)dir.length() - 1; ++i) {
    if (dir[i] == '/') {
      html += F(" / ");
      html += "<a href='/files?path=";
      html += htmlEscape(acc);
      html += "'>";
      // label = tail of acc (segment name)
      int last = acc.lastIndexOf('/', acc.length() - 2);
      String label = (last >= 0) ? acc.substring(last + 1) : acc;
      if (!label.length()) label = "/";
      html += htmlEscape(label);
      html += F("</a>");
    } else {
      acc += dir[i];
    }
  }
  html += F("</p>");
}

void registerFileRoutes(WebServer& srv) {
  WebServer* S = &srv;

  // ---------- GET /files?path=/dir/ ----------
  S->on("/files", HTTP_GET, [S](){
    auto& srv = *S;
    WiFiManager::noteUserActivity();

    SdFat* sd = nullptr;
    if (!ensureSd_(sd)) { srv.send(500, F("text/plain"), F("SD not available")); return; }

    String path = srv.hasArg("path") ? srv.arg("path") : "/";
    if (!safeRelPath(path)) { srv.send(400, F("text/plain"), F("Bad path")); return; }
    const String dir = normDir(path);

    String html = htmlHeader(F("Files"));
    html += F("<h2>Files</h2>");

    // Breadcrumbs
    emitBreadcrumbs_(dir, html);

    // Upload form (multipart)
    html += F("<form method='POST' action='/upload?path=");
    html += htmlEscape(dir);
    html += F("' enctype='multipart/form-data' style='margin:8px 0'>"
             "<input type='file' name='file' multiple>"
             "<button type='submit'>Upload</button></form>");

    // New folder form
    html += F("<form method='POST' action='/mkdir' style='margin:8px 0'>"
              "<input type='hidden' name='path' value='");
    html += htmlEscape(dir);
    html += F("'>"
              "<input type='text' name='name' placeholder='New folder name'> "
              "<button type='submit'>Create</button></form>");

    // Parent link
    if (dir != "/") {
      html += F("<p><a href='/files?path=");
      html += htmlEscape(parentDir(dir));
      html += F("'>⬆ Parent</a></p>");
    }

    // Table
    html += F("<table><tr><th>Name</th><th>Size</th><th>Action</th></tr>");
    listDir_(sd, dir, html);
    html += F("</table><p><a href='/'>Home</a></p>");
    html += htmlFooter();

    srv.send(200, F("text/html"), html);
  });

  // ---------- GET /download?path=/dir/file ----------
  S->on("/download", HTTP_GET, [S](){
    auto& srv = *S;
    WiFiManager::noteUserActivity();

    SdFat* sd = nullptr;
    if (!ensureSd_(sd)) { srv.send(500, F("text/plain"), F("SD not available")); return; }
    if (!srv.hasArg("path")) { srv.send(400, F("text/plain"), F("Missing 'path'")); return; }

    String path = srv.arg("path");
    if (!safeRelPath(path)) { srv.send(400, F("text/plain"), F("Bad path")); return; }

    SdFile f;
    if (!f.open(path.c_str(), O_READ)) { srv.send(404, F("text/plain"), F("Not found")); return; }

    // Content headers
    const String filename = path.substring(path.lastIndexOf('/') + 1);
    String ctype = contentTypeFor(path);
    String hdr = String(F("attachment; filename=\"")) + filename + F("\"");
    srv.sendHeader(F("Content-Disposition"), hdr);
    srv.setContentLength(CONTENT_LENGTH_UNKNOWN);
    srv.send(200, ctype, "");

    // Stream file
    static uint8_t buf[2048];
    int32_t n;
    while ((n = f.read(buf, sizeof(buf))) > 0) {
      srv.sendContent_P((const char*)buf, n);
      delay(0);
    }
    f.close();
    srv.sendContent(""); // end chunked
  });

  // ---------- GET /delete?path=/dir/file ----------
  S->on("/delete", HTTP_GET, [S](){
    auto& srv = *S;
    WiFiManager::noteUserActivity();

    SdFat* sd = nullptr;
    if (!ensureSd_(sd)) { srv.send(500, F("text/plain"), F("SD not available")); return; }
    if (!srv.hasArg("path")) { srv.send(400, F("text/plain"), F("Missing 'path'")); return; }

    String path = srv.arg("path");
    if (!safeRelPath(path)) { srv.send(400, F("text/plain"), F("Bad path")); return; }

    // Delete immediately
    if (!sd->exists(path.c_str())) { srv.send(404, F("text/plain"), F("Not found")); return; }
    if (!sd->remove(path.c_str())) { srv.send(500, F("text/plain"), F("Delete failed")); return; }

    srv.sendHeader(F("Location"), "/files?path=" + parentDir(path));
    srv.send(303, F("text/plain"), F("Deleted"));
  });

  // ---------- GET /rmdir?path=/dir/ [confirm=1] ----------
  S->on("/rmdir", HTTP_GET, [S](){
    auto& srv = *S;
    WiFiManager::noteUserActivity();

    SdFat* sd = nullptr;
    if (!ensureSd_(sd)) { srv.send(500, F("text/plain"), F("SD not available")); return; }
    if (!srv.hasArg("path")) { srv.send(400, F("text/plain"), F("Missing 'path'")); return; }

    String p = srv.arg("path");
    p = normDir(p);
    if (!safeRelPath(p)) { srv.send(400, F("text/plain"), F("Bad path")); return; }

    const bool confirmed = srv.hasArg("confirm") && srv.arg("confirm") == "1";
    if (!confirmed) {
      String html = htmlHeader(F("Confirm remove folder"));
      html += F("<h2>Confirm remove folder</h2><p>Remove: <b>");
      html += htmlEscape(p);
      html += F("</b>?</p><p>"
                "<a class='delete' href='/rmdir?path=");
      html += htmlEscape(p);
      html += F("&confirm=1'>Yes, remove</a> &nbsp; "
                "<a href='/files?path=");
      html += htmlEscape(parentDir(p));
      html += F("'>Cancel</a></p>");
      html += htmlFooter();
      srv.send(200, F("text/html"), html);
      return;
    }

    // Ensure empty before deletion
    SdFile d;
    if (!d.open(p.c_str())) { srv.send(404, F("text/plain"), F("Not found")); return; }
    SdFile e; bool empty = true; while (e.openNext(&d, O_READ)) { e.close(); empty = false; break; }
    d.close();
    if (!empty) { srv.send(409, F("text/plain"), F("Directory not empty")); return; }

    if (!sd->rmdir(p.c_str())) { srv.send(500, F("text/plain"), F("rmdir failed")); return; }

    srv.sendHeader(F("Location"), "/files?path=" + parentDir(p));
    srv.send(303, F("text/plain"), F("Removed"));
  });

  // ---------- POST /mkdir (path + name) ----------
  S->on("/mkdir", HTTP_POST, [S](){
    auto& srv = *S;
    WiFiManager::noteUserActivity();

    SdFat* sd = nullptr;
    if (!ensureSd_(sd)) { srv.send(500, F("text/plain"), F("SD not available")); return; }

    const String base = srv.hasArg("path") ? srv.arg("path") : "/";
    const String name = srv.hasArg("name") ? srv.arg("name") : "";

    if (!safeRelPath(normDir(base))) { srv.send(400, F("text/plain"), F("Bad path")); return; }
    if (!name.length() || name.indexOf('/') >= 0 || name.indexOf('\\') >= 0) {
      srv.send(400, F("text/plain"), F("Bad folder name"));
      return;
    }

    const String full = normDir(base) + name + "/";
    if (!sd->mkdir(full.c_str())) { srv.send(500, F("text/plain"), F("mkdir failed")); return; }

    srv.sendHeader(F("Location"), "/files?path=" + normDir(base));
    srv.send(303);
  });

  // ---------- POST /rmdir (path) (empty dirs only) ----------
  S->on("/rmdir", HTTP_POST, [S](){
    auto& srv = *S;
    WiFiManager::noteUserActivity();

    SdFat* sd = nullptr;
    if (!ensureSd_(sd)) { srv.send(500, F("text/plain"), F("SD not available")); return; }

    String p = srv.hasArg("path") ? srv.arg("path") : "/";
    p = normDir(p);
    if (!safeRelPath(p)) { srv.send(400, F("text/plain"), F("Bad path")); return; }

    SdFile d;
    if (!d.open(p.c_str())) { srv.send(404, F("text/plain"), F("Not found")); return; }

    // Ensure empty
    SdFile e; bool empty = true;
    while (e.openNext(&d, O_READ)) { e.close(); empty = false; break; }
    d.close();
    if (!empty) { srv.send(409, F("text/plain"), F("Directory not empty")); return; }

    if (!sd->rmdir(p.c_str())) { srv.send(500, F("text/plain"), F("rmdir failed")); return; }

    srv.sendHeader(F("Location"), "/files?path=" + parentDir(p));
    srv.send(303);
  });

  // ---------- POST /upload?path=/dir (multipart streaming) ----------
  // onRequest (first lambda): called at the end → we redirect to the listing
  // onUpload (second lambda): receives the data chunks; we stream them to SD
  S->on("/upload", HTTP_POST,
    // onRequest
    [S](){
      auto& srv = *S;
      String p = srv.hasArg("path") ? srv.arg("path") : "/";
      if (!safeRelPath(p)) p = "/";
      srv.sendHeader(F("Location"), "/files?path=" + normDir(p));
      srv.send(303);
    },
    // onUpload
    [S](){
      auto& srv = *S;
      SdFat* sd = nullptr; if (!ensureSd_(sd)) return;

      HTTPUpload& up = srv.upload();
      static SdFile out;
      static String targetDir;

      if (up.status == UPLOAD_FILE_START) {
        targetDir = srv.hasArg("path") ? srv.arg("path") : "/";
        if (!safeRelPath(targetDir)) { up.status = UPLOAD_FILE_ABORTED; return; }
        const String full = normDir(targetDir) + String(up.filename.c_str());
        if (!out.open(full.c_str(), O_WRITE | O_CREAT | O_TRUNC)) {
          Serial.println(F("[FILES] upload: open failed"));
          up.status = UPLOAD_FILE_ABORTED;
          return;
        }
      } else if (up.status == UPLOAD_FILE_WRITE) {
        if (out.isOpen() && up.currentSize) out.write(up.buf, up.currentSize);
      } else if (up.status == UPLOAD_FILE_END) {
        if (out.isOpen()) out.close();
      } else if (up.status == UPLOAD_FILE_ABORTED) {
        if (out.isOpen()) { out.close(); /* optionally: sd->remove((normDir(targetDir)+up.filename).c_str()); */ }
      }
    }
  );
}
