#pragma once
#include <stdint.h>
#include <stdio.h>
#include <string>
#include <ctype.h>

// Pure text proposal. Loading and inspecting never writes storage or mutates the
// captured original. The acceptance adapter owns backup/save/reload operations.
class ProductionConfigMigration {
public:
  void inspect(const std::string& original, bool exists) {
    original_ = original;
    proposed_.clear(); changes_.clear();
    bool formatSeen = false, versionSeen = false, accepted = false;
    for (size_t start = 0; start < original.size();) {
      const size_t end = original.find('\n', start);
      const size_t length = end == std::string::npos ? original.size()-start : end-start+1;
      const std::string line = original.substr(start,length);
      const auto eq = line.find('=');
      const std::string key = eq == std::string::npos ? "" : trim(line.substr(0,eq));
      std::string value = eq == std::string::npos ? "" : trim(line.substr(eq+1));
      const auto comment = value.find('#');
      if (comment != std::string::npos) value = trim(value.substr(0,comment));
      std::string replacement = value;
      std::string canonical=value;
      for(char& letter:canonical)letter=static_cast<char>(toupper(static_cast<unsigned char>(letter)));
      if (key == "log_format") { formatSeen=true; replacement="bodaqs_multi_stream_binary"; }
      if (key == "production_config_revision") {
        versionSeen=true; accepted = value == "1"; replacement="1";
      }
      if (endsWith(key,".output_mode") &&
          (canonical=="POLY" || canonical=="LUT" || value=="2" || value=="3")) replacement="1";
      if (endsWith(key,".output_id") && value != "identity") replacement="identity";
      if (!key.empty() && replacement != value) {
        proposed_ += key + "=" + replacement + "\n";
        changes_ += key + ": " + value + " -> " + replacement + "\n";
      } else proposed_ += line;
      start += length;
    }
    if (!proposed_.empty() && proposed_.back()!='\n') proposed_+='\n';
    if(originalValue("recording_best_effort").empty()) { proposed_ += "recording_best_effort=false\n"; changes_ += "recording_best_effort: absent -> false (all requested participants required)\n"; }
    if (!formatSeen) { proposed_ += "log_format=bodaqs_multi_stream_binary\n"; changes_ += "log_format: absent -> bodaqs_multi_stream_binary\n"; }
    if (!versionSeen) { proposed_ += "production_config_revision=1\n"; changes_ += "production_config_revision: absent -> 1\n"; }
    pending_ = exists && (!accepted || !changes_.empty());
    if(pending_) changes_ += "Recording: BDQ v2 counts and native streams; RAW/LINEAR remain preview preferences.\n"
        "include_raw: retained preference; count-first recordings already retain raw evidence.\n"
        "Calibration anchors/units/count domains, assignments and unsupported sensor tokens: preserved.\n"
        "POLY/LUT selection and output_id transforms are retired; no streamed polynomial/LUT conversion.\n";
    char revision[24];
    uint64_t hash = 14695981039346656037ULL;
    for (unsigned char value : original_) { hash ^= value; hash *= 1099511628211ULL; }
    snprintf(revision,sizeof(revision),"%016llx",static_cast<unsigned long long>(hash));
    revision_ = revision;
  }
  bool pending() const { return pending_; }
  const std::string& original() const { return original_; }
  const std::string& proposed() const { return proposed_; }
  const std::string& changes() const { return changes_; }
  const std::string& revision() const { return revision_; }
  std::string originalValue(const std::string& key) const {
    std::string result;
    for (size_t start=0; start<original_.size();) {
      const auto end=original_.find('\n',start);
      const auto line=original_.substr(start,end==std::string::npos?std::string::npos:end-start);
      const auto eq=line.find('=');
      if(eq!=std::string::npos && trim(line.substr(0,eq))==key) {
        auto value=line.substr(eq+1); const auto comment=value.find('#');
        result=trim(value.substr(0,comment));
      }
      if(end==std::string::npos) break;
      start=end+1;
    }
    return result;
  }
private:
  static std::string trim(const std::string& value) {
    const auto start=value.find_first_not_of(" \r\n\t");
    if(start==std::string::npos)return {};
    return value.substr(start,value.find_last_not_of(" \r\n\t")-start+1);
  }
  static bool endsWith(const std::string& value,const char* suffix) {
    const std::string ending=suffix;
    return value.size()>=ending.size() && value.compare(value.size()-ending.size(),ending.size(),ending)==0;
  }
  std::string original_,proposed_,changes_,revision_;
  bool pending_=false;
};
