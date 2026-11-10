    /* Actual retirement path, including full RX queue and fence rewriting.
     * Arming hardware remains the SDK stand-in; its trace observer is real. */
    bodaqs_spi_trace_init(&gMasterSpiTrace,77);
    bodaqs_record_queue_init(&gSpiReceiveQueue,gSpiReceiveStorage,256,capacity);
    gSpiTransmitReady=false;gSpiRetiring=false;cs_high=1;test_epoch=1;test_tick=7000;
    memset((void*)&gSpiRetirementRequest,0,sizeof gSpiRetirementRequest);
    BodaqsMeasurementSlot traced={0};traced.kind=2;traced.context=91;traced.object=42;
    assert(bodaqs_measurement_encode(&traced,gTransmitSlots[gTransmitIndex],256));
    spi_trace_arm();
    traced.kind=1;traced.object=0;traced.node=255;traced.body[0]=1;
    uint8_t expected_request[256];assert(bodaqs_measurement_encode(&traced,expected_request,256));
    for(unsigned i=0;i<capacity+1;++i) {
        memcpy(gReceiveSlots[gReceiveIndex],expected_request,256);remaining=0;retire_spi_boundary();
    }
    assert(gSpiReceiveQueue.depth==capacity && gSpiReceiveQueue.dropped==1);
    assert(gMasterSpiTrace.count==capacity+1); /* Includes the dropped request. */
    unsigned last=(gMasterSpiTrace.next+7)%8;
    assert(!memcmp(gMasterSpiTrace.entries[last].request,expected_request,256));
    assert(gMasterSpiTrace.entries[last].tx_arm[0]==0x42);
    /* A retirement request rewrites selected data only AFTER the source copy. */
    gSpiRetirementRequest.generation=19;gSpiRetirementRequest.context=91;
    memcpy(gReceiveSlots[gReceiveIndex],expected_request,256);remaining=0;retire_spi_boundary();
    last=(gMasterSpiTrace.next+7)%8;
    assert(gMasterSpiTrace.entries[last].tx_end[3]==2);
    assert(gTransmitSlots[gTransmitIndex][3]==0);
    uint32_t depth_before=gSpiReceiveQueue.depth,drops_before=gSpiReceiveQueue.dropped;
    uint32_t preceding=gMasterSpiTrace.ordinal;
    bodaqs_spi_trace_request(&traced,91,23,42,0x12345678,0xabcdef12);
    assert(bodaqs_measurement_encode(&traced,gReceiveSlots[gReceiveIndex],256));
    remaining=0;retire_spi_boundary();
    assert(gMasterSpiTrace.frozen && gMasterSpiTrace.marker_ordinal==preceding+1);
    assert(gMasterSpiTrace.context_low==91 && gMasterSpiTrace.nonce==23);
    assert(gSpiReceiveQueue.depth==depth_before && gSpiReceiveQueue.dropped==drops_before);
    BodaqsSpiTrace frozen_trace;memcpy(&frozen_trace,&gMasterSpiTrace,sizeof frozen_trace);
    memcpy(gReceiveSlots[gReceiveIndex],expected_request,256);remaining=0;retire_spi_boundary();
    assert(!memcmp(&frozen_trace,&gMasterSpiTrace,sizeof frozen_trace));
    puts("actual CS trace: queue overflow, pre-fence selected source, marker bypass, reset/rearm and immutable freeze PASS");
