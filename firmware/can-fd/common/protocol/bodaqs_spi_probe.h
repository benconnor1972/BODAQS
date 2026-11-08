#ifndef BODAQS_SPI_PROBE_H
#define BODAQS_SPI_PROBE_H
/* Bench-only synthetic transport. Never a production CAN qualification. */
#if defined(BODAQS_SPI_PROBE) && BODAQS_SPI_PROBE
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#define BODAQS_SPI_PROBE_VERSION 1U
#define BODAQS_SPI_PROBE_CAPACITY 256U
#define BODAQS_SPI_PROBE_OBJECT_BYTES 1008U
#define BODAQS_SPI_PROBE_GUARD_US 25U
#define BODAQS_SPI_PROBE_HEADER_BYTES 20U
/* LE wire offsets: magic53,50 at0; version at2; opcode3; case4;
 * object8; node12; fragment13; payload_length14; profile15; logicalCRC16;
 * payload20; zero padding; IEEE CRC32 at frame_bytes-4 covers prior bytes.
 * LogicalCRC covers exactly1008 synthetic bytes, separate from frame CRC. */
enum { BODAQS_PROBE_BEGIN=1, BODAQS_PROBE_POLL=2, BODAQS_PROBE_ACK=3,
    BODAQS_PROBE_ACK_FETCH=4, BODAQS_PROBE_STATS=5, BODAQS_PROBE_STOP=6,
    BODAQS_PROBE_CLOCK=7, BODAQS_PROBE_ERROR=127, BODAQS_PROBE_RESPONSE=128 };
enum { BODAQS_PROBE_OK=0, BODAQS_PROBE_BAD_FRAME=1, BODAQS_PROBE_BUSY=2,
    BODAQS_PROBE_CONTEXT=3, BODAQS_PROBE_ARGUMENT=4, BODAQS_PROBE_CHECKSUM=5,
    BODAQS_PROBE_EXHAUSTED=6 };
typedef struct {
    uint32_t case_id, object_id, logical_crc;
    uint8_t opcode, node, fragment, payload_length, profile;
    uint8_t payload[232];
} BodaqsSpiProbeFrame;
typedef enum {
    BODAQS_SPI_PROBE_DECODE_OK=0,
    BODAQS_SPI_PROBE_DECODE_ARGUMENT=1,
    BODAQS_SPI_PROBE_DECODE_FRAME_SIZE=2,
    BODAQS_SPI_PROBE_DECODE_MAGIC=3,
    BODAQS_SPI_PROBE_DECODE_VERSION=4,
    BODAQS_SPI_PROBE_DECODE_PROFILE=5,
    BODAQS_SPI_PROBE_DECODE_PAYLOAD_LENGTH=6,
    BODAQS_SPI_PROBE_DECODE_CRC=7,
    BODAQS_SPI_PROBE_DECODE_PADDING=8,
    BODAQS_SPI_PROBE_DECODE_COUNT=9
} BodaqsSpiProbeDecodeResult;
/* Counters are prepared/retired, never claims of physical delivery. */
typedef struct {
    uint32_t requests, malformed, rejected, prepared_fragments, repeat_fragments;
    uint32_t selected_objects, retired_objects, duplicate_acks, bad_acks, cases;
} BodaqsSpiProbeStats;
typedef struct {
    uint32_t object_id, logical_crc, prepared_mask, last_acked, last_acked_crc;
    bool selected;
} BodaqsSpiProbeNode;
typedef struct {
    uint32_t case_id;
    uint8_t profile;
    bool active;
    BodaqsSpiProbeNode nodes[4];
    BodaqsSpiProbeStats stats;
    /* Main-owner snapshot: STATS page1. See PROTOCOL.md for indices. */
    uint32_t adapter_stats[10];
    /* Main-owned coherent adapter snapshot: additive STATS page2.
     * Process/counter totals wrap uint32; maxima and invalid are boot state. */
    uint32_t diagnostic_stats[10];
    /* Optional single-main-owner instrumentation. Totals/counts wrap uint32;
     * frame/object CRC costs are nested inside decode/command/encode. */
    uint32_t component_stats[10];
    uint32_t (*component_clock)(void *,uint32_t *epoch);
    void *component_clock_arg;
    uint32_t component_epoch,component_invalid;
    /* Adapter-owned coherent snapshots: additive STATS5/6, schema1. */
    uint32_t receive_stats[10],turnover_stats[10],flow_stats[10];
} BodaqsSpiProbeEngine;
/* profile: size code 0/1/2 =>64/128/256; bit2 0/1 =>8/16MHz;
 * bits3..4 => node_count-1; all other bits zero. Guard fixed at25us. */
uint8_t bodaqs_spi_probe_profile(uint16_t bytes, uint32_t hz, uint8_t nodes);
uint16_t bodaqs_spi_probe_frame_bytes(uint8_t profile);
uint8_t bodaqs_spi_probe_node_count(uint8_t profile);
uint8_t bodaqs_spi_probe_fragment_count(uint8_t profile);
uint32_t bodaqs_spi_probe_crc(const uint8_t *bytes, size_t length);
uint8_t bodaqs_spi_probe_known_byte(uint32_t case_id, uint8_t node,
    uint32_t object_id, uint16_t offset);
uint32_t bodaqs_spi_probe_known_crc(uint32_t case_id, uint8_t node, uint32_t object_id);
bool bodaqs_spi_probe_encode(const BodaqsSpiProbeFrame *frame, uint8_t *wire, size_t length);
/* First rejection in the historical validation order; failure leaves frame
 * unchanged. Sizes are checked before any wire byte is accessed. */
BodaqsSpiProbeDecodeResult bodaqs_spi_probe_decode_result(const uint8_t *wire,
    size_t length, BodaqsSpiProbeFrame *frame);
bool bodaqs_spi_probe_decode(const uint8_t *wire, size_t length, BodaqsSpiProbeFrame *frame);
/* Exact bench CLOCK: canonical size-only profile, all identities/payload/padding
 * zero, valid fixed CRC. No scope/ACK/fence authority. Safe before main decoding;
 * caller must first establish physical length after DMA disable/FIFO drain. */
bool bodaqs_spi_probe_is_clock(const uint8_t *wire,size_t length);
void bodaqs_spi_probe_init(BodaqsSpiProbeEngine *engine);
/* Install before processing requests; no ISR/reentrant use or live switching.
 * NULL leaves timings unmeasured. BEGIN/STOP do not reset boot counters. */
void bodaqs_spi_probe_set_clock(BodaqsSpiProbeEngine *engine,
    uint32_t (*clock)(void *,uint32_t *epoch),void *arg);
/* Main owner only. Selected bytes are regenerated from immutable case/node/ID,
 * not copied from a CAN ring or retained in a1008-byte RAM array. This measures
 * synthetic generation/encode work, not real CAN acquisition or batch copying.
 * Invalid frames do not change selected objects. Output is
 * zero-filled to capacity, including stale tails across profile changes.
 * False means no publishable response (malformed physical/frame input). */
bool bodaqs_spi_probe_process(BodaqsSpiProbeEngine *engine, const uint8_t *request,
    size_t length, uint8_t *reply, size_t capacity);
#ifdef __cplusplus
}
#endif
#endif
#endif
