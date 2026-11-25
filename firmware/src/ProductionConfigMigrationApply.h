#pragma once
#include <stddef.h>

// Explicit idle application boundary shared by web, API and physical controls.
// Configuration persistence remains separate from sensor/hardware application.
namespace ProductionConfigMigrationApply {
enum class Result { Rejected, SavedNotApplied, Applied };
Result accept(const char* revision, char* error, size_t capacity);
}
