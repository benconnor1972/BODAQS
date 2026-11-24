#pragma once
#include <ArduinoJson.h>
#include <cstddef>
#include <cstdlib>

// Per-document heap budget. Small independent allocations tolerate fragmented
// heaps; neither allocation failure nor growth can silently exceed the budget.
class BoundedJsonAllocator final : public ArduinoJson::Allocator {
 public:
  explicit BoundedJsonAllocator(size_t limit) : limit_(limit) {}
  void* allocate(size_t bytes) override {
    if (bytes > limit_ - used_ || sizeof(Header) > limit_ - used_ - bytes) return nullptr;
    auto* header = static_cast<Header*>(std::malloc(sizeof(Header) + bytes));
    if (!header) return nullptr;
    header->bytes = bytes;
    used_ += sizeof(Header) + bytes;
    return header + 1;
  }
  void deallocate(void* pointer) override {
    if (!pointer) return;
    auto* header = static_cast<Header*>(pointer) - 1;
    used_ -= sizeof(Header) + header->bytes;
    std::free(header);
  }
  void* reallocate(void* pointer, size_t bytes) override {
    if (!pointer) return allocate(bytes);
    if (!bytes) { deallocate(pointer); return nullptr; }
    auto* header = static_cast<Header*>(pointer) - 1;
    const size_t old = header->bytes;
    if (bytes > old && bytes - old > limit_ - used_) return nullptr;
    auto* replacement = static_cast<Header*>(std::realloc(header, sizeof(Header) + bytes));
    if (!replacement) return nullptr;
    replacement->bytes = bytes;
    used_ = used_ - old + bytes;
    return replacement + 1;
  }
 private:
  union Header { size_t bytes; std::max_align_t alignment; };
  size_t limit_, used_ = 0;
};
