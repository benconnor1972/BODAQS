#include "imu_capture.h"
#include "ti_msp_dl_config.h"
#include <assert.h>
uint32_t raw, count, cc[4];
int main(void) {
    BodaqsNodeCapture c;
    uint32_t e;
    bodaqs_node_capture_init();
    raw = 5;
    count = 20;
    cc[2] = 65530;
    bodaqs_node_capture_irq();
    assert(bodaqs_node_capture_take(&c) && c.tick == 65530 && c.ordinal == 1);
    raw = 4;
    count = 40;
    cc[2] = 30;
    bodaqs_node_capture_irq();
    assert(bodaqs_node_capture_take(&c) && c.tick == 65566);
    assert(bodaqs_node_capture_clock(0, &e) == 65576 && e == 1);
    bodaqs_node_capture_init();
    raw = 5;
    count = 20;
    cc[2] = 10;
    bodaqs_node_capture_irq();
    assert(bodaqs_node_capture_take(&c) && c.tick == 65546);
    raw = 16;
    bodaqs_node_capture_irq();
    assert(bodaqs_node_capture_fault());
    assert(bodaqs_node_capture_clock(0, &e) == 65556);
    bodaqs_node_capture_init();
    raw = 4;
    count = 65530;
    cc[2] = 65530;
    bodaqs_node_capture_irq();
    assert(bodaqs_node_capture_take(&c) && c.tick == 65530);
    raw = 1;
    count = 0;
    bodaqs_node_capture_irq();
    raw = 4;
    count = 20;
    cc[2] = 10;
    bodaqs_node_capture_irq();
    assert(bodaqs_node_capture_take(&c) && c.tick == 65546);
    bodaqs_node_capture_init();
    for (unsigned i = 0; i < 129; ++i) {
        raw = 4;
        count = i;
        cc[2] = i;
        bodaqs_node_capture_irq();
    }
    assert(bodaqs_node_capture_fault());
    bodaqs_node_capture_init();
    bodaqs_node_capture_supervise(140);
    assert(bodaqs_node_capture_fault());
    return 0;
}
