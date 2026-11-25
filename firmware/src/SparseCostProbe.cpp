#include "SparseCostProbe.h"
#if BODAQS_SPARSE_COST_PROBE
#include <Arduino.h>
#include <cstring>
#include "FirmwareInfo.h"
namespace SparseCostProbe {
uint32_t nowUs(){return micros();}
unsigned coreId(){return xPortGetCoreID();}
unsigned frequencyMHz(){return getCpuFrequencyMhz();}
void bootModeGate(){
#if defined(BODAQS_BENCH_AUTO_BOOT) && BODAQS_BENCH_AUTO_BOOT
 enabled=true;
 Serial.printf("{\"schema\":\"bodaqs.sparse-cost-gate.v1\",\"type\":\"selected\",\"enabled\":true,\"automatic\":true,\"recipe\":\"%s\"}\n",FirmwareInfo::buildRecipe());
 return;
#endif
 char line[16]={};unsigned used=0;bool overflow=false;uint32_t announced=millis();
 auto ready=[](){Serial.printf("{\"schema\":\"bodaqs.sparse-cost-gate.v1\",\"type\":\"ready\",\"recipe\":\"%s\",\"commands\":\"cost off,cost on\"}\n",FirmwareInfo::buildRecipe());};
 ready();
 for(;;){
  if(uint32_t(millis()-announced)>2000){ready();announced=millis();}
  while(Serial.available()){
   const char c=char(Serial.read());if(c=='\r')continue;
   if(c=='\n'){
    line[used]=0;
    if(!overflow && (!std::strcmp(line,"cost off") || !std::strcmp(line,"cost on"))){
     enabled=!std::strcmp(line,"cost on");
     Serial.printf("{\"schema\":\"bodaqs.sparse-cost-gate.v1\",\"type\":\"selected\",\"enabled\":%s,\"recipe\":\"%s\"}\n",enabled?"true":"false",FirmwareInfo::buildRecipe());Serial.flush();return;
    }
    if(used || overflow)Serial.println("[COST] expected cost off or cost on before startup");
    used=0;overflow=false;
   }else if(used<sizeof(line)-1)line[used++]=c;else overflow=true;
  }
  delay(10);
 }
}
}
#endif
