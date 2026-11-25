#include "PublishedSensorCounts.h"
#include <cassert>
#include <thread>
int main() {
  PublishedSensorCounts sample;
  PublishedSensorCounts::Value value;
  assert(!sample.read(value));
  sample.publish(-1,42,8);
  assert(sample.read(value) && value.counts==-1 && value.tickUs==42 && value.status==8);
  std::atomic<bool> done{false};
  std::thread owner([&] {
    for(int i=1;i<=200000;++i) sample.publish(i,uint32_t(i*2),uint16_t(i));
    done=true;
  });
  while(!done) if(sample.read(value) && value.counts!=-1) {
    assert(value.tickUs==uint32_t(value.counts*2));
    assert(value.status==uint16_t(value.counts));
  }
  owner.join();
  assert(sample.read(value) && value.counts==200000);
}
