#include "UsbUploadSession.h"
#include "StorageOwnership.h"
#include <cstdio>

namespace {
struct Device : UsbUploadSession::Backend {
  StorageOwnership ownership;
  bool mounted = true, shared = false, failReclaim = false, failExport = false, ioInFlight = false;
  unsigned exports = 0;
  bool linkChangesDuringExport = false;
  bool localReady() const override { return mounted && ownership.localAvailable(); }
  bool requestStorage() override { return ownership.requestExternal(); }
  bool storageGranted() const override { return ownership.state() == StorageOwnership::State::External; }
  void cancelStorage() override { ownership.cancelExternal(); }
  UsbUploadSession::ExposeResult expose() override {
    if (linkChangesDuringExport) return UsbUploadSession::ExposeResult::LinkChanged;
    shared = !failExport;
    if (shared) ++exports;
    return shared ? UsbUploadSession::ExposeResult::Ready : UsbUploadSession::ExposeResult::Failed;
  }
  bool withdraw(bool) override { if (ioInFlight) return false; shared = false; return true; }
  bool reclaim() override {
    if (ownership.localAvailable()) return mounted;
    if (!ownership.beginReclaim()) return false;
    mounted = !failReclaim;
    ownership.reclaimComplete(mounted);
    return mounted;
  }
  void finishTransfers() {
    if (ownership.beginExternal()) { mounted = false; ownership.externalReady(); }
  }
};
}

int runUsbUploadSessionTests() {
  int failures = 0;
#define CHECK_USB(value) do { if (!(value)) { \
  std::printf("FAIL USB upload line %d: %s\n", __LINE__, #value); ++failures; } } while (0)
  Device device;
  UsbUploadSession session(device);
  UsbUploadSession::Inputs input{true, true, false, false, false, 100};
  CHECK_USB(!session.enter(true));
  CHECK_USB(session.enter(false));
  session.poll(input, 100);
  CHECK_USB(session.state() == UsbUploadSession::State::Waiting);
  device.finishTransfers();
  session.poll(input, 101);
  CHECK_USB(device.shared && session.active());
  session.requestExit(200);
  session.poll(input, 3199);
  CHECK_USB(device.shared && session.exitPending());
  session.poll(input, 3200);
  CHECK_USB(!device.shared && !session.active() && device.localReady());
  {
    Device hardware;
    UsbUploadSession upload(hardware);
    auto unplugged = input;
    unplugged.connected = false;
    upload.poll(input, 1); // Connecting in normal mode never exports storage.
    CHECK_USB(!hardware.shared && hardware.localReady());
    upload.enter(false);
    upload.poll(unplugged, 2); // UPLOAD can precede the cable connection.
    CHECK_USB(upload.active() && hardware.localReady() && !hardware.shared);
    upload.poll(input, 3);
    hardware.finishTransfers();
    upload.poll(input, 4);
    CHECK_USB(hardware.shared);
    const uint32_t beforeWrap = UINT32_MAX - 1500;
    upload.requestExit(beforeWrap);
    auto traffic = input;
    traffic.lastIoMs = beforeWrap;
    upload.poll(traffic, uint32_t(beforeWrap + 2999));
    CHECK_USB(hardware.shared);
    for (uint32_t elapsed = 3000; elapsed < 600000; elapsed += 500) {
      traffic.lastIoMs = uint32_t(beforeWrap + elapsed);
      upload.poll(traffic, traffic.lastIoMs);
      CHECK_USB(hardware.shared && upload.exitPending());
    }
    upload.poll(traffic, uint32_t(traffic.lastIoMs + 999));
    CHECK_USB(hardware.shared);
    upload.poll(traffic, uint32_t(traffic.lastIoMs + 1000));
    CHECK_USB(!upload.active() && hardware.localReady());
  }
  {
    Device hardware;
    UsbUploadSession upload(hardware);
    auto transfer = hardware.ownership.acquireLocal();
    CHECK_USB(upload.enter(false));
    upload.poll(input, 100);
    hardware.finishTransfers();
    upload.poll(input, 101);
    CHECK_USB(!hardware.shared && upload.state() == UsbUploadSession::State::Waiting);
    CHECK_USB(!hardware.ownership.acquireLocal());
    upload.requestExit(200);
    upload.poll(input, 201);
    CHECK_USB(!upload.active() && hardware.localReady());
  }
  {
    Device hardware;
    UsbUploadSession upload(hardware);
    upload.enter(false);
    upload.poll(input, 100);
    hardware.finishTransfers();
    upload.poll(input, 101);
    upload.requestExit(200);
    auto traffic = input;
    traffic.lastIoMs = 3500;
    upload.poll(traffic, 4000);
    CHECK_USB(hardware.shared && upload.exitPending());
    traffic.busy = true;
    upload.poll(traffic, 9000);
    CHECK_USB(hardware.shared);
    CHECK_USB(upload.cancelExit());
    CHECK_USB(!upload.exitPending() && hardware.shared && upload.active());
    traffic.busy = false;
    upload.requestExit(10000);
    upload.poll(traffic, 12999);
    CHECK_USB(hardware.shared);
    upload.poll(traffic, 13000);
    CHECK_USB(!upload.active() && hardware.localReady());
  }
  {
    Device hardware;
    UsbUploadSession upload(hardware);
    upload.enter(false);
    upload.poll(input, 100);
    hardware.finishTransfers();
    upload.poll(input, 101);
    auto eject = input;
    eject.ejected = true;
    upload.poll(eject, 200);
    CHECK_USB(upload.active() && !hardware.shared && hardware.localReady());
    upload.poll(input, 5000);
    CHECK_USB(!hardware.shared && upload.state() == UsbUploadSession::State::Ejected);
    auto cableOut = input;
    cableOut.connected = false;
    upload.poll(cableOut, 6000);
    upload.poll(input, 7000);
    hardware.finishTransfers();
    upload.poll(input, 7001);
    CHECK_USB(hardware.shared);
    hardware.failReclaim = true;
    upload.requestExit(8000);
    upload.poll(input, 11000);
    CHECK_USB(upload.active() && !hardware.shared && !hardware.localReady());
    CHECK_USB(upload.state() == UsbUploadSession::State::Error && !upload.exitPending());
    hardware.failReclaim = false;
    upload.retry();
    upload.poll(input, 12000);
    CHECK_USB(hardware.localReady() && !hardware.shared && upload.active());
    upload.requestExit(12001);
    upload.poll(input, 12002);
    CHECK_USB(!upload.active());
  }
  {
    Device hardware;
    UsbUploadSession upload(hardware);
    auto absent = input;
    upload.enter(false);
    upload.poll(input, 100);
    hardware.finishTransfers();
    upload.poll(input, 101);
    absent.present = false;
    upload.poll(absent, 200);
    CHECK_USB(!hardware.shared && upload.active() && upload.state() == UsbUploadSession::State::Error);
    upload.poll(input, 300);
    CHECK_USB(!hardware.shared); // Reinsert alone never exports a replacement.
    upload.requestExit(301);
    upload.poll(input, 302);
    // Explicit mode exit can finish once usable local storage is restored.
    CHECK_USB(!upload.active());
  }
  {
    Device hardware;
    UsbUploadSession upload(hardware);
    auto link = input;
    link.connectionEpoch = 1;
    upload.enter(false);
    upload.poll(link, 100);
    hardware.finishTransfers();
    upload.poll(link, 101);
    CHECK_USB(hardware.shared && hardware.exports == 1);
    // A complete USB reconfiguration may occur between application polls.
    // Connected is still true, but the old host's exported card must be retired.
    link.connectionEpoch = 2;
    upload.poll(link, 200);
    CHECK_USB(upload.active() && !hardware.shared && hardware.localReady());
    CHECK_USB(hardware.exports == 1);
    upload.poll(link, 201);
    hardware.finishTransfers();
    upload.poll(link, 202);
    CHECK_USB(hardware.shared && hardware.exports == 2 && upload.active());
  }
  {
    Device hardware;
    UsbUploadSession upload(hardware);
    auto link = input;
    link.connectionEpoch = 1;
    upload.enter(false);
    upload.poll(link, 100);
    hardware.finishTransfers();
    upload.poll(link, 101);
    hardware.ioInFlight = true;
    link.connectionEpoch = 2;
    upload.poll(link, 200);
    CHECK_USB(upload.active() && !hardware.localReady());
    CHECK_USB(hardware.ownership.state() == StorageOwnership::State::External);
    CHECK_USB(hardware.exports == 1);
    hardware.ioInFlight = false;
    upload.poll(link, 201);
    CHECK_USB(upload.active() && hardware.localReady() && !hardware.shared);
    upload.poll(link, 202);
    hardware.finishTransfers();
    upload.poll(link, 203);
    CHECK_USB(hardware.shared && hardware.exports == 2);
  }
  {
    Device hardware;
    UsbUploadSession upload(hardware);
    auto link = input;
    link.connectionEpoch = 1;
    upload.enter(false);
    upload.poll(link, 100);
    hardware.finishTransfers();
    hardware.linkChangesDuringExport = true;
    upload.poll(link, 101);
    upload.poll(link, 102);
    CHECK_USB(upload.active() && upload.state() == UsbUploadSession::State::Upload && hardware.localReady());
    hardware.linkChangesDuringExport = false;
    ++link.connectionEpoch;
    upload.poll(link, 103);
    hardware.finishTransfers();
    upload.poll(link, 104);
    CHECK_USB(hardware.shared && hardware.exports == 1);
  }
  std::printf("USB upload session: %d failures\n", failures);
  return failures;
#undef CHECK_USB
}
