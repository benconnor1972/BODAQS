    /* A full CAN burst plus a queued SPI request. ISR refill leaves one record,
     * but each turn still reaches SPI and never drains unbounded CAN work. */
    bodaqs_master_service_init(&gService,NULL);
    memset((void *)&gMasterDrainInfo,0,sizeof gMasterDrainInfo);
    memset(gRejectedCan,0,sizeof gRejectedCan);
    memset((void *)&gSpiRetirementRequest,0,sizeof gSpiRetirementRequest);
    memset((void *)&gSpiRetirementProof,0,sizeof gSpiRetirementProof);
    bodaqs_record_queue_init(&gCanReceiveQueue,storage,sizeof storage[0],8);
    bodaqs_record_queue_init(&gSpiReceiveQueue,gSpiReceiveStorage,256,capacity);
    gService.measurement.mode.phase=2;gService.measurement.mode.context=77;
    gService.control.master_boot_id=1;
    gSpiTransmitReady=false;processed_can=0;processed_ordinal=0;gCanReceiveOrdinal=0;
    hardware=(DL_MCAN_RxBufElement){.id=0x100U<<18,.fdf=1,.brs=1,.dlc=15};
    hardware.data[2]=3;hardware.data[3]=5;
    hardware_depth=8;capture_can_receive_fifo();refill_during_decode=true;
    BodaqsMeasurementSlot order_idle={0};
    order_idle.node=255;order_idle.context=77;
    uint8_t order_wire[256];
    assert(bodaqs_measurement_encode(&order_idle,order_wire,sizeof order_wire));
    gSpiReceiveLengths[gSpiReceiveQueue.tail]=256;
    assert(bodaqs_record_queue_push(&gSpiReceiveQueue,order_wire));
    service_receive_queues();
    assert(gSpiTransmitReady && gService.slots_received==1);
    assert(processed_can==8 && gCanReceiveQueue.depth==1 && !gCanReceiveQueue.dropped);
    assert(can_seen_at_spi==(BODAQS_MASTER_CAN_FIRST?8U:0U));
    /* A full outgoing SPI publication cannot prevent CAN service next turn. */
    service_receive_queues();
    assert(processed_can==9 && !gCanReceiveQueue.depth && gService.slots_received==1);
    puts("production receive-turn ordering and bounded CAN/SPI service: PASS");
    static CanReceiveRecord burst_storage[32];
    bodaqs_record_queue_init(&gCanReceiveQueue,burst_storage,sizeof burst_storage[0],32);
    processed_can=0;
    for(unsigned burst=0;burst<4;++burst) {hardware_depth=8;capture_can_receive_fifo();}
    assert(gCanReceiveQueue.depth==32 && !gCanReceiveQueue.dropped);
    service_can_receive();
    assert(processed_can==8 && gCanReceiveQueue.depth==24);
    for(unsigned turn=0;turn<3;++turn) service_can_receive();
    assert(processed_can==32 && !gCanReceiveQueue.depth);
    puts("32 captured CAN receptions survive burst; each turn retires only8: PASS");
