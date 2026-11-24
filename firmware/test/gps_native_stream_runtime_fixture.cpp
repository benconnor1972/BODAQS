#include "GpsNativeStream.h"
#include <cassert>
int main() {
  GpsNativeStream stream;
  assert(stream.begin(2));
  GpsNativeStream::Observation p;
  p.latE7=-319512345;p.lonE7=1158612345;p.altMslMm=-1234;
  p.groundSpeedMmS=12345;p.headingDegE5=35912345;p.flags=3;p.fixType=3;p.satellites=12;
  p.gpsTowMs=604799999;p.receivedMs=42;
  stream.observe(p,42000);
  auto source=stream.source(2);
  assert(stream.pending()==1);
  uint8_t bytes[64];
  assert(source.popRecord(source.context,bytes,64));
  assert(BdqV2Format::getU32(bytes+12)==static_cast<uint32_t>(-319512345));
  assert(BdqV2Format::getU32(bytes+16)==1158612345);
  assert(BdqV2Format::getU32(bytes+48)==604799999);
  p.flags=1;stream.observe(p,43000);stream.observe(p,44000);stream.observe(p,45000);
  assert(stream.stats().recordsDropped==1);
  stream.stop();stream.observe(p,46000);assert(stream.pending()==2);
  assert(!stream.begin(2));
  assert(source.popRecord(source.context,bytes,64));assert(BdqV2Format::getU16(bytes+8)&32);
  assert(source.popRecord(source.context,bytes,64));
  assert(stream.stats().recordsDropped==1);
  assert(stream.begin(2));stream.observe(p,50000);
  assert(source.popRecord(source.context,bytes,64));assert(BdqV2Format::getU32(bytes)==0);
  stream.stop();assert(stream.finalizeSession()==0);
}
