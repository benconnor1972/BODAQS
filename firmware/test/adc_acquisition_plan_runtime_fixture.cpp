#include "AdcAcquisitionPlan.h"
#include <assert.h>
#include <stdio.h>

int main() {
  LocalAnalogRecordingPlan source;
  assert(source.configure(650));
  assert(source.addExternal(7, 0, 3));
  assert(source.addExternal(2, 1, 0));
  assert(source.addExternal(3, 0, 1));
  assert(source.addGpio(9, 12));
  assert(!source.addExternal(4, 0, 3));
  assert(!source.addExternal(4, 2, 0));
  assert(!source.addExternal(4, 0, 4));
  assert(source.columns() == 4 && source.mask(0) == 10 && source.mask(1) == 1);
  assert(source.column(0).sensorIndex == 7 && source.column(0).channel == 3);
  assert(source.column(3).pin == 12 && !source.column(3).external);
  assert(source.firstChannel(0) == 1 && source.nextChannel(0, 1) == 3 && source.nextChannel(0, 3) == 1);
  AdcAcquisitionCadence cadence;
  assert(cadence.begin(source, 1000000));
  auto due = cadence.claim(1000000);
  assert(!due.adcMask && !due.row && due.nextUs == 1000770);
  due = cadence.claim(1000769); assert(!due.adcMask && !due.row);
  due = cadence.claim(1000770); assert(due.adcMask == 1 && !due.row);
  due = cadence.claim(1000770); assert(!due.adcMask && !due.row); // no duplicate transfer
  due = cadence.claim(1001539);
  assert(due.adcMask == 3 && due.row && due.sequence == 0 && !due.skippedRows);
  due = cadence.claim(1009000);
  assert(due.adcMask == 3 && due.row && due.sequence == 4 && due.skippedRows == 3);
  assert(due.missed[0] == 8 && due.missed[1] == 3);
  assert(due.nextUs > 1009000); // one bounded event, never a catch-up burst
  assert(!cadence.claim(1009000).row);
  // Exact rate and one idle ADC, with no dummy channel or ADC appointment.
  assert(source.configure(500) && source.addExternal(1, 1, 2));
  assert(cadence.begin(source, 0));
  due = cadence.claim(2000); assert(due.adcMask == 2 && due.row && due.sequence == 0);
  assert(source.configure(1200) && source.addExternal(1, 0, 0));
  assert(cadence.begin(source, 0));
  unsigned rows = 0;
  for (uint64_t now = 0; now <= 1000000; ++now) if (cadence.claim(now).row) ++rows;
  assert(rows == 1200); // independent elapsed-time expectation, not rounded 833us periods
  // A direct-input-only plan keeps the common row timer without ADC traffic.
  assert(source.configure(700) && source.addGpio(0, 4));
  assert(cadence.begin(source, 500));
  due = cadence.claim(1929); assert(!due.adcMask && due.row);
  assert(!source.configure(0));
  puts("ADC acquisition plan: sparse/unequal/idle/direct layouts, exact/fractional cadence and late wakes passed");
}
