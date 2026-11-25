#ifndef BODAQS_RECORD_QUEUE_H
#define BODAQS_RECORD_QUEUE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

/* Fixed storage, whole records, drop newest on overflow. The caller serializes
 * push/pop (on MSPM0 the main-loop pop briefly masks interrupts). Storage must
 * contain capacity * record_bytes bytes and remain alive with the queue.
 * No processing callback runs while interrupts are masked. */
typedef struct {
    uint8_t *storage;
    size_t record_bytes;
    uint16_t capacity;
    volatile uint16_t head;
    volatile uint16_t tail;
    volatile uint16_t depth;
    volatile uint16_t high_water;
    volatile uint32_t dropped;
} BodaqsRecordQueue;

static inline void bodaqs_record_queue_init(BodaqsRecordQueue *queue,
    void *storage, size_t record_bytes, uint16_t capacity)
{
    memset(queue, 0, sizeof(*queue));
    queue->storage = (uint8_t *) storage;
    queue->record_bytes = record_bytes;
    queue->capacity = capacity;
}

static inline bool bodaqs_record_queue_push(
    BodaqsRecordQueue *queue, const void *record)
{
    if (queue->depth == queue->capacity) {
        if (queue->dropped != UINT32_MAX) {
            ++queue->dropped;
        }
        return false;
    }
    memcpy(queue->storage + queue->tail * queue->record_bytes,
        record, queue->record_bytes);
    queue->tail = (uint16_t) ((queue->tail + 1U) % queue->capacity);
    ++queue->depth;
    if (queue->depth > queue->high_water) {
        queue->high_water = queue->depth;
    }
    return true;
}

static inline bool bodaqs_record_queue_pop(
    BodaqsRecordQueue *queue, void *record)
{
    if (queue->depth == 0U) {
        return false;
    }
    memcpy(record, queue->storage + queue->head * queue->record_bytes,
        queue->record_bytes);
    queue->head = (uint16_t) ((queue->head + 1U) % queue->capacity);
    --queue->depth;
    return true;
}

#endif
