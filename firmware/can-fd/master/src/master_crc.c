#include "master_crc.h"
#if BODAQS_MASTER_HW_CRC
#include "master_crc_port.h"
/* Single foreground owner; every exception caller uses immutable-table software.
 * No IRQ masking, ISR spinlock, peripheral save/restore, or shared streaming state. */
volatile MasterCrcInfo gMasterCrcInfo
#if BODAQS_SPI_BULK_BYTES
 __attribute__((section(".bodaqs_spi_buffers"),aligned(4)))
#endif
 ;
static bool ready;
void bodaqs_master_crc_init(void) {
 ready=false;master_crc_power_init();
 gMasterCrcInfo.version=1;gMasterCrcInfo.enabled=1;ready=true;
}
static uint32_t software_parts(const uint8_t *a,size_t an,const uint8_t *b,size_t bn) {
 uint32_t c=0xffffffffU;
 for(size_t i=0;i<an;++i)c=bodaqs_measurement_crc_step(c,a[i]);
 for(size_t i=0;i<bn;++i)c=bodaqs_measurement_crc_step(c,b[i]);
 return ~c;
}
static void feed(const uint8_t *p,size_t n) {
 size_t i=0;
 for(;i+4<=n;i+=4) {uint32_t word;memcpy(&word,p+i,4);master_crc_feed32(word);}
 for(;i<n;++i)master_crc_feed8(p[i]);
}
uint32_t bodaqs_master_crc32_parts(const uint8_t *a,size_t an,const uint8_t *b,size_t bn) {
 if(master_crc_in_isr()) {
  ++gMasterCrcInfo.isr_fallback_calls;return software_parts(a,an,b,bn);
 }
 if(!ready) {++gMasterCrcInfo.cold_fallback_calls;return software_parts(a,an,b,bn);}
 ++gMasterCrcInfo.hardware_calls;
 master_crc_begin();feed(a,an);feed(b,bn);return master_crc_result();
}
#if defined(BODAQS_CRC_SELFTEST) && BODAQS_CRC_SELFTEST
/* Boot only, after init and before acquisition interrupts are enabled. */
volatile MasterCrcSelfTest gMasterCrcSelfTest __attribute__((section(".bodaqs_spi_buffers"),aligned(4)));
static uint8_t selftest_data[1028] __attribute__((section(".bodaqs_spi_buffers"),aligned(4)));
void bodaqs_master_crc_selftest(void) {
 gMasterCrcSelfTest.version=1;gMasterCrcSelfTest.state=1;
 for(unsigned i=0;i<sizeof selftest_data;++i)selftest_data[i]=(uint8_t)(i*37+11);
 if(bodaqs_master_crc32_parts((const uint8_t *)"1234",4,(const uint8_t *)"56789",5)!=0xcbf43926U)++gMasterCrcSelfTest.failures;
 ++gMasterCrcSelfTest.checks;
 for(unsigned offset=0;offset<4;++offset)for(unsigned n=0;n<=1024;++n) {
  const uint8_t *p=selftest_data+offset;const unsigned split=n/2;
  if(bodaqs_master_crc32_parts(p,split,p+split,n-split)!=software_parts(p,n,NULL,0))++gMasterCrcSelfTest.failures;
  ++gMasterCrcSelfTest.checks;
 }
 gMasterCrcSelfTest.state=2;
 /* A failed boot diagnostic never enters acquisition. */
 if(gMasterCrcSelfTest.failures) {for(;;) {__asm("nop");}}
}
#endif
#endif
