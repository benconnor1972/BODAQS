#ifndef BODAQS_CONTROL_SNAPSHOT_H
#define BODAQS_CONTROL_SNAPSHOT_H
#include "bodaqs_control.h"
#ifdef __cplusplus
extern "C" {
#endif
#define BODAQS_CONTROL_CAPABILITY_BYTES 128U
#define BODAQS_CONTROL_EFFECTIVE_BYTES 192U
#define BODAQS_CONTROL_SNAPSHOT_LIFETIME_MS 5000U
#define BODAQS_CONTROL_FIELD_GROUPS 0xFFFU
typedef void (*BodaqsControlDescriptorCapture)(void *context,
 const BodaqsControlNode *view, uint8_t endpoint, bool effective, uint8_t *data);
typedef struct {
 BodaqsControlDescriptorCapture capture;
 void *capture_context;
 uint8_t bytes[192];
 BodaqsControlRecord opening;
 uint64_t id, next_id;
 uint32_t opened_ms;
 uint16_t length;
 bool pinned, expired;
} BodaqsControlSnapshot;
bool bodaqs_control_descriptor_valid(const uint8_t *data, size_t length,
                                     uint16_t schema, uint8_t endpoint);
void bodaqs_control_unconfigured_descriptor(const BodaqsControlNode *view,
 uint8_t endpoint, bool effective, uint8_t *data);
bool bodaqs_control_snapshot_process(BodaqsControlSnapshot *snapshot,
 const BodaqsControlNode *view, const BodaqsControlRecord *request,
 uint32_t now_ms, BodaqsControlRecord *reply);
#ifdef __cplusplus
}
#endif
#endif
