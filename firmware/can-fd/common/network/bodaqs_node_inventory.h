#ifndef BODAQS_NODE_INVENTORY_H
#define BODAQS_NODE_INVENTORY_H

#include <stdbool.h>
#include <stdint.h>

#include "bodaqs_can_network.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    bool present;
    bool stale;
    bool duplicate;
    BodaqsCanNodeAnnounce identity;
    BodaqsCanNodeStatus status;
    uint64_t conflicting_hardware_uid;
    uint32_t last_seen_ms;
    uint32_t last_announce_ms;
    uint32_t last_status_ms;
    uint32_t announces_received;
    uint32_t statuses_received;
    uint32_t boot_changes;
} BodaqsNodeInventoryEntry;

typedef struct {
    BodaqsNodeInventoryEntry nodes[BODAQS_CAN_NODE_COUNT];
    uint32_t generation;
    uint32_t duplicate_observations;
    uint32_t unmatched_statuses;
    uint32_t boot_mismatch_statuses;
} BodaqsNodeInventory;

void bodaqs_node_inventory_init(BodaqsNodeInventory *inventory);

bool bodaqs_node_inventory_observe_announce(BodaqsNodeInventory *inventory,
    const BodaqsCanNodeAnnounce *announce, uint32_t now_ms);

bool bodaqs_node_inventory_observe_status(BodaqsNodeInventory *inventory,
    uint8_t node_address, const BodaqsCanNodeStatus *status, uint32_t now_ms);

void bodaqs_node_inventory_update_stale(BodaqsNodeInventory *inventory,
    uint32_t now_ms, uint32_t stale_after_ms);

#ifdef __cplusplus
}
#endif

#endif
