#include "HtmlUtil.h"

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
    if (n.endsWith(".txt"))  return F("text/plain");
    if (n.endsWith(".json")) return F("application/json");
    if (n.endsWith(".htm") || n.endsWith(".html")) return F("text/html");
    return F("application/octet-stream");
  }

  String htmlHeader(const String& title) {
    String s = F("<!DOCTYPE html><html><head><meta charset='utf-8'>");
    s += F("<meta name='viewport' content='width=device-width, initial-scale=1'>");
    s += "<title>" + title + "</title>";
    s += s += F("<style>"
        /* page */
        "body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;"
          "font-size:14px;line-height:1.35;color:#333;margin:20px}"
        "h2{margin-top:1.6em;padding-bottom:.2em;border-bottom:1px solid #ccc;font-size:1.1em}"

        /* containers */
        "fieldset{margin:1.2em 0;padding:1em 1.2em;border:1px solid #ddd;border-radius:6px;background:#fafafa}"
        "legend{font-weight:700;padding:0 6px}"

        /* rows & controls */
        ".row{margin:.4em 0}"
        "label{display:inline-block;min-width:160px;margin:.4em 0;font-weight:500}"
        "input,select{margin:.3em 0;padding:.3em .4em;border:1px solid #bbb;border-radius:4px;font-size:.95em}"
        ".row input[type='checkbox']{margin-left:.5em}"

        /* minor helpers */
        "small{color:#666;margin-left:.3em}"

        /* buttons */
        "button{padding:.45em .9em;border:1px solid #999;border-radius:5px;background:#f5f5f5;cursor:pointer}"
        "button:disabled{opacity:.6;cursor:not-allowed}"
        "</style>");
        "function populateSelect(selectEl, data, selected) {"
        "  var arr = [];"
        "  if (Array.isArray(data)) {"
        "    arr = data;"
        "  } else if (data.options) {"
        "    arr = data.options;"
        "  } else if (data.items) {"
        "    arr = data.items;"
        "  } else if (data.transforms) {"
        "    arr = data.transforms;"
        "  } else if (data.results) {"
        "    arr = data.results;"
        "  } else if (data.choices) {"
        "    arr = data.choices;"
        "  }"
        "  selectEl.innerHTML = '';"
        "  arr.forEach(function(t) {"
        "    var opt = document.createElement('option');"
        "    opt.value = t.id || t.value || '';"
        "    opt.textContent = (t.label || t.name || t.id || '?') + (t.out_units ? (' [' + t.out_units + ']') : '');"
        "    if (opt.value === selected) {"
        "      opt.selected = true;"
        "    }"
        "    selectEl.appendChild(opt);"
        "  });"
        "}"
        ""
        "function loadTransforms(sensorId, selectEl, selected, mode) {"
        "  var url = '/api/transforms/list?sensor=' + encodeURIComponent(sensorId) + '&t=' + Date.now();"
        "  if (mode) url += '&mode=' + encodeURIComponent(mode);"
        "  fetch(url, {cache:'no-store'})"
        "    .then(function(r){ return r.json(); })"
        "    .then(function(data){"
        "      populateSelect(selectEl, data, selected);"
        "    })"
        "    .catch(function(err){"
        "      console.error('Error loading transforms', err);"
        "    });"
        "}"
        ""
        "document.addEventListener('DOMContentLoaded', function(){"
        "  document.querySelectorAll('.reload').forEach(function(btn){"
        "    btn.addEventListener('click', function(){"
        "      var block = btn.closest('.tr-block');"
        "      if (!block) return;"
        "      var sensor = block.getAttribute('data-sensor');"
        "      var sel = block.querySelector('select');"
        "      var modeEl = document.getElementById(sensor + '_output_mode');"
        "      var mode = modeEl ? modeEl.value : null;"
        "      loadTransforms(sensor, sel, sel.value, mode);"
        "    });"
        "  });"
        "});";

    s += F("</head><body>");
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