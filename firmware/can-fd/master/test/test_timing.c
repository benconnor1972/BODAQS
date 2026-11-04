#include "master_timing.h"
#include "ti_msp_dl_config.h"
uint32_t raw,count;
int main(void) {
 uint32_t sequence,tick,epoch;
 bodaqs_master_timing_init();
 raw=1;count=71;bodaqs_master_timing_irq();
 assert(bodaqs_master_timing_take(&sequence,&tick)&&sequence==1&&tick==50000);
 assert(bodaqs_master_timing_clock(0,&epoch)==50071&&epoch==1);
 raw=1;count=99;bodaqs_master_timing_irq();
 assert(!bodaqs_master_timing_take(&sequence,&tick));
 raw=1;count=123;bodaqs_master_timing_irq();
 assert(bodaqs_master_timing_take(&sequence,&tick)&&sequence==2&&tick==150000);
 raw=1;count=7; // pending rollover is counted exactly once before handler
 assert(bodaqs_master_timing_clock(0,&epoch)==200007&&epoch==1);
 bodaqs_master_timing_irq();assert(bodaqs_master_timing_clock(0,&epoch)==200007);
 bodaqs_master_timing_supervise(51);
 (void)bodaqs_master_timing_clock(0,&epoch);assert(epoch==0);
}
