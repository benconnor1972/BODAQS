#pragma once

#include <FS.h>

#include "BdqV2Writer.h"

// Thin storage-boundary adapter. Keeping File out of BdqV2Writer makes the
// writer core host-testable and permits alternative sinks for diagnostics.
class BdqV2FileSink final : public BdqV2ByteSink {
public:
  explicit BdqV2FileSink(File& file) : file_(file) {}

  bool write(const uint8_t* data, size_t length) override {
    if (!file_ || (!data && length != 0)) return false;
    if (length == 0) return true;
    return file_.write(data, length) == length;
  }

  bool flush() override {
    if (!file_) return false;
    file_.flush();
    return true;
  }

private:
  File& file_;
};

