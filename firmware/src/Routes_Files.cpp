#include "Routes_Files.h"
#include <Arduino.h>
#include <time.h>
#include <SdFat.h>
#include "SD_MMC.h"   // for SD_MMC backend

#include "HtmlUtil.h"
#include "WiFiManager.h"
#include "WebServerManager.h"
#include "DebugLog.h"

using namespace HtmlUtil;

#define FILES_LOGE(...) LOGE_TAG("FILES", __VA_ARGS__)

static bool ensureSd_(SdFs*& out) {
  out = WebServerManager::sd();
  if (!out) {
    FILES_LOGE("SdFat* is null (call WebServerManager::begin first)\n");
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

static String jsStringEscape_(const String& in) {
  String out;
  out.reserve(in.length() + 8);
  for (size_t i = 0; i < in.length(); ++i) {
    const char c = in[i];
    if (c == '\\') out += F("\\\\");
    else if (c == '\'') out += F("\\'");
    else if (c == '\n') out += F("\\n");
    else if (c == '\r') out += F("\\r");
    else if (c == '\t') out += F("\\t");
    else out += c;
  }
  return out;
}

static String urlEncodeQueryValue_(const String& in) {
  String out;
  out.reserve(in.length() * 3);
  static const char hex[] = "0123456789ABCDEF";
  for (size_t i = 0; i < in.length(); ++i) {
    const uint8_t c = (uint8_t)in[i];
    const bool unreserved =
      (c >= 'A' && c <= 'Z') ||
      (c >= 'a' && c <= 'z') ||
      (c >= '0' && c <= '9') ||
      c == '-' || c == '_' || c == '.' || c == '~' || c == '/';
    if (unreserved) {
      out += (char)c;
    } else {
      out += '%';
      out += hex[(c >> 4) & 0x0F];
      out += hex[c & 0x0F];
    }
  }
  return out;
}

static String dirOpenPath_(const String& dir) {
  if (dir.length() > 1 && dir.endsWith("/")) {
    return dir.substring(0, dir.length() - 1);
  }
  return dir;
}

static bool isFileInDir_(const String& filePath, const String& dirNorm) {
  // dirNorm is normalized directory (leading '/', trailing '/' unless root)
  const String p = filePath;
  if (!p.startsWith(dirNorm)) return false;
  // ensure no further '/' after dir prefix (i.e., current directory only)
  int slash = p.indexOf('/', dirNorm.length());
  return slash < 0;
}

// ---------- ZIP helpers (store-only ZIP with data descriptors) ----------

static uint32_t crc32_update_(uint32_t crc, const uint8_t* data, size_t len) {
  crc = ~crc;
  for (size_t i = 0; i < len; ++i) {
    crc ^= data[i];
    for (int k = 0; k < 8; ++k) {
      crc = (crc >> 1) ^ (0xEDB88320u & (-(int32_t)(crc & 1u)));
    }
  }
  return ~crc;
}

static void zipWrite_(WebServer& srv, const void* data, size_t len, uint32_t& bytesWritten) {
  srv.sendContent_P((const char*)data, len);
  bytesWritten += (uint32_t)len;
}

static void zipWriteU16_(WebServer& srv, uint16_t v, uint32_t& bytesWritten) {
  uint8_t b[2] = { (uint8_t)(v & 0xFF), (uint8_t)((v >> 8) & 0xFF) };
  zipWrite_(srv, b, 2, bytesWritten);
}

static void zipWriteU32_(WebServer& srv, uint32_t v, uint32_t& bytesWritten) {
  uint8_t b[4] = {
    (uint8_t)(v & 0xFF),
    (uint8_t)((v >> 8) & 0xFF),
    (uint8_t)((v >> 16) & 0xFF),
    (uint8_t)((v >> 24) & 0xFF),
  };
  zipWrite_(srv, b, 4, bytesWritten);
}

static void zipDosTimeDate_(uint16_t& dosTime, uint16_t& dosDate) {
  time_t now = time(nullptr);
  if (now <= 100000) { // likely not set
    dosTime = 0;
    dosDate = 0;
    return;
  }
  struct tm t;
  localtime_r(&now, &t);
  // DOS time: bits 0-4 sec/2, 5-10 min, 11-15 hour
  dosTime = (uint16_t)(((t.tm_sec / 2) & 0x1F) | ((t.tm_min & 0x3F) << 5) | ((t.tm_hour & 0x1F) << 11));
  // DOS date: bits 0-4 day, 5-8 month, 9-15 years since 1980
  int year = t.tm_year + 1900;
  if (year < 1980) year = 1980;
  dosDate = (uint16_t)((t.tm_mday & 0x1F) | (((t.tm_mon + 1) & 0x0F) << 5) | (((year - 1980) & 0x7F) << 9));
}

static String makeZipName_() {
  time_t now = time(nullptr);
  if (now > 100000) {
    struct tm t;
    localtime_r(&now, &t);
    char buf[32];
    // YYYY-MM-DD_HH-MM-SS.zip
    snprintf(buf, sizeof(buf), "%04d-%02d-%02d_%02d-%02d-%02d.zip",
             t.tm_year + 1900, t.tm_mon + 1, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec);
    return String(buf);
  }
  return String("bodaqs_") + String(millis()) + String(".zip");
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

    html += F("<tr><td></td><td>📁 <a href=\"/files?path=");
    html += htmlEscape(urlEncodeQueryValue_(normDir(dir) + String(name) + "/"));
    html += F("\">");
    html += htmlEscape(String(name));
    html += F("</a></td><td>-</td><td>"
              "<a class='delete' href=\"/rmdir?path=");
    html += htmlEscape(urlEncodeQueryValue_(normDir(dir) + String(name) + "/"));
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
    html += F("<tr><td><input type='checkbox' class='filecb' name='path' value='");
    html += htmlEscape(urlEncodeQueryValue_(full));
    html += F("'></td><td>");
    html += htmlEscape(String(name));
    html += F("</td><td>");
    html += prettySize_(sz);
    html += F("</td><td>"
              "<a class='download' href=\"/download?path=");
    html += htmlEscape(urlEncodeQueryValue_(full));
    html += F("\">Download</a> "
              "<a class='delete' href=\"/delete?path=");
    html += htmlEscape(urlEncodeQueryValue_(full));
    html += F("\">Delete</a></td></tr>");

    e.close();
    delay(0);
  }

  d.close();
}

// SD_MMC version of directory listing (same HTML as listDir_ for SdFat) (same HTML as listDir_ for SdFat)
static void listDirMMC_(const String& dir, String& html) {
  const String openDir = dirOpenPath_(dir);
  File d = SD_MMC.open(openDir.c_str());
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

        html += F("<tr><td></td><td>📁 <a href=\"/files?path=");
        html += htmlEscape(urlEncodeQueryValue_(normDir(dir) + name + "/"));
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
  d = SD_MMC.open(openDir.c_str());
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
        html += F("<tr><td><input type='checkbox' class='filecb' name='path' value='");
        html += htmlEscape(urlEncodeQueryValue_(full));
        html += F("'></td><td>");
        html += htmlEscape(name);
        html += F("</td><td>");
        html += prettySize_(sz);
        html += F("</td><td>"
                  "<a class='download' href=\"/download?path=");
        html += htmlEscape(urlEncodeQueryValue_(full));
        html += F("\">Download</a> "
                  "<a class='delete' href=\"/delete?path=");
        html += htmlEscape(urlEncodeQueryValue_(full));
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
      html += htmlEscape(urlEncodeQueryValue_(acc));
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
    html += htmlEscape(urlEncodeQueryValue_(dir));
    html += F("' enctype='multipart/form-data' style='margin:8px 0'>"
             "<input type='file' name='file' multiple>"
             "<button type='submit'>Upload</button></form>");

    // New folder form
    html += F("<form method='POST' action='/mkdir' style='margin:8px 0'>"
              "<input type='hidden' name='path' value='");
    html += htmlEscape(urlEncodeQueryValue_(dir));
    html += F("'>"
              "<input type='text' name='name' placeholder='New folder name'> "
              "<button type='submit'>Create</button></form>");

    // Parent link
    if (dir != "/") {
      html += F("<p><a href='/files?path=");
      html += htmlEscape(urlEncodeQueryValue_(parentDir(dir)));
      html += F("'>⬆ Parent</a></p>");
    }

    // Multi-select actions (files only, current dir only)
    html += F("<div style='margin:10px 0'>"
              "<button type='button' id='btn_download' disabled>Download selected</button> "
              "<button type='button' id='btn_zip' disabled>Download ZIP</button> "
              "<button type='button' id='btn_delete' disabled class='delete'>Delete selected</button> "
              "<span id='dl_status' style='margin-left:10px'></span>"
              "</div>");

    html += F("<form id='multiForm' method='POST'>");
    html += F("<input type='hidden' name='dir' value='");
    html += htmlEscape(urlEncodeQueryValue_(dir));
    html += F("'>");

    // Table
    html += F("<table>"
              "<tr>"
              "<th style='width:40px'><input type='checkbox' id='sel_all'></th>"
              "<th>Name</th><th>Size</th><th>Action</th>"
              "</tr>");
    if (useSpi) {
      listDir_(sd, dir, html);
    } else {
      listDirMMC_(dir, html);
    }
    html += F("</table></form>");
    html += F("<iframe name='zipframe' style='display:none'></iframe>");

    // Inline JS: select all, enable/disable buttons, submit actions
    html += F("<script>"
              "(function(){"
              "const form=document.getElementById('multiForm');"
              "const selAll=document.getElementById('sel_all');"
              "const btnDl=document.getElementById('btn_download');"
              "const btnDel=document.getElementById('btn_delete');const btnZip=document.getElementById('btn_zip');"
              "function cbs(){return Array.from(document.querySelectorAll('.filecb'));}"
              "function anyChecked(){return cbs().some(cb=>cb.checked);}"
              "function refresh(){const any=anyChecked(); btnDl.disabled=!any; if(btnZip) btnZip.disabled=!any; btnDel.disabled=!any;}"
              "if(selAll){selAll.addEventListener('change',()=>{cbs().forEach(cb=>cb.checked=selAll.checked); refresh();});}"
              "document.addEventListener('change',(e)=>{if(e.target && e.target.classList && e.target.classList.contains('filecb')){"
              "const all=cbs(); if(selAll){ selAll.checked = all.length && all.every(cb=>cb.checked); } refresh(); }});"
              "btnDl.addEventListener('click',async()=>{btnDl.disabled=true; if(btnZip) btnZip.disabled=true; btnDel.disabled=true; if(selAll) selAll.disabled=true;const status=document.getElementById('dl_status');const paths=cbs().filter(cb=>cb.checked).map(cb=>cb.value);if(!paths.length){refresh(); if(selAll) selAll.disabled=false; return;}if(status) status.textContent='Starting...';for(let i=0;i<paths.length;i++){const p=paths[i];const name=(p.split('/').pop()||p);if(status) status.textContent=`Fetching ${i+1}/${paths.length}: ${name}`;try{const url='/download?path='+encodeURIComponent(p);const resp=await fetch(url,{cache:'no-store'});if(!resp.ok) throw new Error('HTTP '+resp.status);const cd=resp.headers.get('Content-Disposition')||'';let fn=name;const mm=/filename\s*=\s*\"?([^\";]+)\"?/i.exec(cd);if(mm && mm[1]) fn=mm[1];const blob=await resp.blob();const a=document.createElement('a');const obj=URL.createObjectURL(blob);a.href=obj; a.download=fn; a.style.display='none';document.body.appendChild(a); a.click();setTimeout(()=>{URL.revokeObjectURL(obj); a.remove();},1500);}catch(err){console.error('Download failed for',p,err);if(status) status.textContent=`Failed: ${name}`;break;}await new Promise(r=>setTimeout(r,300));}if(status && !status.textContent.startsWith('Failed')) status.textContent='Done';refresh(); if(selAll) selAll.disabled=false;});"
              "if(btnZip){btnZip.addEventListener('click',()=>{btnDl.disabled=true; btnZip.disabled=true; btnDel.disabled=true; if(selAll) selAll.disabled=true; const prevAction=form.action; const prevTarget=form.target; form.action='/download_zip'; form.target='zipframe'; form.submit(); form.action=prevAction; form.target=prevTarget; setTimeout(()=>{refresh(); if(selAll) selAll.disabled=false;},500);});}btnDel.addEventListener('click',()=>{form.action='/delete_multi'; form.submit();});"
              "refresh();"
              "})();"
              "</script>");

    html += F("<p><a href='/'>Home</a></p>");
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

  srv.sendHeader(F("Location"), "/files?path=" + urlEncodeQueryValue_(parentDir(path)));
  srv.send(303, F("text/plain"), F("Deleted"));
});




// ---------- POST /download_multi (paths[]=...) ----------
// Returns an HTML page that sequentially triggers individual downloads via /download?path=...
S->on("/download_multi", HTTP_POST, [S](){
  auto& srv = *S;
  WiFiManager::noteUserActivity();

  String dir = srv.hasArg("dir") ? srv.arg("dir") : "/";
  if (!safeRelPath(dir)) { dir = "/"; }
  dir = normDir(dir);

  // Collect selected paths (repeated "path" args)
  String jsArray = "";
  jsArray.reserve(512);
  int nSel = 0;

  const int ac = srv.args();
  for (int i = 0; i < ac; ++i) {
    if (srv.argName(i) != "path") continue;
    String p = srv.arg(i);
    if (!safeRelPath(p)) continue;
    if (p.endsWith("/")) continue; // files only
    if (!isFileInDir_(p, dir)) continue; // current directory only
    if (nSel >= 40) break;

    if (nSel) jsArray += ",";
    jsArray += "'";
    jsArray += jsStringEscape_(p);
    jsArray += "'";
    ++nSel;
  }

  String html = htmlHeader(F("Download selected"));
  html += F("<h2>Download selected</h2>");

  if (nSel == 0) {
    html += F("<p>No files selected.</p><p><a href='/files?path=");
    html += htmlEscape(urlEncodeQueryValue_(dir));
    html += F("'>Back</a></p>");
    html += htmlFooter();
    srv.send(200, F("text/html"), html);
    return;
  }

  html += F("<p>Starting ");
  html += String(nSel);
  html += F(" download(s)...</p>");
  html += F("<p>If your browser asks, allow multiple downloads for this site.</p>");

  html += F("<script>(function(){");
  html += F("const files=[");
  html += jsArray;
  html += F("];");
  html += F("let i=0;");
  html += F("function trigger(p){"
            "const a=document.createElement('a');"
            "a.href='/download?path='+encodeURIComponent(p);"
            "a.download='';"
            "document.body.appendChild(a);"
            "a.click();"
            "document.body.removeChild(a);"
            "}");
  // Throttled loop; cannot reliably detect download completion in browser JS.
  html += F("function next(){"
            "if(i>=files.length){window.location='/files?path=");
  html += jsStringEscape_(urlEncodeQueryValue_(dir));
  html += F("'; return;}"
            "trigger(files[i]);"
            "i++;"
            "setTimeout(next,700);"
            "}"
            "window.addEventListener('load', next);"
            "})();</script>");

  html += F("<p><a href='/files?path=");
  html += htmlEscape(urlEncodeQueryValue_(dir));
  html += F("'>Back to files</a></p>");
  html += htmlFooter();

  srv.send(200, F("text/html"), html);
});


// ---------- POST /delete_multi (best-effort, confirm step) ----------
S->on("/delete_multi", HTTP_POST, [S](){
  auto& srv = *S;
  WiFiManager::noteUserActivity();

  SdFat* sd = WebServerManager::sd();
  const bool useSpi = (sd != nullptr);

  String dir = srv.hasArg("dir") ? srv.arg("dir") : "/";
  if (!safeRelPath(dir)) { dir = "/"; }
  dir = normDir(dir);

  const bool confirmed = srv.hasArg("confirm") && srv.arg("confirm") == "1";

  // Collect selected paths (repeated "path" args)
  String paths[40];
  int nSel = 0;
  const int ac = srv.args();
  for (int i = 0; i < ac; ++i) {
    if (srv.argName(i) != "path") continue;
    String p = srv.arg(i);
    if (!safeRelPath(p)) continue;
    if (p.endsWith("/")) continue; // files only
    if (!isFileInDir_(p, dir)) continue; // current directory only
    if (nSel >= 40) break;
    paths[nSel++] = p;
  }

  if (nSel == 0) {
    String html = htmlHeader(F("Delete selected"));
    html += F("<h2>Delete selected</h2><p>No files selected.</p><p><a href='/files?path=");
    html += htmlEscape(urlEncodeQueryValue_(dir));
    html += F("'>Back</a></p>");
    html += htmlFooter();
    srv.send(200, F("text/html"), html);
    return;
  }

  if (!confirmed) {
    String html = htmlHeader(F("Confirm delete"));
    html += F("<h2>Confirm delete</h2>");
    html += F("<p>Delete the following file(s)?</p><ul>");
    for (int i = 0; i < nSel; ++i) {
      html += F("<li><code>");
      html += htmlEscape(paths[i]);
      html += F("</code></li>");
    }
    html += F("</ul>");

    html += F("<form method='POST' action='/delete_multi'>");
    html += F("<input type='hidden' name='dir' value='");
    html += htmlEscape(dir);
    html += F("'>");
    html += F("<input type='hidden' name='confirm' value='1'>");
    for (int i = 0; i < nSel; ++i) {
      html += F("<input type='hidden' name='path' value='");
      html += htmlEscape(paths[i]);
      html += F("'>");
    }
    html += F("<button type='submit' class='delete'>Yes, delete</button> ");
    html += F("<a href='/files?path=");
    html += htmlEscape(urlEncodeQueryValue_(dir));
    html += F("'>Cancel</a></form>");
    html += htmlFooter();
    srv.send(200, F("text/html"), html);
    return;
  }

  // Confirmed: delete best-effort
  int okCount = 0;
  int failCount = 0;

  String html = htmlHeader(F("Delete results"));
  html += F("<h2>Delete results</h2>");
  html += F("<table><tr><th>File</th><th>Status</th></tr>");

  for (int i = 0; i < nSel; ++i) {
    const String& p = paths[i];

    bool exists = false;
    bool removed = false;

    if (useSpi) {
      exists = sd->exists(p.c_str());
      if (exists) removed = sd->remove(p.c_str());
    } else {
      exists = SD_MMC.exists(p.c_str());
      if (exists) removed = SD_MMC.remove(p.c_str());
    }

    html += F("<tr><td><code>");
    html += htmlEscape(p);
    html += F("</code></td><td>");

    if (!exists) {
      html += F("<span style='color:#b00'>Missing</span>");
      ++failCount;
    } else if (!removed) {
      html += F("<span style='color:#b00'>Failed</span>");
      ++failCount;
    } else {
      html += F("<span style='color:#060'>Deleted</span>");
      ++okCount;
    }

    html += F("</td></tr>");
    delay(0);
  }

  html += F("</table>");
  html += F("<p>Deleted: ");
  html += String(okCount);
  html += F(" &nbsp; Failed: ");
  html += String(failCount);
  html += F("</p>");
  html += F("<p><a href='/files?path=");
  html += htmlEscape(urlEncodeQueryValue_(dir));
  html += F("'>Back to files</a></p>");
  html += htmlFooter();

  srv.send(200, F("text/html"), html);
});

// ---------- GET /rmdir?path=/dir/ [confirm=1] ----------

  // ---------- POST /download_zip (selected files in current dir; store-only ZIP) ----------
  S->on("/download_zip", HTTP_POST, [S](){
    auto& srv = *S;
    WiFiManager::noteUserActivity();

    SdFat* sd = WebServerManager::sd();
    const bool useSpi = (sd != nullptr);

    String dir = srv.hasArg("dir") ? srv.arg("dir") : "/";
    if (!safeRelPath(dir)) { dir = "/"; }
    dir = normDir(dir);

    // Collect selected paths (repeated "path" args)
    String paths[40];
    int nSel = 0;
    const int ac = srv.args();
    for (int i = 0; i < ac; ++i) {
      if (srv.argName(i) != "path") continue;
      String p = srv.arg(i);
      if (!safeRelPath(p)) continue;
      if (p.endsWith("/")) continue;             // files only
      if (!isFileInDir_(p, dir)) continue;       // current directory only
      if (nSel >= 40) break;
      paths[nSel++] = p;
    }

    if (nSel == 0) {
      String html = htmlHeader(F("Download ZIP"));
      html += F("<h2>Download ZIP</h2><p>No files selected.</p><p><a href='/files?path=");
      html += htmlEscape(urlEncodeQueryValue_(dir));
      html += F("'>Back</a></p>");
      html += htmlFooter();
      srv.send(200, F("text/html"), html);
      return;
    }

    // Prepare response headers
    const String zipName = makeZipName_();
    srv.sendHeader(F("Content-Type"), F("application/zip"));
    srv.sendHeader(F("Cache-Control"), F("no-store"));
    srv.sendHeader(F("Content-Disposition"), String(F("attachment; filename=\"")) + zipName + F("\""));
    srv.setContentLength(CONTENT_LENGTH_UNKNOWN);

    // Start streaming body
    srv.send(200, F("application/zip"), "");

    uint16_t dosTime = 0, dosDate = 0;
    zipDosTimeDate_(dosTime, dosDate);

    struct EntryMeta {
      String name;
      uint32_t crc;
      uint32_t size;
      uint32_t localOffset;
    };
    EntryMeta meta[40];

    uint32_t bytesWritten = 0;

    static uint8_t buf[2048];

    // Write each local file entry + data descriptor
    for (int i = 0; i < nSel; ++i) {
      const String& fullPath = paths[i];
      const String baseName = fullPath.substring(fullPath.lastIndexOf('/') + 1);

      meta[i].name = baseName;
      meta[i].crc = 0;
      meta[i].size = 0;
      meta[i].localOffset = bytesWritten;

      // Local file header
      zipWriteU32_(srv, 0x04034b50u, bytesWritten);   // signature
      zipWriteU16_(srv, 20, bytesWritten);           // version needed
      zipWriteU16_(srv, 0x0008, bytesWritten);       // flags: data descriptor present
      zipWriteU16_(srv, 0, bytesWritten);            // method: store
      zipWriteU16_(srv, dosTime, bytesWritten);      // mod time
      zipWriteU16_(srv, dosDate, bytesWritten);      // mod date
      zipWriteU32_(srv, 0, bytesWritten);            // crc (0; in descriptor)
      zipWriteU32_(srv, 0, bytesWritten);            // comp size (0; in descriptor)
      zipWriteU32_(srv, 0, bytesWritten);            // uncomp size (0; in descriptor)
      zipWriteU16_(srv, (uint16_t)baseName.length(), bytesWritten); // name len
      zipWriteU16_(srv, 0, bytesWritten);            // extra len

      zipWrite_(srv, baseName.c_str(), baseName.length(), bytesWritten);

      // File data
      uint32_t crc = 0;
      uint32_t size = 0;

      if (useSpi) {
        SdFile f;
        if (f.open(fullPath.c_str(), O_READ)) {
          int32_t n;
          while ((n = f.read(buf, sizeof(buf))) > 0) {
            crc = crc32_update_(crc, buf, (size_t)n);
            size += (uint32_t)n;
            zipWrite_(srv, buf, (size_t)n, bytesWritten);
            delay(0);
          }
          f.close();
        }
      } else {
        File f = SD_MMC.open(fullPath.c_str(), FILE_READ);
        if (f) {
          int32_t n;
          while ((n = f.read(buf, sizeof(buf))) > 0) {
            crc = crc32_update_(crc, buf, (size_t)n);
            size += (uint32_t)n;
            zipWrite_(srv, buf, (size_t)n, bytesWritten);
            delay(0);
          }
          f.close();
        }
      }

      meta[i].crc = crc;
      meta[i].size = size;

      // Data descriptor (with signature)
      zipWriteU32_(srv, 0x08074b50u, bytesWritten);
      zipWriteU32_(srv, crc, bytesWritten);
      zipWriteU32_(srv, size, bytesWritten); // comp size = size (store)
      zipWriteU32_(srv, size, bytesWritten); // uncomp size
    }

    // Central directory
    const uint32_t centralStart = bytesWritten;

    for (int i = 0; i < nSel; ++i) {
      const String& name = meta[i].name;

      zipWriteU32_(srv, 0x02014b50u, bytesWritten);    // central sig
      zipWriteU16_(srv, 20, bytesWritten);             // version made by
      zipWriteU16_(srv, 20, bytesWritten);             // version needed
      zipWriteU16_(srv, 0x0008, bytesWritten);         // flags
      zipWriteU16_(srv, 0, bytesWritten);              // method store
      zipWriteU16_(srv, dosTime, bytesWritten);
      zipWriteU16_(srv, dosDate, bytesWritten);
      zipWriteU32_(srv, meta[i].crc, bytesWritten);
      zipWriteU32_(srv, meta[i].size, bytesWritten);   // comp size
      zipWriteU32_(srv, meta[i].size, bytesWritten);   // uncomp size
      zipWriteU16_(srv, (uint16_t)name.length(), bytesWritten); // name len
      zipWriteU16_(srv, 0, bytesWritten);              // extra len
      zipWriteU16_(srv, 0, bytesWritten);              // comment len
      zipWriteU16_(srv, 0, bytesWritten);              // disk start
      zipWriteU16_(srv, 0, bytesWritten);              // internal attrs
      zipWriteU32_(srv, 0, bytesWritten);              // external attrs
      zipWriteU32_(srv, meta[i].localOffset, bytesWritten); // local header offset
      zipWrite_(srv, name.c_str(), name.length(), bytesWritten);
    }

    const uint32_t centralSize = bytesWritten - centralStart;

    // End of central directory
    zipWriteU32_(srv, 0x06054b50u, bytesWritten);
    zipWriteU16_(srv, 0, bytesWritten);                // disk number
    zipWriteU16_(srv, 0, bytesWritten);                // start disk
    zipWriteU16_(srv, (uint16_t)nSel, bytesWritten);   // entries on this disk
    zipWriteU16_(srv, (uint16_t)nSel, bytesWritten);   // total entries
    zipWriteU32_(srv, centralSize, bytesWritten);      // central dir size
    zipWriteU32_(srv, centralStart, bytesWritten);     // central dir offset
    zipWriteU16_(srv, 0, bytesWritten);                // comment len
  });

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
    html += htmlEscape(urlEncodeQueryValue_(p));
    html += F("&confirm=1'>Yes, remove</a> &nbsp; "
              "<a href='/files?path=");
    html += htmlEscape(urlEncodeQueryValue_(parentDir(p)));
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
    const String openPath = dirOpenPath_(p);
    File d = SD_MMC.open(openPath.c_str());
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

  srv.sendHeader(F("Location"), "/files?path=" + urlEncodeQueryValue_(parentDir(p)));
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

  srv.sendHeader(F("Location"), "/files?path=" + urlEncodeQueryValue_(normDir(base)));
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
    const String openPath = dirOpenPath_(p);
    File d = SD_MMC.open(openPath.c_str());
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

  srv.sendHeader(F("Location"), "/files?path=" + urlEncodeQueryValue_(parentDir(p)));
  srv.send(303);
});


  // ---------- POST /upload (multipart form, single or multiple files) ----------
  S->on("/upload", HTTP_POST,
    // onRequest: just redirect back to /files
    [S](){
      auto& srv = *S;
      String p = srv.hasArg("path") ? srv.arg("path") : "/";
      if (!safeRelPath(p)) p = "/";
  srv.sendHeader(F("Location"), "/files?path=" + urlEncodeQueryValue_(normDir(p)));
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
            FILES_LOGE("upload: SPI open failed\n");
            up.status = UPLOAD_FILE_ABORTED;
            return;
          }
        } else {
          outMMC = SD_MMC.open(full.c_str(), FILE_WRITE);
          if (!outMMC) {
            FILES_LOGE("upload: SD_MMC open failed\n");
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
