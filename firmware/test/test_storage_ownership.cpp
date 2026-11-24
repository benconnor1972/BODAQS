#include "StorageOwnership.h"
#include <cstdio>

int runStorageOwnershipTests() {
  int failures = 0;
#define CHECK_STORAGE(value) do { if (!(value)) { \
  std::printf("FAIL storage ownership line %d: %s\n", __LINE__, #value); ++failures; } } while (0)
  StorageOwnership ownership;
  {
    auto transfer = ownership.acquireLocal();
    CHECK_STORAGE(bool(transfer));
    CHECK_STORAGE(ownership.requestExternal());
    CHECK_STORAGE(!ownership.acquireLocal());
    CHECK_STORAGE(!ownership.beginExternal());
    // The admitted transfer can finish; acquisition of new work is closed.
  }
  CHECK_STORAGE(ownership.beginExternal());
  CHECK_STORAGE(!ownership.acquireLocal());
  ownership.externalReady();
  CHECK_STORAGE(ownership.state() == StorageOwnership::State::External);
  CHECK_STORAGE(ownership.beginReclaim());
  CHECK_STORAGE(!ownership.acquireLocal());
  ownership.reclaimComplete(false);
  CHECK_STORAGE(ownership.state() == StorageOwnership::State::Error);
  CHECK_STORAGE(!ownership.acquireLocal());
  CHECK_STORAGE(ownership.beginReclaim());
  ownership.reclaimComplete(true);
  CHECK_STORAGE(bool(ownership.acquireLocal()));

  CHECK_STORAGE(ownership.requestExternal());
  CHECK_STORAGE(ownership.cancelExternal());
  CHECK_STORAGE(bool(ownership.acquireLocal()));
  CHECK_STORAGE(!ownership.beginExternal());
  std::printf("Storage ownership: %d failures\n", failures);
  return failures;
#undef CHECK_STORAGE
}
