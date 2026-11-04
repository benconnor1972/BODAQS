#include "bodaqs_control_authority.h"
#include "bodaqs_control_authority_client.h"
#include <cassert>
#include <cstdio>
#include <initializer_list>
static uint64_t random64(void *)
{
    return 0x123456789abcdef0ULL;
}
int main()
{
    BodaqsControlAuthority a;
    bodaqs_control_authority_init(&a);
    BodaqsControlNode n = {};
    n.boot_id = 123;
    n.endpoint_mask = 1;
    n.endpoint_epoch[0] = 99;
    BodaqsControlRecord q = {}, r = {};
    q.opcode = BODAQS_CONTROL_GET_CHALLENGE;
    q.endpoint = 255;
    q.node_boot_id = 123;
    q.operation = 50;
    q.data_length = 8;
    bodaqs_control_put_u64(q.data, 456);
    assert(bodaqs_control_authority_process(&a, &n, &q, 100, random64, 0, &r));
    assert(r.transfer == 0x123456789abcdef0ULL && bodaqs_control_get_u32(r.data) == 5000);
    q = {};
    q.opcode = BODAQS_CONTROL_BIND_SESSION;
    q.endpoint = 255;
    q.node_boot_id = 123;
    q.operation = 1;
    q.session = 456;
    q.transfer = r.transfer;
    assert(bodaqs_control_authority_process(&a, &n, &q, 101, random64, 0, &r));
    assert(r.data[0] == 0 && n.active_session == 456 && n.endpoint_epoch[0] == 100);

    BodaqsControlRecord bind = q;
    BodaqsControlRecord mutation = q;
    mutation.opcode = BODAQS_CONTROL_BEGIN_APPLY;
    mutation.operation = 2;
    assert(bodaqs_control_authority_admit(&a, &n, &mutation) == 0);
    BodaqsControlRecord outcome = mutation;
    outcome.data_length = 24;
    outcome.data[0] = 3;
    bodaqs_control_authority_complete(&a, &mutation, &outcome);
    assert(bodaqs_control_authority_process(&a, &n, &bind, 102, random64, 0, &r) && r.data[0] == 0);
    assert(a.high_water == 2); // Lost bind reply must not rewind accepted operations.
    q = {};
    q.opcode = BODAQS_CONTROL_GET_OPERATION;
    q.endpoint = 255;
    q.node_boot_id = 123;
    q.operation = 90;
    q.session = 456;
    q.data_length = 4;
    bodaqs_control_put_u32(q.data, 1);
    assert(bodaqs_control_authority_process(&a, &n, &q, 103, random64, 0, &r));
    assert(r.opcode == BODAQS_CONTROL_GET_OPERATION && r.data[0] == 6 && r.data[1] == 13);
    bodaqs_control_put_u32(q.data, 2);
    assert(bodaqs_control_authority_process(&a, &n, &q, 103, random64, 0, &r) && r.data[0] == 3);
    assert(r.opcode == 0x14 && r.data[3] == 0x14 && bodaqs_control_get_u32(r.data + 4) == 2);
    assert(a.latest_result.data[3] == outcome.data[3]);
    q.session = 999;
    assert(bodaqs_control_authority_process(&a, &n, &q, 103, random64, 0, &r) && r.data[1] == 5);
    q.session = 0;
    assert(!bodaqs_control_request_valid(&q));
    q = {};
    q.opcode = BODAQS_CONTROL_RELEASE_SESSION;
    q.endpoint = 255;
    q.node_boot_id = 123;
    q.session = 456;
    q.operation = 3;
    for (unsigned guard : {2U, 4U, 8U, 16U, 32U})
    {
        n.flags = 1 | guard;
        assert(bodaqs_control_authority_process(&a, &n, &q, 104, random64, 0, &r));
        assert(r.opcode == BODAQS_CONTROL_ERROR && n.active_session == 456 && a.high_water == 2);
    }
    n.flags = 1;
    n.pending_operation = 4;
    assert(bodaqs_control_authority_process(&a, &n, &q, 104, random64, 0, &r) && r.data[1] == 7);
    n.pending_operation = 0;
    assert(bodaqs_control_authority_process(&a, &n, &q, 104, random64, 0, &r) && r.data[0] == 0 &&
           n.active_session == 0);
    assert(bodaqs_control_authority_process(&a, &n, &q, 8000, random64, 0, &r) && r.data[0] == 0);
    assert(n.endpoint_epoch[0] == 101 && bodaqs_control_authority_admit(&a, &n, &mutation) == 5);
    q.node_boot_id = 122;
    assert(bodaqs_control_authority_process(&a, &n, &q, 8000, random64, 0, &r) && r.data[1] == 4);
    // Identical challenge retries preserve deadline, including uint32 time wrap.
    bodaqs_control_authority_init(&a);
    n.active_session = 0;
    n.flags = 0;
    q = {};
    q.opcode = BODAQS_CONTROL_GET_CHALLENGE;
    q.endpoint = 255;
    q.node_boot_id = 123;
    q.operation = 10;
    q.data_length = 8;
    bodaqs_control_put_u64(q.data, 789);
    assert(bodaqs_control_authority_process(&a, &n, &q, 0xfffffff0U, random64, 0, &r));
    uint64_t challenge = r.transfer;
    assert(bodaqs_control_authority_process(&a, &n, &q, 100, random64, 0, &r) && r.transfer == challenge);
    assert(bodaqs_control_authority_process(&a, &n, &q, 4984, random64, 0, &r) && r.data[1] == 20);
    bind.session = 789;
    bind.transfer = challenge;
    assert(bodaqs_control_authority_process(&a, &n, &bind, 4984, random64, 0, &r) && r.data[1] == 20);
    // Public logger-to-node exchange: observation replies alone never grant authority.
    BodaqsControlAuthorityClient client;
    bodaqs_control_authority_client_init(&client, 1000);
    bodaqs_control_authority_client_node(&client, 0, 123, true);
    bodaqs_control_authority_init(&a);
    BodaqsControlWrapped request = {}, reply = {};
    uint8_t type = 0;
    for (unsigned step = 0; step < 2; step++)
    {
        assert(bodaqs_control_authority_client_next(&client, 55, &request, &type));
        assert(type == 6);
        reply = request;
        assert(bodaqs_control_authority_process(&a, &n, &request.record, 10 + step, random64, 0, &reply.record));
        assert(bodaqs_control_authority_client_accept(&client, 0x87, &reply, 10 + step));
    }
    assert(client.nodes[0].bound && n.active_session == 1000);
    assert(bodaqs_control_authority_client_release(&client, 0));
    assert(bodaqs_control_authority_client_next(&client, 55, &request, &type));
    reply = request;
    assert(bodaqs_control_authority_process(&a, &n, &request.record, 12, random64, 0, &reply.record));
    assert(bodaqs_control_authority_client_accept(&client, 0x87, &reply, 12));
    assert(!client.nodes[0].bound && n.active_session == 0);
    bodaqs_control_authority_client_node(&client, 0, 124, true);
    assert(!client.nodes[0].bound);
    // A different admitted challenge invalidates the prior challenge, but a
    // reused read identity with different contents never replaces it.
    bodaqs_control_authority_init(&a);
    n.active_session = 0;
    n.flags = 0;
    q = {};
    q.opcode = 1;
    q.endpoint = 255;
    q.node_boot_id = 123;
    q.operation = 100;
    q.data_length = 8;
    bodaqs_control_put_u64(q.data, 2000);
    assert(bodaqs_control_authority_process(&a, &n, &q, 20, random64, 0, &r));
    uint64_t oldChallenge = r.transfer;
    bodaqs_control_put_u64(q.data, 2001);
    assert(bodaqs_control_authority_process(&a, &n, &q, 21, random64, 0, &r) && r.data[1] == 12);
    q.operation++;
    assert(bodaqs_control_authority_process(&a, &n, &q, 22, random64, 0, &r));
    assert(r.transfer && r.transfer != oldChallenge);
    uint64_t freshChallenge = r.transfer;
    bind.session = 2000;
    bind.transfer = oldChallenge;
    assert(bodaqs_control_authority_process(&a, &n, &bind, 23, random64, 0, &r) && r.data[1] == 20);
    bind.session = 2001;
    bind.transfer = freshChallenge;
    assert(bodaqs_control_authority_process(&a, &n, &bind, 24, random64, 0, &r) && r.data[0] == 0);
    q = {};
    q.opcode = 3;
    q.endpoint = 255;
    q.node_boot_id = 123;
    q.session = 2001;
    q.operation = 2;
    assert(bodaqs_control_authority_process(&a, &n, &q, 25, random64, 0, &r) && r.data[0] == 0);
    BodaqsControlRecord released = q;
    q = {};
    q.opcode = 0x14;
    q.endpoint = 255;
    q.node_boot_id = 123;
    q.session = 2001;
    q.operation = 900;
    q.data_length = 4;
    bodaqs_control_put_u32(q.data, 2);
    assert(bodaqs_control_authority_process(&a, &n, &q, 26, random64, 0, &r) && r.opcode == 0x14 && r.data[0] == 0);
    q = {};
    q.opcode = 1;
    q.endpoint = 255;
    q.node_boot_id = 123;
    q.operation = 102;
    q.data_length = 8;
    bodaqs_control_put_u64(q.data, 2002);
    assert(bodaqs_control_authority_process(&a, &n, &q, 27, random64, 0, &r));
    bind.session = 2002;
    bind.transfer = r.transfer;
    assert(bodaqs_control_authority_process(&a, &n, &bind, 28, random64, 0, &r) && r.data[0] == 0);
    assert(bodaqs_control_authority_process(&a, &n, &released, 29, random64, 0, &r) && r.data[1] == 5);
    bodaqs_control_authority_init(&a);
    n.active_session = 0;
    n.flags = 0;
    q.operation++;
    assert(bodaqs_control_authority_process(&a, &n, &q, 30, nullptr, 0, &r) && r.data[1] == 22);
    puts("authority lifecycle and logger exchanges passed");
}
