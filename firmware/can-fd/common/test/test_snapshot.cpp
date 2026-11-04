#include "bodaqs_control_snapshot.h"
#include <cassert>
#include <cstring>
int main()
{
    BodaqsControlNode n = {};
    n.boot_id = 55;
    n.endpoint_mask = 1;
    n.endpoint_epoch[0] = 1;
    BodaqsControlSnapshot s = {};
    BodaqsControlRecord q = {}, r = {};
    q.opcode = 5;
    q.node_boot_id = 55;
    q.operation = 7;
    assert(bodaqs_control_snapshot_process(&s, &n, &q, 100, &r));
    const uint8_t metadata[24] = {2, 0, 1, 0, 128, 0, 6, 0};
    assert(r.transfer == 1 && r.data_length == 24 &&
           !memcmp(r.data, metadata, 24));
    q.opcode = 7;
    q.transfer = r.transfer;
    assert(bodaqs_control_snapshot_process(&s, &n, &q, 200, &r));
    const uint8_t first[24] = {2, 0, 1, 0, 0,  1, 0, 0, 0, 0, 0, 0,
                               0, 0, 0, 0, 32, 0, 0, 0, 1, 0, 1, 0};
    assert(r.data_length == 24 && !memcmp(r.data, first, 24));
    assert(bodaqs_control_descriptor_valid(s.bytes, 128, 2, 0));
    q.opcode = 5;
    q.transfer = 0;
    assert(bodaqs_control_snapshot_process(&s, &n, &q, 5099, &r));
    assert(r.opcode == 5 && r.transfer == 1);
    assert(bodaqs_control_snapshot_process(&s, &n, &q, 5100, &r));
    assert(r.opcode == 127 && r.data[1] == 10);

    // An expired original read cannot capture a replacement descriptor.
    q.opcode = 6;
    q.operation = 8;
    assert(bodaqs_control_snapshot_process(&s, &n, &q, 5200, &r));
    const uint8_t effectiveMetadata[24] = {3, 0, 1, 0, 192, 0, 8, 0, 0,
                                           0, 0, 0, 0, 0,   0, 0, 1};
    assert(r.transfer == 2 && !memcmp(r.data, effectiveMetadata, 24));
    assert(bodaqs_control_descriptor_valid(s.bytes, 192, 3, 0));
    const uint8_t effectiveFirst[24] = {3, 0, 1, 0, 0, 0, 0, 0, 255, 15, 0,
                                        0, 0, 0, 0, 0, 0, 0, 0, 0,   32};
    assert(!memcmp(s.bytes, effectiveFirst, sizeof(effectiveFirst)));
    n.endpoint_epoch[0] = 2;
    q.opcode = 7;
    q.transfer = 2;
    q.page = 7;
    assert(bodaqs_control_snapshot_process(&s, &n, &q, 5300, &r));
    assert(bodaqs_control_get_u64(r.data + 16) ==
           1); // captured before live epoch changed
    q.operation = 9;
    assert(bodaqs_control_snapshot_process(&s, &n, &q, 5400, &r));
    assert(r.opcode == 127 && r.data[1] == 10);
    q.operation = 8;
    q.opcode = BODAQS_CONTROL_RELEASE_SNAPSHOT;
    q.page = 0;
    assert(bodaqs_control_snapshot_process(&s, &n, &q, 5500, &r));
    assert(r.opcode == 8 && r.data[0] == 0 && r.data[3] == 8);
    assert(bodaqs_control_snapshot_process(&s, &n, &q, 5600, &r));
    assert(r.opcode == 8 && r.data[3] == 8);
    uint8_t d[192];
    bodaqs_control_unconfigured_descriptor(&n, 0, true, d);
    d[12] = 1;
    d[16] = 2;
    assert(!bodaqs_control_descriptor_valid(d, 192, 3, 0));
    d[16] = 0;
    d[12] = 0;
    d[48] = 1;
    assert(!bodaqs_control_descriptor_valid(d, 192, 3, 0));
    d[48] = 0;
    d[12] = 4;
    assert(!bodaqs_control_descriptor_valid(d, 192, 3, 0));
    d[48] = 5;
    d[49] = 13;
    d[52] = 1;
    d[56] = 5;
    d[57] = 13;
    d[60] = 1;
    assert(bodaqs_control_descriptor_valid(
        d, 192, 3, 0)); // nominal3333/1; measurement still unknown
    d[16] = 4;
    assert(bodaqs_control_descriptor_valid(
        d, 192, 3, 0)); // retained historical nominal evidence
    d[12] = 0;
    assert(!bodaqs_control_descriptor_valid(d, 192, 3, 0));
    return 0;
}
