#include <cstdio>
#include <cstring>

#include "BdqV2Format.h"

int runBdqV2FormatTests() {
    int passed = 0;
    int failed = 0;

    auto check = [&](bool condition, const char* description) {
        if (condition) {
            ++passed;
        } else {
            std::printf("    FAIL: test_bdq_v2_format: %s\n", description);
            ++failed;
        }
    };

    check(BdqV2Format::kFileHeaderBytes == 32, "file header size is fixed");
    check(BdqV2Format::kChunkHeaderBytes == 20, "chunk header size is fixed");
    check(BdqV2Format::kStreamDataHeaderBytes == 24, "stream-data header size is fixed");
    check(BdqV2Format::kStreamRecordPrefixBytes == 12, "record prefix size is fixed");
    check(BdqV2Format::kTimeObservationBytes == 32, "time observation size is fixed");

    uint8_t fileHeaderBytes[BdqV2Format::kFileHeaderBytes] {};
    BdqV2Format::FileHeader fileHeader;
    fileHeader.createdUnixUs = 0x0102030405060708ULL;
    check(BdqV2Format::encodeFileHeader(
              fileHeader, fileHeaderBytes, sizeof(fileHeaderBytes)),
          "file header encodes");
    check(std::memcmp(fileHeaderBytes, BdqV2Format::kFileMagic, 8) == 0 &&
          fileHeaderBytes[8] == 2 && fileHeaderBytes[9] == 0 &&
          fileHeaderBytes[16] == 0x08 && fileHeaderBytes[23] == 0x01,
          "file header contains v2 magic and little-endian creation time");

    uint8_t chunkHeaderBytes[BdqV2Format::kChunkHeaderBytes] {};
    BdqV2Format::ChunkHeader chunkHeader;
    chunkHeader.type = BdqV2Format::ChunkType::StreamData;
    chunkHeader.sequence = 7;
    chunkHeader.payloadLength = 123;
    chunkHeader.payloadCrc32 = 0xCBF43926u;
    check(BdqV2Format::encodeChunkHeader(
              chunkHeader, chunkHeaderBytes, sizeof(chunkHeaderBytes)),
          "chunk header encodes");
    check(std::memcmp(chunkHeaderBytes, BdqV2Format::kChunkMagic, 4) == 0 &&
          BdqV2Format::getU16(chunkHeaderBytes + 6) == 3 &&
          BdqV2Format::getU32(chunkHeaderBytes + 8) == 7,
          "chunk header contains type and sequence");
    const uint8_t crcVector[] = {'1', '2', '3', '4', '5', '6', '7', '8', '9'};
    check(BdqV2Format::crc32(crcVector, sizeof(crcVector)) == 0xCBF43926u,
          "CRC32 matches the reflected IEEE check vector");

    uint8_t headerBytes[BdqV2Format::kStreamDataHeaderBytes] {};
    BdqV2Format::StreamDataHeader header;
    header.streamId = 0x1234;
    header.firstSequence = 0x89ABCDEFu;
    header.recordCount = 17;
    header.recordSizeBytes = 28;
    header.observationCount = 2;
    check(BdqV2Format::encodeStreamDataHeader(header, headerBytes, sizeof(headerBytes)),
          "stream-data header encodes");
    check(headerBytes[0] == 0x34 && headerBytes[1] == 0x12,
          "stream ID is little-endian");
    check(headerBytes[8] == 0xEF && headerBytes[11] == 0x89,
          "first sequence is little-endian");

    BdqV2Format::StreamDataHeader decodedHeader;
    check(BdqV2Format::decodeStreamDataHeader(headerBytes, sizeof(headerBytes), decodedHeader),
          "stream-data header decodes");
    check(decodedHeader.streamId == header.streamId &&
          decodedHeader.firstSequence == header.firstSequence &&
          decodedHeader.recordCount == header.recordCount &&
          decodedHeader.recordSizeBytes == header.recordSizeBytes &&
          decodedHeader.observationCount == header.observationCount,
          "stream-data header round trips");
    check(!BdqV2Format::decodeStreamDataHeader(headerBytes, sizeof(headerBytes) - 1, decodedHeader),
          "short stream-data header is rejected");

    uint8_t prefixBytes[BdqV2Format::kStreamRecordPrefixBytes] {};
    BdqV2Format::StreamRecordPrefix prefix;
    prefix.sequence = 0xFFFFFFFEu;
    prefix.nativeTick = 0x00FFFFF0u;
    prefix.statusFlags = BdqV2Format::DiscontinuityBefore |
                         BdqV2Format::TimingDegraded;
    check(BdqV2Format::encodeStreamRecordPrefix(prefix, prefixBytes, sizeof(prefixBytes)),
          "record prefix encodes");
    BdqV2Format::StreamRecordPrefix decodedPrefix;
    check(BdqV2Format::decodeStreamRecordPrefix(prefixBytes, sizeof(prefixBytes), decodedPrefix),
          "record prefix decodes");
    check(decodedPrefix.sequence == prefix.sequence &&
          decodedPrefix.nativeTick == prefix.nativeTick &&
          decodedPrefix.statusFlags == prefix.statusFlags &&
          decodedPrefix.reserved == 0,
          "record prefix round trips");

    uint8_t observationBytes[BdqV2Format::kTimeObservationBytes] {};
    BdqV2Format::TimeObservation observation;
    observation.nativeTick = 0x00FFFFF0u;
    observation.relatedSequence = 0xFFFFFFFEu;
    observation.hostMinUs = 0x0102030405060708ULL;
    observation.hostMaxUs = 0x0102030405060808ULL;
    observation.kind = BdqV2Format::TimeObservationKind::AcquisitionWindow;
    observation.flags = BdqV2Format::ObservationHostBoundsConservative;
    check(BdqV2Format::validTimeObservation(observation), "valid timing interval is accepted");
    check(BdqV2Format::encodeTimeObservation(observation, observationBytes, sizeof(observationBytes)),
          "time observation encodes");
    check(observationBytes[8] == 0x08 && observationBytes[15] == 0x01,
          "64-bit host time is little-endian");

    BdqV2Format::TimeObservation decodedObservation;
    check(BdqV2Format::decodeTimeObservation(
              observationBytes, sizeof(observationBytes), decodedObservation),
          "time observation decodes");
    check(decodedObservation.nativeTick == observation.nativeTick &&
          decodedObservation.relatedSequence == observation.relatedSequence &&
          decodedObservation.hostMinUs == observation.hostMinUs &&
          decodedObservation.hostMaxUs == observation.hostMaxUs &&
          decodedObservation.kind == observation.kind &&
          decodedObservation.flags == observation.flags,
          "time observation round trips");

    decodedObservation.hostMinUs = decodedObservation.hostMaxUs + 1;
    check(!BdqV2Format::validTimeObservation(decodedObservation),
          "reversed timing interval is rejected");

    std::printf("BDQ v2 format: %d passed, %d failed\n", passed, failed);
    return failed;
}
