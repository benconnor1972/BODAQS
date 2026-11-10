#include "StorageFilesystem.h"
#if defined(ARDUINO_ARCH_ESP32)
#include "vfs_api.h"
#include <memory>

namespace StorageFilesystem {
namespace {
using Lease = StorageOwnership::Lease;

class TrackedFile : public fs::FileImpl {
public:
  TrackedFile(fs::FileImplPtr file, std::shared_ptr<Lease> lease)
      : file_(std::move(file)), lease_(std::move(lease)) {}
  ~TrackedFile() override { close(); }
  size_t write(const uint8_t* b, size_t n) override { return file_ ? file_->write(b, n) : 0; }
  size_t read(uint8_t* b, size_t n) override { return file_ ? file_->read(b, n) : 0; }
  void flush() override { if (file_) file_->flush(); }
  bool seek(uint32_t p, SeekMode m) override { return file_ && file_->seek(p, m); }
  size_t position() const override { return file_ ? file_->position() : 0; }
  size_t size() const override { return file_ ? file_->size() : 0; }
  bool setBufferSize(size_t n) override { return file_ && file_->setBufferSize(n); }
  void close() override {
    if (file_) file_->close();
    file_.reset();
    lease_.reset();
  }
  time_t getLastWrite() override { return file_ ? file_->getLastWrite() : 0; }
  const char* path() const override { return file_ ? file_->path() : nullptr; }
  const char* name() const override { return file_ ? file_->name() : nullptr; }
  boolean isDirectory() override { return file_ && file_->isDirectory(); }
  fs::FileImplPtr openNextFile(const char* mode) override {
    if (!file_) return nullptr;
    auto next = file_->openNextFile(mode);
    if (!next || !*next) return nullptr;
    // Children of an admitted directory scan belong to the same operation.
    return std::make_shared<TrackedFile>(std::move(next), lease_);
  }
  boolean seekDir(long p) override { return file_ && file_->seekDir(p); }
  String getNextFileName() override { return file_ ? file_->getNextFileName() : String(); }
  String getNextFileName(bool* isDir) override { return file_ ? file_->getNextFileName(isDir) : String(); }
  void rewindDirectory() override { if (file_) file_->rewindDirectory(); }
  operator bool() override { return file_ && bool(*file_); }
private:
  fs::FileImplPtr file_;
  std::shared_ptr<Lease> lease_;
};

class TrackedVFS : public VFSImpl {
public:
  fs::FileImplPtr open(const char* path, const char* mode, bool create) override {
    auto lease = ownership().acquireLocal();
    if (!lease) return nullptr;
    auto file = VFSImpl::open(path, mode, create);
    if (!file || !*file) return nullptr;
    return std::make_shared<TrackedFile>(std::move(file), std::make_shared<Lease>(std::move(lease)));
  }
  bool exists(const char* p) override {
    auto lease = ownership().acquireLocal();
    return lease && VFSImpl::exists(p);
  }
  bool rename(const char* from, const char* to) override {
    auto lease = ownership().acquireLocal();
    return lease && VFSImpl::rename(from, to);
  }
  bool remove(const char* p) override {
    auto lease = ownership().acquireLocal();
    return lease && VFSImpl::remove(p);
  }
  bool mkdir(const char* p) override {
    auto lease = ownership().acquireLocal();
    return lease && VFSImpl::mkdir(p);
  }
  bool rmdir(const char* p) override {
    auto lease = ownership().acquireLocal();
    return lease && VFSImpl::rmdir(p);
  }
};
} // namespace

Card::Card() : fs::SDMMCFS(std::make_shared<TrackedVFS>()) {}
Card& card() { static Card value; return value; }

bool Card::begin(const char* mountpoint, bool oneBit, bool format, int frequency, uint8_t maxFiles) {
  auto lease = ownership().acquireLocal();
  if (!lease || format) return false; // This ownership path never formats a card.
  if (_card) return true;
  mountpoint_ = mountpoint;
  oneBit_ = oneBit;
  frequency_ = frequency;
  maxFiles_ = maxFiles;
  return fs::SDMMCFS::begin(mountpoint_.c_str(), oneBit_, false, frequency_, maxFiles_);
}
void Card::end() {
  auto lease = ownership().acquireLocal();
  if (lease) fs::SDMMCFS::end();
}
sdcard_type_t Card::cardType() {
  auto lease = ownership().acquireLocal();
  return lease ? fs::SDMMCFS::cardType() : CARD_NONE;
}
uint64_t Card::cardSize() {
  auto lease = ownership().acquireLocal();
  return lease ? fs::SDMMCFS::cardSize() : 0;
}
uint64_t Card::totalBytes() {
  auto lease = ownership().acquireLocal();
  return lease ? fs::SDMMCFS::totalBytes() : 0;
}
uint64_t Card::usedBytes() {
  auto lease = ownership().acquireLocal();
  return lease ? fs::SDMMCFS::usedBytes() : 0;
}
void Card::service() {
  if (ownership().beginExternal()) {
    fs::SDMMCFS::end();
    ownership().externalReady();
  }
}
bool Card::reclaim() {
  if (!ownership().beginReclaim()) return false;
  const bool ok = fs::SDMMCFS::begin(mountpoint_.c_str(), oneBit_, false, frequency_, maxFiles_);
  ownership().reclaimComplete(ok);
  return ok;
}
} // namespace StorageFilesystem
#endif
