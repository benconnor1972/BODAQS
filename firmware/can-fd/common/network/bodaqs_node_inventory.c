#include "bodaqs_node_inventory.h"

#include <string.h>

static void advance_generation(BodaqsNodeInventory *inventory)
{
    ++inventory->generation;
    if (inventory->generation == 0U) {
        inventory->generation = 1U;
    }
}

void bodaqs_node_inventory_init(BodaqsNodeInventory *inventory)
{
    if (inventory != NULL) {
        memset(inventory, 0, sizeof(*inventory));
        inventory->generation = 1U;
    }
}

bool bodaqs_node_inventory_observe_announce(BodaqsNodeInventory *inventory,
    const BodaqsCanNodeAnnounce *announce, uint32_t now_ms)
{
    BodaqsNodeInventoryEntry *entry;

    if ((inventory == NULL) || (announce == NULL) ||
        (announce->node_address >= BODAQS_CAN_NODE_COUNT)) {
        return false;
    }
    entry = &inventory->nodes[announce->node_address];
    if (entry->present &&
        (entry->identity.hardware_uid != announce->hardware_uid)) {
        entry->duplicate = true;
        entry->stale = false;
        entry->conflicting_hardware_uid = announce->hardware_uid;
        entry->last_seen_ms = now_ms;
        ++entry->announces_received;
        ++inventory->duplicate_observations;
        advance_generation(inventory);
        return false;
    }

    if (entry->present && (entry->identity.boot_id != announce->boot_id)) {
        ++entry->boot_changes;
        memset(&entry->status, 0, sizeof(entry->status));
        entry->last_status_ms = 0U;
    }
    entry->present = true;
    entry->stale = false;
    entry->identity = *announce;
    entry->last_seen_ms = now_ms;
    entry->last_announce_ms = now_ms;
    ++entry->announces_received;
    advance_generation(inventory);
    return !entry->duplicate;
}

bool bodaqs_node_inventory_observe_status(BodaqsNodeInventory *inventory,
    uint8_t node_address, const BodaqsCanNodeStatus *status, uint32_t now_ms)
{
    BodaqsNodeInventoryEntry *entry;

    if ((inventory == NULL) || (status == NULL) ||
        (node_address >= BODAQS_CAN_NODE_COUNT)) {
        return false;
    }
    entry = &inventory->nodes[node_address];
    if (!entry->present || entry->duplicate) {
        ++inventory->unmatched_statuses;
        return false;
    }
    if (entry->identity.boot_id != status->boot_id) {
        ++inventory->boot_mismatch_statuses;
        return false;
    }

    entry->status = *status;
    entry->stale = false;
    entry->last_seen_ms = now_ms;
    entry->last_status_ms = now_ms;
    ++entry->statuses_received;
    advance_generation(inventory);
    return true;
}

void bodaqs_node_inventory_update_stale(BodaqsNodeInventory *inventory,
    uint32_t now_ms, uint32_t stale_after_ms)
{
    uint8_t node;

    if (inventory == NULL) {
        return;
    }
    for (node = 0U; node < BODAQS_CAN_NODE_COUNT; ++node) {
        BodaqsNodeInventoryEntry *entry = &inventory->nodes[node];
        if (entry->present &&
            ((uint32_t) (now_ms - entry->last_seen_ms) > stale_after_ms)) {
            if (!entry->stale) {
                entry->stale = true;
                advance_generation(inventory);
            }
        }
    }
}
