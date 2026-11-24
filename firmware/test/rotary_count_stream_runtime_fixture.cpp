#include "RotaryCountStream.h"
#include <cassert>
#include <limits.h>

int main() {
  RotaryCountStream stream;
  assert(stream.begin(2));
  RotaryCountStream::Observation value;
  value.raw=16383;value.angle=4095;value.deviceStatus=32;value.agc=127;
  value.validity=7;value.magnitude=2048;value.tickUs=123;value.readFailures=17;
  assert(stream.observe(value));
  value.sequence=1;assert(stream.observe(value));
  value.sequence=2;assert(!stream.observe(value));
  assert(stream.stats().recordsDropped==1 && stream.stats().recordQueueHighWater==2);
  const auto source=stream.source(2);assert(source.valid());
  uint8_t bytes[32]{};
  assert(!source.popRecord(source.context,bytes,31));
  assert(stream.pendingRecords()==2);
  assert(source.popRecord(source.context,bytes,sizeof bytes));
  assert(BdqV2Format::getU16(bytes+12)==16383 && BdqV2Format::getU16(bytes+14)==4095);
  assert(bytes[19]==7 && BdqV2Format::getU32(bytes+24)==17);
  value.sequence=3;assert(stream.observe(value));
  assert(source.popRecord(source.context,bytes,sizeof bytes));
  assert(source.popRecord(source.context,bytes,sizeof bytes));
  assert((BdqV2Format::getU16(bytes+8)&3)==3);
  stream.markGap();value.sequence=6;assert(stream.observe(value));
  stream.stop();assert(!stream.observe(value));
  assert(!stream.begin(2)); // The old file owns its unconsumed tail.
  assert(source.popRecord(source.context,bytes,sizeof bytes));
  assert((BdqV2Format::getU16(bytes+8)&9)==9);
  assert(stream.stats().recordsDequeued==4);
  assert(stream.begin(2));assert(stream.stats().recordsDropped==0);
  value.sequence=0;assert(stream.observe(value));stream.stop();stream.finalizeSession();
  assert(stream.pendingRecords()==0 && stream.begin(2));
}
