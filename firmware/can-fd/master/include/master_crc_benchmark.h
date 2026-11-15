/* Boot-only experiment: never called by measurement or interrupt paths. */
#include "ti/driverlib/dl_crcp.h"
typedef struct {uint32_t bytes,software_cycles,hardware8_cycles,hardware32_cycles,checksum;} CrcBenchRow;
typedef struct {
 uint32_t version,state,cpu_hz,checks,mismatches,first_length,first_offset;
 uint32_t expected,actual8,actual32,iterations,sink;
 CrcBenchRow rows[16];
} CrcBenchInfo;
_Static_assert(sizeof(CrcBenchInfo)==368,"CRC benchmark ABI");
volatile CrcBenchInfo gCrcBench __attribute__((section(".bodaqs_spi_buffers"),aligned(8)));
static uint8_t crc_bench_data[1028] __attribute__((section(".bodaqs_spi_buffers"),aligned(4)));
static uint32_t crc_bench_sw(const uint8_t *p,size_t n) {return bodaqs_measurement_crc(p,n);}
static void crc_bench_begin(void) {
 DL_CRCP_init(CRC,DL_CRCP_POLYNOMIAL_SIZE_32,DL_CRCP_BIT_REVERSED,
  DL_CRCP_INPUT_ENDIANESS_LITTLE_ENDIAN,DL_CRCP_OUTPUT_BYTESWAP_DISABLED);
 DL_CRCP_setPolynomial(CRC,0x04c11db7U);
 DL_CRCP_setSeed32(CRC,0xffffffffU);
}
static uint32_t crc_bench_hw8(const uint8_t *p,size_t n) {
 crc_bench_begin();for(size_t i=0;i<n;++i)DL_CRCP_feedData8(CRC,p[i]);
 return ~DL_CRCP_getResult32(CRC);
}
static uint32_t crc_bench_hw32(const uint8_t *p,size_t n) {
 crc_bench_begin();size_t i=0;
 for(;i+4<=n;i+=4) {uint32_t word;memcpy(&word,p+i,4);DL_CRCP_feedData32(CRC,word);}
 for(;i<n;++i)DL_CRCP_feedData8(CRC,p[i]);
 return ~DL_CRCP_getResult32(CRC);
}
static void crc_bench_check(const uint8_t *p,size_t n,unsigned offset,uint32_t expected) {
 const uint32_t a=crc_bench_hw8(p,n),b=crc_bench_hw32(p,n);
 ++gCrcBench.checks;
 if(a!=expected || b!=expected) {
  if(!gCrcBench.mismatches) {gCrcBench.first_length=n;gCrcBench.first_offset=offset;
   gCrcBench.expected=expected;gCrcBench.actual8=a;gCrcBench.actual32=b;}
  ++gCrcBench.mismatches;
 }
}
static void crc_bench_run(void) {
 const unsigned lengths[16]={0,1,3,4,20,84,92,112,124,128,468,484,508,512,980,1024};
 static const uint32_t golden[16]={0x00000000U,0x45d03605U,0x3753a57bU,0xa5328cbeU,0x205c4a33U,0x86b46d5bU,0x33559e96U,0x52da41f5U,0x5cdd5c5dU,0x68f0b719U,0x714a8059U,0xc755f92bU,0xe10235b7U,0xff1346dbU,0x29342524U,0x6fea9368U};
 const uint32_t mask=__get_PRIMASK();__disable_irq();
 const uint32_t old_ctrl=SysTick->CTRL,old_load=SysTick->LOAD;
 SysTick->CTRL=0;SysTick->LOAD=0xffffffU;SysTick->VAL=0;
 SysTick->CTRL=SysTick_CTRL_ENABLE_Msk|SysTick_CTRL_CLKSOURCE_Msk;
 memset((void *)&gCrcBench,0,sizeof gCrcBench);
 gCrcBench.version=1;gCrcBench.state=1;gCrcBench.cpu_hz=CPUCLK_FREQ;gCrcBench.iterations=64;
 DL_CRCP_reset(CRC);DL_CRCP_enablePower(CRC);DL_Common_delayCycles(32);
 for(unsigned i=0;i<sizeof crc_bench_data;++i)crc_bench_data[i]=(uint8_t)(i*37+11);
 crc_bench_check((const uint8_t *)"123456789",9,0,0xcbf43926U);
 for(unsigned offset=0;offset<4;++offset)for(unsigned n=0;n<=1024;++n)
  crc_bench_check(crc_bench_data+offset,n,offset,crc_bench_sw(crc_bench_data+offset,n));
 for(unsigned r=0;r<16;++r) {
  const unsigned n=lengths[r];gCrcBench.rows[r].bytes=n;
  const uint32_t sw=crc_bench_sw(crc_bench_data,n);
  if(sw!=golden[r])++gCrcBench.mismatches;
  crc_bench_check(crc_bench_data,n,0,golden[r]);gCrcBench.rows[r].checksum=sw;
  if(gCrcBench.mismatches)continue;
  for(unsigned method=0;method<3;++method) {
   uint32_t (*volatile function)(const uint8_t *,size_t)=method==0?crc_bench_sw:method==1?crc_bench_hw8:crc_bench_hw32;
   uint32_t cycles=0;
   for(unsigned repeat=0;repeat<64;++repeat) {
    const uint32_t start=SysTick->VAL;const uint32_t value=function(crc_bench_data,n);
    const uint32_t elapsed=(start-SysTick->VAL)&0xffffffU;
    gCrcBench.sink^=value;cycles+=elapsed;
   }
   if(method==0)gCrcBench.rows[r].software_cycles=cycles;
   else if(method==1)gCrcBench.rows[r].hardware8_cycles=cycles;
   else gCrcBench.rows[r].hardware32_cycles=cycles;
  }
 }
 DL_CRCP_disablePower(CRC);gCrcBench.state=2;
 SysTick->CTRL=0;SysTick->LOAD=old_load;SysTick->VAL=0;SysTick->CTRL=old_ctrl;
 __set_PRIMASK(mask);
}
