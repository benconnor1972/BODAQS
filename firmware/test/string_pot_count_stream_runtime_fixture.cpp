#include "StringPotCountStream.h"
#include <cassert>
#include <cstring>
#include <limits.h>

int main() {
  StringPotCountStream stream;
  StringPotCountStream::Configuration config;
  config.assumeTurnZero=false;
  assert(stream.configure(config));
  assert(stream.begin(8));
  stream.observe(4090,0,100,0);
  stream.observe(3,1,200,0);
  StringPotCountStream::Sample sample;
  assert(stream.snapshot(sample) && sample.wrapped==3 && sample.unwrapped==4099);
  const auto frozen=sample;
  for(unsigned i=0;i<100;++i) {
    assert(stream.snapshot(sample));
    assert(sample.sequence==frozen.sequence && sample.unwrapped==frozen.unwrapped);
  }
  auto source=stream.source(2);
  uint8_t record[24]={};
  assert(source.popRecord(source.context,record,sizeof record));
  assert(BdqV2Format::getU32(record)==0 && BdqV2Format::getU32(record+4)==100);
  assert(BdqV2Format::getU16(record+12)==4090 && BdqV2Format::getU32(record+16)==4090);
  assert(BdqV2Format::getU16(record+14)&StringPotCountStream::Reset);
  assert(source.popRecord(source.context,record,sizeof record));
  assert(BdqV2Format::getU32(record+16)==4099);
  stream.stop();assert(stream.configure(config) && stream.begin(8));
  stream.observe(3,0,100,0);stream.observe(4090,1,200,0);
  assert(stream.snapshot(sample) && sample.unwrapped==-6);
  assert(sample.epoch==2);
  stream.observe(4080,3,400,0);
  assert(stream.snapshot(sample) && (sample.quality&StringPotCountStream::ObservationGap));
  assert(sample.quality&StringPotCountStream::Uncertain);
  stream.observe(0,4,500,0x20);
  assert(stream.snapshot(sample) && (sample.quality&StringPotCountStream::InvalidInput));
  assert(sample.unwrapped==-16);
  stream.observe(5000,5,600,0);
  assert(stream.snapshot(sample) && sample.wrapped==5000 && (sample.quality&StringPotCountStream::InvalidInput));
  stream.stop();while(source.popRecord(source.context,record,sizeof record)) {}
  config.analogSettling=true;
  assert(stream.configure(config) && stream.begin(2));
  stream.observe(4090,0,100,0);stream.observe(2000,1,200,0);
  assert(stream.snapshot(sample) && sample.unwrapped==4090 && (sample.quality&StringPotCountStream::SettlingHeld));
  stream.observe(1000,2,300,0);stream.observe(3,3,400,0);
  assert(stream.snapshot(sample) && sample.unwrapped==4099);
  assert(source.popRecord(source.context,record,sizeof record));
  assert(source.popRecord(source.context,record,sizeof record));
  stream.observe(4,4,500,0);
  assert(source.popRecord(source.context,record,sizeof record));
  assert((BdqV2Format::getU16(record+8)&3)==3); // Full queue loss is explicit.
  stream.stop();
  assert(stream.stats().recordsDropped==2 && stream.stats().recordsEnqueued==3);
  assert(stream.stats().recordsDequeued==3 && stream.stats().recordQueueHighWater==2);
  config.analogSettling=false;config.assumeTurnZero=true;config.installedZero=INT32_MAX;
  assert(stream.configure(config) && stream.begin(8));
  stream.observe(4095,0,100,0);stream.observe(0,1,200,0);
  assert(stream.snapshot(sample) && sample.unwrapped==INT32_MAX && (sample.quality&StringPotCountStream::Overflow));
  StringPotCountStream settling;
  config.installedZero=0;config.assumeTurnZero=false;config.analogSettling=true;
  assert(settling.configure(config) && settling.begin(8));
  settling.observe(4090,0,100,0);settling.observe(2000,1,200,0);
  settling.observe(1800,2,300,0);settling.observe(1600,3,400,0);settling.observe(1400,4,500,0);
  assert(settling.snapshot(sample) && sample.unwrapped==5496 && (sample.quality&StringPotCountStream::Uncertain));
  assert(!(sample.quality&StringPotCountStream::SettlingHeld));
  StringPotCountStream failedStart;
  assert(failedStart.configure(config) && failedStart.begin(2));
  failedStart.observe(100,0,100,0);
  failedStart.stop();
  assert(!failedStart.configure(config)); // A START cannot erase retained rows.
  assert(failedStart.finalizeSession()==1); // I/O retired; prior file's final depth was reportable.
  assert(failedStart.pending()==0 && failedStart.configure(config) && failedStart.begin(2));
}
