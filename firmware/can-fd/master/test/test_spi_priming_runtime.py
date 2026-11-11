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
    parser.add_argument("--boundary-trace",action="store_true")
    parser.add_argument("--disabled-init",action="store_true")
    parser.add_argument("--without-init-gate",action="store_true",help="Negative control against actual initialization wrapper")
    parser.add_argument("--negative",choices=("missing-preload","duplicate-prefix","early-enable","missing-mode","enabled-mode"))
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    production=(root/"src/main.c").read_text(encoding="utf-8")
    arm=function(production,"arm_spi_slot")
    # No semantic mutation: pointers must fit the native host's SDK stand-in.
    assert arm.count("(uint32_t)")==4
    arm=arm.replace("(uint32_t)","(uintptr_t)")
    if args.negative:
        if args.negative=="missing-preload":
            arm,n=re.subn(r"\s*DL_SPI_transmitData8\([^;]+;","",arm);assert n==1
        elif args.negative=="duplicate-prefix":
            arm,n=re.subn(r"\[BODAQS_MASTER_SPI_TX_PRIME\]","[0]",arm);assert n==1
        elif args.negative=="early-enable":
            arm,n=re.subn(r"DL_SPI_transmitData8\(","DL_SPI_enable(SPI_A8_INST); DL_SPI_transmitData8(",arm);assert n==1
        elif args.negative=="missing-mode":
            arm,n=re.subn(r"\s*DL_SPI_setFrameFormat\([^;]+;","",arm);assert n==1
        else:
            arm,n=re.subn(r"DL_SPI_setFrameFormat\(","spi_enabled=true; DL_SPI_setFrameFormat(",arm);assert n==1
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
typedef struct { uint8_t TXDATA,RXDATA; uint32_t STAT,CTL0,CTL1; } SPI_Regs;
static SPI_Regs registers;
#define SPI_A8_INST (&registers)
static uint8_t gTransmitSlots[2][256],gReceiveSlots[2][256];
static unsigned gTransmitIndex,gReceiveIndex;
static uintptr_t source[2],destination[2];
static unsigned remaining[2];
static bool dma_enabled[2],spi_enabled;
enum { DL_SPI_FRAME_FORMAT_MOTO4_POL0_PHA1=1 };
static unsigned phase;
static uint8_t fifo[4];static unsigned fifo_count,prefix_writes,barriers;
static void DL_DMA_setSrcAddr(int d,int c,uintptr_t p) {(void)d;assert(!dma_enabled[c]);source[c]=p;}
static void DL_DMA_setDestAddr(int d,int c,uintptr_t p) {(void)d;assert(!dma_enabled[c]);destination[c]=p;}
static void DL_DMA_setTransferSize(int d,int c,unsigned n) {(void)d;assert(!dma_enabled[c]);remaining[c]=n;}
static void DL_DMA_enableChannel(int d,int c) {(void)d;assert(!dma_enabled[c]);dma_enabled[c]=true;}
static void DL_SPI_disable(void *p) {(void)p;assert(!dma_enabled[0] && !dma_enabled[1]);spi_enabled=false;}
static void DL_SPI_setFrameFormat(void *p,unsigned value) {(void)p;assert(!spi_enabled && !fifo_count && !dma_enabled[0] && !dma_enabled[1]);phase=value;}
static void DL_SPI_transmitData8(void *p,uint8_t b) {(void)p;assert(!spi_enabled && !dma_enabled[1] && !fifo_count);fifo[fifo_count++]=b;++prefix_writes;}
static void __DSB(void) {++barriers;}
static void DL_SPI_enable(void *p) {(void)p;assert(fifo_count==1 && barriers);assert(dma_enabled[0] && dma_enabled[1]);spi_enabled=true;}
static unsigned traced_arms;
static void spi_trace_arm(void) {assert(spi_enabled && dma_enabled[0] && dma_enabled[1]);++traced_arms;}
// ACTUAL_ARM
static void reset_hardware(void) {
 memset(source,0,sizeof source);memset(destination,0,sizeof destination);memset(remaining,0,sizeof remaining);
 dma_enabled[0]=dma_enabled[1]=false;fifo_count=prefix_writes=barriers=phase=0;spi_enabled=true;
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
#if BODAQS_SPI_BOUNDARY_TRACE
  assert(traced_arms==trial+2);
#endif
  assert(phase==BODAQS_CAN_SPI_BENCH_MODE);
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
        if args.disabled_init:
            # Generated configuration is a stand-in, not a silicon model. The
            # production wrapper and actual arm body are compiled unchanged;
            # target build separately audits the real generated configuration.
            wrapper=(root/'src/master_sysconfig.c').read_text(encoding='utf-8')
            if args.without_init_gate:
                gate='    if (spi == SPI_A8_INST) return;'
                assert wrapper.count(gate)==1
                wrapper=wrapper.replace(gate,'    (void)spi; /* negative: allow early enable */')
                assert gate not in wrapper
            (Path(directory)/'master_sysconfig.c').write_text(wrapper)
            (Path(directory)/'ti_msp_dl_config.h').write_text('#pragma once\n')
            (Path(directory)/'ti_msp_dl_config.c').write_text('''
void SYSCFG_DL_SPI_A8_init(void) {
 assert(!spi_enabled);registers.CTL0=0x27;registers.CTL1=0x10;
 DL_SPI_enable(SPI_A8_INST);
}
void SYSCFG_DL_init(void) {SYSCFG_DL_SPI_A8_init();DL_SPI_enable(&other_registers);}
''')
            fixture=fixture.replace('static SPI_Regs registers;','static SPI_Regs registers,other_registers;\nstatic unsigned other_enables;')
            fixture=fixture.replace('static void DL_SPI_enable(void *p) {(void)p;',
                'static void DL_SPI_enable(void *p) {if(p==&other_registers) {++other_enables;return;}')
            fixture=fixture.replace('// ACTUAL_ARM','#include "master_sysconfig.c"\n// ACTUAL_ARM')
            fixture=fixture.replace('phase=0;spi_enabled=true;','phase=0;spi_enabled=false;')
            fixture=fixture.replace('reset_hardware();gTransmitIndex=gReceiveIndex=0;arm_spi_slot();',
                'reset_hardware();SYSCFG_DL_init();assert(!spi_enabled && other_enables==1);gTransmitIndex=gReceiveIndex=0;arm_spi_slot();')
            fixture=fixture.replace('  arm_spi_slot();','  SYSCFG_DL_SPI_A8_init();assert(!spi_enabled && registers.CTL0==0x27 && registers.CTL1==0x10);\n  arm_spi_slot();')
        if args.boundary_trace:
            # Extract all four production observer bodies; only hardware/time
            # are stand-ins. Exact SDK raw address/masked size representation.
            def observer(name):
                match=re.search(r"static [\w *]+ "+name+r"\([^;{}]*\)\s*\{",production)
                assert match,name
                end=match.end();depth=1
                while depth:
                    depth+=(production[end]=='{')-(production[end]=='}');end+=1
                return production[match.start():end]
            helpers='\n'.join(observer(n) for n in ('spi_trace_hardware','spi_trace_barrier','spi_trace_cost','spi_trace_arm'))
            fixture=fixture.replace('static unsigned traced_arms;\nstatic void spi_trace_arm(void) {assert(spi_enabled && dma_enabled[0] && dma_enabled[1]);++traced_arms;}', '''
#include "bodaqs_spi_trace.h"
static BodaqsSpiTrace gMasterSpiTrace;
static uint32_t bodaqs_master_timing_clock(void *p,uint32_t *epoch) {(void)p;*epoch=7;return 100;}
static void __DMB(void) {}
static uint32_t DL_DMA_getSrcAddr(int d,int c) {(void)d;return (uint32_t)source[c];}
static uint32_t DL_DMA_getDestAddr(int d,int c) {(void)d;return (uint32_t)destination[c];}
static uint32_t DL_DMA_getTransferSize(int d,int c) {(void)d;return remaining[c];}
'''+helpers)
            fixture=fixture.replace('assert(traced_arms==trial+2);','''
  assert(gMasterSpiTrace.armed.tx_src==(uint32_t)source[1]);
  assert(gMasterSpiTrace.armed.rx_dst==(uint32_t)destination[0]);
  assert(gMasterSpiTrace.armed.tx_remaining==255 && gMasterSpiTrace.armed.rx_remaining==256);
  assert(!memcmp(gMasterSpiTrace.tx_armed,gTransmitSlots[gTransmitIndex],256));
  assert(gMasterSpiTrace.armed.stat==registers.STAT && gMasterSpiTrace.armed.epoch==7);
''')
        source.write_text(fixture.replace("// ACTUAL_ARM",arm),encoding="utf-8")
        variants=((1,0),) if args.boundary_trace or args.disabled_init else ((1,1),) if args.negative in ("missing-mode","enabled-mode") else ((1,0),) if args.negative else ((0,0),(1,0),(1,1))
        for priming,mode in variants:
            subprocess.run([args.cc,"-std=c11","-Wall","-Wextra","-Werror","-Wno-unused-function","-O2",
                "-DBODAQS_SPI_MEASUREMENT_V2=1",f"-DBODAQS_MASTER_SPI_DISABLED_INIT={int(args.disabled_init)}",f"-DBODAQS_SPI_BOUNDARY_TRACE={int(args.boundary_trace)}",f"-DBODAQS_MASTER_SPI_TX_PRIME={priming}",f"-DBODAQS_CAN_SPI_BENCH_MODE={mode}",
                "-I",str(root/"include"),"-I",str(root.parent/'common/transport'),str(source),"-o",str(exe)],check=True)
            subprocess.run([str(exe)],check=True)
        if not args.negative:
            for flags in (("-DBODAQS_MASTER_SPI_TX_PRIME=2",),("-DBODAQS_MASTER_SPI_TX_PRIME=1","-DBODAQS_SPI_MEASUREMENT_V2=0"),
                    ("-DBODAQS_CAN_SPI_BENCH_MODE=2",), ("-DBODAQS_CAN_SPI_BENCH_MODE=1","-DBODAQS_SPI_MEASUREMENT_V2=0"),
                    ("-DBODAQS_CAN_SPI_BENCH_MODE=1","-DBODAQS_SPI_MEASUREMENT_V2=1","-DBODAQS_MASTER_SPI_TX_PRIME=0"),
                    ("-DBODAQS_SPI_BOUNDARY_TRACE=1",),
                    ("-DBODAQS_SPI_BOUNDARY_TRACE=1","-DBODAQS_SPI_MEASUREMENT_V2=1","-DBODAQS_MASTER_SPI_TX_PRIME=0"),
                    ("-DBODAQS_SPI_BOUNDARY_TRACE=1","-DBODAQS_SPI_MEASUREMENT_V2=1","-DBODAQS_MASTER_SPI_TX_PRIME=1","-DBODAQS_CAN_SPI_BENCH_MODE=1")):
                checked=subprocess.run([args.cc,"-E","-x","c","-I",str(root/"include"),*flags,"-"],
                    input='#include "master_spi_priming.h"\n',text=True,capture_output=True)
                assert checked.returncode,"Unsafe priming configuration was accepted"


if __name__=="__main__":main()
