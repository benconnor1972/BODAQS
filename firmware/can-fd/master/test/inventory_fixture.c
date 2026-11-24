#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "bodaqs_master_service.h"
#include "bodaqs_node_inventory.h"
#include "bodaqs_record_queue.h"
/* RUNTIME_TYPE */
static MasterRuntimeInfo gMasterRuntimeInfo;
static BodaqsMasterService gService;
static BodaqsNodeInventory gNodeInventory;
static BodaqsMasterDiscoveryRecord gDiscoveryRecords[4];
static uint32_t gUptimeMs;
static BodaqsRecordQueue gCanReceiveQueue;
#define GPIO_BOARD_PORT 0
#define GPIO_BOARD_BUCK_ENABLE_PIN 1U
#define GPIO_BOARD_FRONT_ENABLE_PIN 2U
#define GPIO_BOARD_REAR_ENABLE_PIN 4U
#define GPIO_BOARD_FRONT_FAULT_PIN 8U
#define GPIO_BOARD_REAR_FAULT_PIN 16U
static uint32_t pins=31;
static uint32_t DL_GPIO_readPins(int port,uint32_t mask) {(void)port;return pins&mask;}
static unsigned publications;
static void publish_inventory(BodaqsMasterService *service,uint32_t generation,
    const BodaqsMasterDiscoveryRecord *records,uint8_t count) {
    ++publications;
    bodaqs_master_service_set_inventory(service,generation,records,count);
}
/* PRODUCTION_STATUS */
int main(void) {
    bodaqs_master_service_init(&gService,NULL);
    bodaqs_control_exchange_init(&gService.control,99);
    bodaqs_control_exchange_init(&gService.authorization,99);
    bodaqs_node_inventory_init(&gNodeInventory);
    gUptimeMs=101;update_service_status();
    assert(publications==1 && gService.discovery_generation==1);
    for(unsigned n=0;n<4;++n) {
        assert(gService.discovery[n].node_address==n && gService.discovery[n].node_count==4);
        assert(!gService.discovery[n].flags);
    }
    /* Steady data polls still refresh hardware/status; unchanged inventory
     * must not be rebuilt or republished on every SPI request. */
    gUptimeMs=102;gMasterRuntimeInfo.can_rx_frames=22;
    pins&=~GPIO_BOARD_FRONT_FAULT_PIN;gService.receptions[0].count=3;
    update_service_status();
    fprintf(stderr,"unchanged inventory publications=%u (expected 1)\n",publications);
    assert(publications==1);
    assert(gService.status.uptime_ms==102 && gService.status.can_rx_frames==22);
    assert(gService.status.flags&BODAQS_MASTER_STATUS_FLAG_FRONT_FAULT);
    assert(gService.status.spi_tx_queue_depth==1);
    gService.receptions[0].count=0;

    /* Mutations use the real main-owned inventory implementation. Raw CAN
     * decoding is covered by the separate adapter/protocol fixtures. */
    BodaqsCanNodeAnnounce announce={0};announce.hardware_uid=11;announce.boot_id=123;
    announce.endpoint_mask=1;
    assert(bodaqs_node_inventory_observe_announce(&gNodeInventory,&announce,10));
    update_service_status();assert(publications==2);
    assert(gService.discovery[0].hardware_uid==11 && gService.discovery[0].boot_id==123);
    BodaqsCanNodeStatus status={0};status.boot_id=123;status.uptime_ms=500;status.can_rx_frames=7;
    assert(bodaqs_node_inventory_observe_status(&gNodeInventory,0,&status,20));
    update_service_status();assert(publications==3);
    assert(gService.discovery[0].node_uptime_ms==500 && gService.discovery[0].can_rx_frames==7);
    assert(gService.discovery[0].flags&BODAQS_MASTER_DISCOVERY_FLAG_STATUS_VALID);
    assert(bodaqs_node_inventory_observe_status(&gNodeInventory,0,&status,25));
    update_service_status();assert(publications==4 && gService.discovery[0].last_seen_ms==25);
    bodaqs_node_inventory_update_stale(&gNodeInventory,3026,3000);
    update_service_status();assert(publications==5);
    assert(gService.discovery[0].flags&BODAQS_MASTER_DISCOVERY_FLAG_STALE);
    announce.boot_id=124;
    assert(bodaqs_node_inventory_observe_announce(&gNodeInventory,&announce,3030));
    update_service_status();assert(publications==6 && gService.discovery[0].boot_id==124);
    assert(!(gService.discovery[0].flags&BODAQS_MASTER_DISCOVERY_FLAG_STATUS_VALID));

    /* Both real control lanes have pending mutations before a duplicate UID
     * is observed. Publication must fence this dispatch, not a later retry. */
    BodaqsControlWrapped q={0},reply={0};uint8_t type;
    q.master_boot_id=99;q.record.opcode=BODAQS_CONTROL_COMMIT_APPLY;
    q.record.node_boot_id=124;q.record.session=456;q.record.operation=2;q.record.transfer=789;
    q.record.data_length=24;q.record.data[0]=1;q.record.data[2]=1;q.record.data[4]=44;q.record.data[8]=1;
    assert(bodaqs_control_exchange_request(&gService.control,false,&q,&reply,&type));
    assert(gService.control.slots[0].state==1);
    memset(&q.record,0,sizeof q.record);q.record.opcode=BODAQS_CONTROL_RENEW_LEASE;
    q.record.node_boot_id=124;q.record.session=456;q.record.operation=3;
    q.record.endpoint=255;q.record.data_length=24;q.record.data[0]=1;
    assert(bodaqs_control_exchange_request(&gService.authorization,false,&q,&reply,&type));
    assert(gService.authorization.slots[0].state==1);
    announce.hardware_uid=22;
    assert(!bodaqs_node_inventory_observe_announce(&gNodeInventory,&announce,3040));
    update_service_status();assert(publications==7);
    assert(gService.control.excluded_addresses==1 && gService.authorization.excluded_addresses==1);
    assert(gService.control.slots[0].state!=1 && gService.authorization.slots[0].state!=1);
    gService.measurement.mode.phase=2;gService.authorization_tokens[0]=2;
    uint8_t address,payload[64];uint16_t transaction;
    assert(!bodaqs_master_service_control_transmit(&gService,3040,&address,&transaction,payload));

    /* Measurement-context turnover preserves the duplicate exclusion even
     * when an unchanged inventory takes the fast path. */
    gService.measurement.mode.context=789;gService.measurement.mode.session=456;
    gService.measurement.mode.recording=1;
    BodaqsMeasurementSlot idle={0};idle.node=255;idle.context=789;
    uint8_t input[64],output[84];
    assert(bodaqs_measurement_encode(&idle,input,64));
    update_service_status();assert(publications==7);
    assert(bodaqs_master_service_process_transfer(&gService,input,64,3041,output)==BODAQS_MASTER_SLOT_PROCESSED);
    assert(gService.authorization.excluded_addresses==1);

    /* Publish the final generation before exercising the real wrap to one. */
    gNodeInventory.generation=UINT32_MAX-1;
    announce.node_address=1;announce.hardware_uid=33;announce.boot_id=1;
    assert(bodaqs_node_inventory_observe_announce(&gNodeInventory,&announce,3050));
    update_service_status();assert(publications==8 && gService.discovery_generation==UINT32_MAX);
    status.boot_id=1;status.uptime_ms=600;
    assert(bodaqs_node_inventory_observe_status(&gNodeInventory,1,&status,3060));
    update_service_status();assert(publications==9 && gService.discovery_generation==1);
    assert(gService.discovery[1].node_uptime_ms==600 && gService.control.excluded_addresses==1);
    bodaqs_master_service_init(&gService,NULL);update_service_status();
    assert(publications==10 && gService.discovery[1].node_uptime_ms==600);
    assert(gService.control.excluded_addresses==1 && gService.authorization.excluded_addresses==1);
    puts("generation-based inventory refresh, live status and same-dispatch duplicate fencing: PASS");
}
