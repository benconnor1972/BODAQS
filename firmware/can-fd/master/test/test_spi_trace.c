#include <assert.h>
#include <string.h>
#include <stdio.h>
#include "../../common/transport/bodaqs_spi_trace.h"
static struct {uint32_t before;BodaqsSpiTrace value;uint32_t after;} guarded;
static BodaqsSpiTrace *t=&guarded.value;
static unsigned published;
static void barrier(void) {
    assert(!t->frozen && t->nonce==23 && t->logger_slot==23 && t->marker_ordinal==11);
    assert(t->request_crc==0x12345678 && t->reply_crc==0xabcdef12);
    ++published;
}
int main(void) {
    uint8_t tx[256],rx[256],old_tx[256],old_rx[256];
    BodaqsMeasurementSlot command={0},decoded;
    BodaqsSpiTraceHardware arm={0},end={0};
    guarded.before=0x12345678;guarded.after=0x87654321;
    bodaqs_spi_trace_init(t,UINT64_C(0xfedcba9876543210));
    assert(t->bytes==sizeof(*t) && t->boot_high==0xfedcba98 && t->boot_low==0x76543210);
    command.kind=1;command.context=UINT64_C(0xfedcba9876543210);command.node=255;command.body[0]=1;
    assert(bodaqs_measurement_encode(&command,rx,256));
    command.kind=2;command.object=41;
    assert(bodaqs_measurement_encode(&command,tx,256));
    memcpy(old_tx,tx,256);memcpy(old_rx,rx,256);
    arm.stat=0x11;arm.tx_src=0x20210101;arm.tx_remaining=255;arm.rx_remaining=256;
    end=arm;end.stat=0x22;end.tx_remaining=end.rx_remaining=0;
    for(unsigned i=0;i<10;++i) {
        bodaqs_spi_trace_arm(t,tx,0x20210100,&arm);
        assert(!bodaqs_spi_trace_end(t,tx,rx,256,&end,barrier));
    }
    assert(t->count==8 && t->next==2 && t->ordinal==10);
    assert(t->entries[1].ordinal==10 && t->entries[2].ordinal==3);
    assert(t->entries[1].arm.stat==0x11 && t->entries[1].end.stat==0x22);
    assert(!memcmp(t->entries[1].tx_arm,old_tx,256) && !memcmp(t->entries[1].request,old_rx,256));
    bodaqs_spi_trace_request(&command,UINT64_C(0xfedcba9876543210),23,42,0x12345678,0xabcdef12);
    assert(bodaqs_measurement_encode(&command,rx,256));
    assert(rx[3]==0 && rx[16]==255 && !memcmp(rx+20,"TRC8\1\0\0\0",8));
    assert(bodaqs_spi_trace_marker(rx,256,&decoded));
    uint8_t malformed[256];memcpy(malformed,rx,256);malformed[30]^=1;
    assert(!bodaqs_spi_trace_marker(malformed,256,&decoded));
    assert(!bodaqs_spi_trace_marker(rx,84,&decoded));
    command.body[5]=1;assert(bodaqs_measurement_encode(&command,malformed,256));
    assert(!bodaqs_spi_trace_marker(malformed,256,&decoded));command.body[5]=0;
    command.body[16]=0;assert(bodaqs_measurement_encode(&command,malformed,256));
    assert(!bodaqs_spi_trace_marker(malformed,256,&decoded));
    assert(bodaqs_spi_trace_end(t,tx,rx,256,&end,barrier));
    assert(t->frozen && published==1 && t->count==8 && t->marker_ordinal==11);
    assert(t->entries[1].ordinal==10); /* Marker never displaces the failed predecessor. */
    BodaqsSpiTrace frozen;memcpy(&frozen,t,sizeof frozen);
    bodaqs_spi_trace_arm(t,old_rx,0,&end);
    assert(!bodaqs_spi_trace_end(t,old_rx,old_rx,64,&end,barrier));
    assert(bodaqs_spi_trace_end(t,tx,rx,256,&end,barrier));
    assert(!memcmp(&frozen,t,sizeof frozen));
    bodaqs_spi_trace_init(t,1);t->ordinal=UINT32_MAX;
    assert(bodaqs_spi_trace_end(t,tx,rx,256,&end,barrier));
    assert(t->overflow && !t->frozen && t->ordinal==UINT32_MAX);
    bodaqs_spi_trace_init(t,1);
    bodaqs_spi_trace_arm(t,old_tx,12,&arm);old_tx[0]=0;
    assert(!bodaqs_spi_trace_end(t,old_tx,old_rx,84,&end,barrier));
    assert(t->entries[0].tx_arm[0]==0x42 && t->entries[0].tx_end[0]==0 && t->entries[0].length==84);
    assert(!memcmp(tx,t->entries[0].tx_arm,256) && !memcmp(old_rx,t->entries[0].request,256));
    assert(bodaqs_spi_trace_end(t,tx,rx,256,&end,NULL));assert(t->overflow && !t->frozen);
    assert(guarded.before==0x12345678 && guarded.after==0x87654321);
    puts("bounded trace: ring, exact source/request, marker CRC/scope, freeze publication, immutability and saturation PASS");
}
