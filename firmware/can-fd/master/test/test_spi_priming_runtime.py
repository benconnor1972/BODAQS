"""Actual arm_spi_slot at the SDK register/DMA seam; no physical timing claim.

DMA is deliberately held off until arm returns: B must make byte0 available
without relying on its first DMA event. A must retain the old all-DMA path.
Then the simulated FIFO/DMA emits a whole or short frame and checks exact bytes,
remaining RX extent, buffer ownership and fresh reset/rearm. Host pointer casts
are widened only at the four SDK address calls; target code uses32-bit addresses.
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def function(text,name):
    match=re.search(r"static void "+name+r"\(void\)\s*\{",text)
    assert match
    end=match.end();depth=1
    while depth:
        depth+=(text[end]=="{")-(text[end]=="}");end+=1
    return text[match.start():end]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc",default="gcc")
    parser.add_argument("--negative",choices=("missing-preload","duplicate-prefix","early-enable"))
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    arm=function((root/"src/main.c").read_text(encoding="utf-8"),"arm_spi_slot")
    # No semantic mutation: pointers must fit the native host's SDK stand-in.
    assert arm.count("(uint32_t)")==4
    arm=arm.replace("(uint32_t)","(uintptr_t)")
    if args.negative:
        if args.negative=="missing-preload":
            arm,n=re.subn(r"\s*DL_SPI_transmitData8\([^;]+;","",arm);assert n==1
        elif args.negative=="duplicate-prefix":
            arm,n=re.subn(r"\[BODAQS_MASTER_SPI_TX_PRIME\]","[0]",arm);assert n==1
        else:
            arm,n=re.subn(r"DL_SPI_transmitData8\(","DL_SPI_enable(SPI_A8_INST); DL_SPI_transmitData8(",arm);assert n==1
    fixture=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "master_spi_priming.h"
#define BODAQS_MASTER_TRANSFER_BYTES 256U
#define DMA 0
#define DMA_SPI_RX_CHAN_ID 0
#define DMA_SPI_TX_CHAN_ID 1
static struct { uint8_t TXDATA,RXDATA; } registers;
#define SPI_A8_INST (&registers)
static uint8_t gTransmitSlots[2][256],gReceiveSlots[2][256];
static unsigned gTransmitIndex,gReceiveIndex;
static uintptr_t source[2],destination[2];
static unsigned remaining[2];
static bool dma_enabled[2],spi_enabled;
static uint8_t fifo[4];static unsigned fifo_count,prefix_writes,barriers;
static void DL_DMA_setSrcAddr(int d,int c,uintptr_t p) {(void)d;assert(!dma_enabled[c]);source[c]=p;}
static void DL_DMA_setDestAddr(int d,int c,uintptr_t p) {(void)d;assert(!dma_enabled[c]);destination[c]=p;}
static void DL_DMA_setTransferSize(int d,int c,unsigned n) {(void)d;assert(!dma_enabled[c]);remaining[c]=n;}
static void DL_DMA_enableChannel(int d,int c) {(void)d;assert(!dma_enabled[c]);dma_enabled[c]=true;}
static void DL_SPI_disable(void *p) {(void)p;assert(!dma_enabled[0] && !dma_enabled[1]);spi_enabled=false;}
static void DL_SPI_transmitData8(void *p,uint8_t b) {(void)p;assert(!spi_enabled && !dma_enabled[1] && !fifo_count);fifo[fifo_count++]=b;++prefix_writes;}
static void __DSB(void) {++barriers;}
static void DL_SPI_enable(void *p) {(void)p;assert(fifo_count==1 && barriers);assert(dma_enabled[0] && dma_enabled[1]);spi_enabled=true;}
// ACTUAL_ARM
static void reset_hardware(void) {
 memset(source,0,sizeof source);memset(destination,0,sizeof destination);memset(remaining,0,sizeof remaining);
 dma_enabled[0]=dma_enabled[1]=false;fifo_count=prefix_writes=barriers=0;spi_enabled=true;
}
static void dispatch_dma(void) {
 while(dma_enabled[1] && remaining[1] && fifo_count<4) {
  fifo[fifo_count++]=*(const uint8_t*)source[1];++source[1];--remaining[1];
 }
}
static uint8_t clock_byte(uint8_t mosi) {
 assert(spi_enabled && dma_enabled[0] && remaining[0]);dispatch_dma();assert(fifo_count);
 uint8_t b=fifo[0];memmove(fifo,fifo+1,--fifo_count);
 *(uint8_t*)destination[0]=mosi;++destination[0];--remaining[0];return b;
}
int main(void) {
 // Startup intentionally publishes an all-zero legacy pipeline slot. Priming
 // must preserve those bytes rather than manufacture a measurement magic byte.
 reset_hardware();gTransmitIndex=gReceiveIndex=0;arm_spi_slot();
 for(unsigned b=0;b<256;++b) assert(clock_byte(0)==0);
 assert(!remaining[0] && !remaining[1] && !fifo_count);
 // Independent literal protocol prefix and a deterministic payload. The other
 // slot has a different prefix to catch selection/duplicate-byte mistakes.
 const uint8_t prefix[4]={0x42,0x4d,0x02,0x0d};
 for(unsigned slot=0;slot<2;++slot) {
  for(unsigned b=0;b<256;++b) gTransmitSlots[slot][b]=(uint8_t)(b+31*slot);
  memcpy(gTransmitSlots[slot],prefix,4);gTransmitSlots[slot][3]=(uint8_t)(0x0d-slot);
 }
 const unsigned lengths[]={64,84,256,17,256};
 for(unsigned trial=0;trial<5;++trial) {
  reset_hardware();gTransmitIndex=trial%2;gReceiveIndex=(trial+1)%2;
  uint8_t before[2][256];memcpy(before,gTransmitSlots,sizeof before);
  memset(gReceiveSlots,0xaa,sizeof gReceiveSlots);
  arm_spi_slot();
  assert(spi_enabled && dma_enabled[0] && dma_enabled[1]);
  assert(remaining[0]==256 && destination[0]==(uintptr_t)gReceiveSlots[gReceiveIndex]);
  assert(source[0]==(uintptr_t)&registers.RXDATA && destination[1]==(uintptr_t)&registers.TXDATA);
#if BODAQS_MASTER_SPI_TX_PRIME
  assert(prefix_writes==1 && fifo_count==1 && fifo[0]==0x42 && barriers==1);
  assert(source[1]==(uintptr_t)&gTransmitSlots[gTransmitIndex][1] && remaining[1]==255);
#else
  assert(!prefix_writes && !fifo_count && !barriers);
  assert(source[1]==(uintptr_t)&gTransmitSlots[gTransmitIndex][0] && remaining[1]==256);
#endif
  for(unsigned b=0;b<lengths[trial];++b) {
   const uint8_t expected=b<4 ? (b==3?(uint8_t)(0x0d-gTransmitIndex):prefix[b]) : (uint8_t)(b+31*gTransmitIndex);
   assert(clock_byte((uint8_t)(b^0xa5))==expected);
   assert(gReceiveSlots[gReceiveIndex][b]==(uint8_t)(b^0xa5));
  }
  assert(!memcmp(before,gTransmitSlots,sizeof before));
  assert(remaining[0]==256-lengths[trial]);
  assert(remaining[1]+fifo_count==256-lengths[trial]);
  if(lengths[trial]<256) assert(gReceiveSlots[gReceiveIndex][lengths[trial]]==0xaa);
  // CS retirement resets FIFO/DMA; a short frame must not carry bytes forward.
 }
 puts(BODAQS_MASTER_SPI_TX_PRIME?"actual arm B: byte0 before DMA, exact suffix/RX extents; simulated reset/rearm PASS":"actual arm A: unchanged all-DMA bytes/extents; simulated reset/rearm PASS");
}
'''
    with tempfile.TemporaryDirectory(prefix="bodaqs-spi-prime-") as directory:
        source=Path(directory)/"fixture.c";exe=Path(directory)/"fixture.exe"
        source.write_text(fixture.replace("// ACTUAL_ARM",arm),encoding="utf-8")
        for priming in ((1,) if args.negative else (0,1)):
            subprocess.run([args.cc,"-std=c11","-Wall","-Wextra","-Werror","-Wno-unused-function","-O2",
                "-DBODAQS_SPI_MEASUREMENT_V2=1",f"-DBODAQS_MASTER_SPI_TX_PRIME={priming}",
                "-I",str(root/"include"),str(source),"-o",str(exe)],check=True)
            subprocess.run([str(exe)],check=True)
        if not args.negative:
            for flags in (("-DBODAQS_MASTER_SPI_TX_PRIME=2",),("-DBODAQS_MASTER_SPI_TX_PRIME=1","-DBODAQS_SPI_MEASUREMENT_V2=0")):
                checked=subprocess.run([args.cc,"-E","-x","c","-I",str(root/"include"),*flags,"-"],
                    input='#include "master_spi_priming.h"\n',text=True,capture_output=True)
                assert checked.returncode,"Unsafe priming configuration was accepted"


if __name__=="__main__":main()
