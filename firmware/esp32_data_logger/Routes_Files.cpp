#include "Routes_Files.h"
#include <Arduino.h>
#include <SdFat.h>
#include "SD_MMC.h"   // for SD_MMC backend

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

// Get the last path segment (strip leading directories)
static String baseName_(const String& path) {
  int slash = path.lastIndexOf('/');
  if (slash >= 0 && slash + 1 < (int)path.length()) {
    return path.substring(slash + 1);
  }
  return path;
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

// SD_MMC version of directory listing (same HTML as listDir_ for SdFat)
static void listDirMMC_(const String& dir, String& html) {
  File d = SD_MMC.open(dir.c_str());
  if (!d || !d.isDirectory()) {
    html += F("<p>Failed to open directory.</p>");
    if (d) d.close();
    return;
  }

  // --- Folders first ---
  {
    File e = d.openNextFile();
    while (e) {
      if (e.isDirectory()) {
        String fullName = e.name();  // may include path
        String name = baseName_(fullName);
        if (name == "." || name == "..") {
          e.close();
          e = d.openNextFile();
          continue;
        }

        html += F("<tr><td>📁 <a href=\"/files?path=");
        html += htmlEscape(normDir(dir) + name + "/");
        html += F("\">");
        html += htmlEscape(name);
        html += F("</a></td><td>-</td><td>-</td></tr>");

        e.close();
      } else {
        e.close();
      }
      delay(0);
      e = d.openNextFile();
    }
    d.close();
  }

  // --- Files ---
  d = SD_MMC.open(dir.c_str());
  if (!d || !d.isDirectory()) {
    if (d) d.close();
    return;
  }

  {
    File e = d.openNextFile();
    while (e) {
      if (!e.isDirectory()) {
        String fullName = e.name();
        String name = baseName_(fullName);
        uint32_t sz = e.size();

        const String full = normDir(dir) + name;
        html += F("<tr><td>");
        html += htmlEscape(name);
        html += F("</td><td>");
        html += prettySize_(sz);
        html += F("</td><td>"
                  "<a class='download' href=\"/download?path=");
        html += htmlEscape(full);
        html += F("\">Download</a> "
                  "<a class='delete' href=\"/delete?path=");
        html += htmlEscape(full);
        html += F("\">Delete</a></td></tr>");
      }
      e.close();
      delay(0);
      e = d.openNextFile();
    }
    d.close();
  }
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

    // Determine backend: if WebServerManager::sd() is non-null, we're on SPI/SdFat.
    SdFat* sd = WebServerManager::sd();
    const bool useSpi = (sd != nullptr);

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
    if (useSpi) {
      listDir_(sd, dir, html);
    } else {
      listDirMMC_(dir, html);
    }
    html += F("</table><p><a href='/'>Home</a></p>");
    html += htmlFooter();

    srv.send(200, F("text/html"), html);
  });


// ---------- GET /download?path=/dir/file ----------
S->on("/download", HTTP_GET, [S](){
  auto& srv = *S;
  WiFiManager::noteUserActivity();

  SdFat* sd = WebServerManager::sd();
  bool useSpi = (sd != nullptr);

  if (!srv.hasArg("path")) {
    srv.send(400, F("text/plain"), F("Missing 'path'"));
    return;
  }

  String path = srv.arg("path");
  if (!safeRelPath(path)) {
    srv.send(400, F("text/plain"), F("Bad path"));
    return;
  }

  // Open file
  bool ok = false;

  // Prepare headers
  const String filename = path.substring(path.lastIndexOf('/') + 1);
  String ctype = contentTypeFor(path);
  String hdr = String(F("attachment; filename=\"")) + filename + F("\"");
  srv.sendHeader(F("Content-Disposition"), hdr);
  srv.setContentLength(CONTENT_LENGTH_UNKNOWN);

  static uint8_t buf[2048];
  int32_t n;

  if (useSpi) {
    SdFile f;
    if (!f.open(path.c_str(), O_READ)) {
      srv.send(404, F("text/plain"), F("Not found"));
      return;
    }
    srv.send(200, ctype, "");
    while ((n = f.read(buf, sizeof(buf))) > 0) {
      srv.sendContent_P((const char*)buf, n);
      delay(0);
    }
    f.close();
    ok = true;
  } else {
    File f = SD_MMC.open(path.c_str(), FILE_READ);
    if (!f) {
      srv.send(404, F("text/plain"), F("Not found"));
      return;
    }
    srv.send(200, ctype, "");
    while ((n = f.read(buf, sizeof(buf))) > 0) {
      srv.sendContent_P((const char*)buf, n);
      delay(0);
    }
    f.close();
    ok = true;
  }

  if (ok) {
    srv.sendContent(""); // end chunked
  }
});


// ---------- GET /delete?path=/dir/file ----------
S->on("/delete", HTTP_GET, [S](){
  auto& srv = *S;
  WiFiManager::noteUserActivity();

  SdFat* sd = WebServerManager::sd();
  bool useSpi = (sd != nullptr);

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

  if (!exists) {
    srv.send(404, F("text/plain"), F("Not found"));
    return;
  }
  if (!removed) {
    srv.send(500, F("text/plain"), F("Delete failed"));
    return;
  }

  srv.sendHeader(F("Location"), "/files?path=" + parentDir(path));
  srv.send(303, F("text/plain"), F("Deleted"));
});


// ---------- GET /rmdir?path=/dir/ [confirm=1] ----------
S->on("/rmdir", HTTP_GET, [S](){
  auto& srv = *S;
  WiFiManager::noteUserActivity();

  SdFat* sd = WebServerManager::sd();
  bool useSpi = (sd != nullptr);

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

  // Ensure empty directory
  bool empty = true;
  bool existsDir = false;

  if (useSpi) {
    SdFile d;
    if (!d.open(p.c_str())) {
      srv.send(404, F("text/plain"), F("Not found"));
      return;
    }
    existsDir = true;
    SdFile e;
    while (e.openNext(&d, O_READ)) {
      e.close();
      empty = false;
      break;
    }
    d.close();
  } else {
    File d = SD_MMC.open(p.c_str());
    if (!d || !d.isDirectory()) {
      if (d) d.close();
      srv.send(404, F("text/plain"), F("Not found"));
      return;
    }
    existsDir = true;
    File e = d.openNextFile();
    if (e) {
      e.close();
      empty = false;
    }
    d.close();
  }

  if (!existsDir) {
    srv.send(404, F("text/plain"), F("Not found"));
    return;
  }
  if (!empty) {
    srv.send(409, F("text/plain"), F("Directory not empty"));
    return;
  }

  bool ok = false;
  if (useSpi) {
    ok = sd->rmdir(p.c_str());
  } else {
    ok = SD_MMC.rmdir(p.c_str());
  }

  if (!ok) {
    srv.send(500, F("text/plain"), F("rmdir failed"));
    return;
  }

  srv.sendHeader(F("Location"), "/files?path=" + parentDir(p));
  srv.send(303, F("text/plain"), F("Removed"));
});

// ---------- POST /mkdir (path + name) ----------
S->on("/mkdir", HTTP_POST, [S](){
  auto& srv = *S;
  WiFiManager::noteUserActivity();

  SdFat* sd = WebServerManager::sd();
  bool useSpi = (sd != nullptr);

  const String base = srv.hasArg("path") ? srv.arg("path") : "/";
  const String name = srv.hasArg("name") ? srv.arg("name") : "";

  if (!safeRelPath(normDir(base))) { srv.send(400, F("text/plain"), F("Bad path")); return; }
  if (!name.length() || name.indexOf('/') >= 0 || name.indexOf('\\') >= 0) {
    srv.send(400, F("text/plain"), F("Bad folder name"));
    return;
  }

  const String full = normDir(base) + name + "/";

  bool ok = false;
  if (useSpi) {
    ok = sd->mkdir(full.c_str());
  } else {
    ok = SD_MMC.mkdir(full.c_str());
  }

  if (!ok) {
    srv.send(500, F("text/plain"), F("mkdir failed"));
    return;
  }

  srv.sendHeader(F("Location"), "/files?path=" + normDir(base));
  srv.send(303);
});


// ---------- POST /rmdir (path) (empty dirs only) ----------
S->on("/rmdir", HTTP_POST, [S](){
  auto& srv = *S;
  WiFiManager::noteUserActivity();

  SdFat* sd = WebServerManager::sd();
  bool useSpi = (sd != nullptr);

  String p = srv.hasArg("path") ? srv.arg("path") : "/";
  p = normDir(p);
  if (!safeRelPath(p)) { srv.send(400, F("text/plain"), F("Bad path")); return; }

  bool empty = true;
  bool existsDir = false;

  if (useSpi) {
    SdFile d;
    if (!d.open(p.c_str())) { srv.send(404, F("text/plain"), F("Not found")); return; }
    existsDir = true;
    SdFile e; 
    while (e.openNext(&d, O_READ)) { e.close(); empty = false; break; }
    d.close();
  } else {
    File d = SD_MMC.open(p.c_str());
    if (!d || !d.isDirectory()) {
      if (d) d.close();
      srv.send(404, F("text/plain"), F("Not found"));
      return;
    }
    existsDir = true;
    File e = d.openNextFile();
    if (e) { e.close(); empty = false; }
    d.close();
  }

  if (!existsDir) {
    srv.send(404, F("text/plain"), F("Not found"));
    return;
  }
  if (!empty) {
    srv.send(409, F("text/plain"), F("Directory not empty"));
    return;
  }

  bool ok = false;
  if (useSpi) {
    ok = sd->rmdir(p.c_str());
  } else {
    ok = SD_MMC.rmdir(p.c_str());
  }

  if (!ok) {
    srv.send(500, F("text/plain"), F("rmdir failed"));
    return;
  }

  srv.sendHeader(F("Location"), "/files?path=" + parentDir(p));
  srv.send(303);
});


  // ---------- POST /upload (multipart form, single or multiple files) ----------
  S->on("/upload", HTTP_POST,
    // onRequest: just redirect back to /files
    [S](){
      auto& srv = *S;
      String p = srv.hasArg("path") ? srv.arg("path") : "/";
      if (!safeRelPath(p)) p = "/";
      srv.sendHeader(F("Location"), "/files?path=" + normDir(p));
      srv.send(303);
    },
    // onUpload: stream file data to SD (SPI or SD_MMC)
    [S](){
      auto& srv = *S;

      // Decide backend once per upload
      SdFat* sd = WebServerManager::sd();
      static bool useSpi = false;

      HTTPUpload& up = srv.upload();
      static SdFile outSpi;
      static File   outMMC;
      static String targetDir;

      if (up.status == UPLOAD_FILE_START) {
        // Determine target directory
        targetDir = srv.hasArg("path") ? srv.arg("path") : "/";
        if (!safeRelPath(targetDir)) {
          up.status = UPLOAD_FILE_ABORTED;
          return;
        }

        const String full = normDir(targetDir) + String(up.filename.c_str());
        useSpi = (sd != nullptr);

        if (useSpi) {
          if (!outSpi.open(full.c_str(), O_WRITE | O_CREAT | O_TRUNC)) {
            Serial.println(F("[FILES] upload: SPI open failed"));
            up.status = UPLOAD_FILE_ABORTED;
            return;
          }
        } else {
          outMMC = SD_MMC.open(full.c_str(), FILE_WRITE);
          if (!outMMC) {
            Serial.println(F("[FILES] upload: SD_MMC open failed"));
            up.status = UPLOAD_FILE_ABORTED;
            return;
          }
        }
      }
      else if (up.status == UPLOAD_FILE_WRITE) {
        if (up.currentSize) {
          if (useSpi) {
            if (outSpi.isOpen()) {
              outSpi.write(up.buf, up.currentSize);
            }
          } else {
            if (outMMC) {
              outMMC.write(up.buf, up.currentSize);
            }
          }
        }
      }
      else if (up.status == UPLOAD_FILE_END) {
        if (useSpi) {
          if (outSpi.isOpen()) {
            outSpi.close();
          }
        } else {
          if (outMMC) {
            outMMC.close();
          }
        }
      }
      else if (up.status == UPLOAD_FILE_ABORTED) {
        if (useSpi) {
          if (outSpi.isOpen()) {
            outSpi.close();
            // Optional: remove partial file here if you like
            // SdFat can't easily remove by open handle; you’d need
            // to track the full path separately.
          }
        } else {
          if (outMMC) {
            outMMC.close();
            // Optional: SD_MMC.remove((normDir(targetDir)+up.filename).c_str());
          }
        }
      }
    }
  );
}
