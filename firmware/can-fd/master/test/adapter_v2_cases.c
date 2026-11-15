int main(void) {
    const unsigned capacity=BODAQS_MASTER_SPI_RX_CAPACITY;
    assert(BODAQS_MASTER_TRANSFER_BYTES==256 && (capacity==2 || capacity==4));
    bodaqs_record_queue_init(&gSpiReceiveQueue,gSpiReceiveStorage,256,capacity);
    bodaqs_master_service_init(&gService,NULL);
    bodaqs_record_queue_init(&gCanReceiveQueue,storage,sizeof storage[0],8);
    hardware=(DL_MCAN_RxBufElement){.id=0x100U<<18,.fdf=1,.brs=1,.dlc=15};
    hardware.data[2]=3;hardware.data[3]=5;hardware_depth=8;capture_can_receive_fifo();
    hardware_depth=1;capture_can_receive_fifo();
    hardware.id=0x90U<<18;hardware.dlc=13;hardware.data[1]=0x22;hardware.data[10]=3;hardware.data[13]=0xaa;
    hardware_depth=1;capture_can_receive_fifo();
    hardware.dlc=15;hardware.data[1]=0x24;hardware.data[13]=3;
    hardware_depth=1;capture_can_receive_fifo();
    hardware.dlc=12;hardware.data[1]=0x21;hardware.data[13]=0xab;
    hardware_depth=1;capture_can_receive_fifo();
    assert(gRejectedCan[0].source==5 && gRejectedCan[0].evidence==3 && gRejectedCan[0].epoch==3);
    assert(!gRejectedCan[0].essential); // raw tick/sequence bytes are not stream epochs
    hardware.dlc=15;hardware.data[1]=0x25;hardware.data[13]=3;hardware.data[14]=2;
    hardware_depth=1;capture_can_receive_fifo();assert(gRejectedCan[0].essential);
    gService.measurement.mode.phase=2;gService.measurement.mode.context=77;
    const unsigned lengths[4]={84,256,255,256};
    for(unsigned i=0;i<capacity;++i) {
        memset(gReceiveSlots[gReceiveIndex],i+1,256);
        remaining=256-lengths[i];retire_spi_boundary();
    }
    assert(gSpiReceiveQueue.depth==capacity && !gSpiReceiveQueue.dropped);
    remaining=0;retire_spi_boundary();
    assert(gSpiReceiveQueue.depth==capacity && gSpiReceiveQueue.dropped==1);
    for(unsigned i=0;i<capacity;++i) {
        assert(gSpiReceiveLengths[gSpiReceiveQueue.head]==lengths[i]);
        uint8_t bytes[256];assert(bodaqs_record_queue_pop(&gSpiReceiveQueue,bytes));
        assert(bytes[0]==i+1 && bytes[255]==i+1);
    }
    /* Exact physical extent: valid 256, short255 and excess257. */
    BodaqsMeasurementSlot idle={0};idle.node=255;idle.context=77;
    assert(bodaqs_measurement_encode(&idle,gReceiveSlots[gReceiveIndex],256));
    remaining=0;retire_spi_boundary();gSpiTransmitReady=false;
    service_spi_receive();assert(gSpiTransmitReady && gService.slots_received==1);
    assert(bodaqs_measurement_encode(&idle,gReceiveSlots[gReceiveIndex],256));
    remaining=1;retire_spi_boundary();gSpiTransmitReady=false;
    service_spi_receive();assert(!gSpiTransmitReady && gService.malformed_slots==1);
    assert(bodaqs_measurement_encode(&idle,gReceiveSlots[gReceiveIndex],256));
    remaining=0;extra_rx_byte=true;retire_spi_boundary();gSpiTransmitReady=false;
    service_spi_receive();assert(!gSpiTransmitReady && gService.malformed_slots==2);
    /* Fully prepared data is scrubbed at the exact captured fence generation;
     * ISR proof alone never edits retained service rings. */
    BodaqsMeasurementSlot data={0};data.kind=2;data.context=77;data.node=0;
    assert(bodaqs_measurement_encode(&data,gTransmitSlots[0],256));
    assert(bodaqs_measurement_encode(&data,gTransmitSlots[1],256));
    gSpiTransmitReady=true;gService.receptions[0].count=2;
    gService.acquisition_retirement_pending=true;gService.acquisition_retirement_generation=1;
    service_spi_retirement();
    assert(bodaqs_measurement_encode(&idle,gReceiveSlots[gReceiveIndex],256));
    /* DMA completion is not physical CS retirement. Even with a published
     * fence request, no queue/swap/reset/proof may occur while CS is low. */
    const unsigned saved_depth=gSpiReceiveQueue.depth,saved_reset=reset_count,saved_arm=arm_count;
    const unsigned saved_tx=gTransmitIndex,saved_rx=gReceiveIndex;
    const uint32_t saved_proof=gSpiRetirementProof.generation;
    uint8_t owned_before[2][BODAQS_MEASUREMENT_BYTES];memcpy(owned_before,gTransmitSlots,sizeof owned_before);
    remaining=0;cs_high=0;retire_spi_boundary();
    assert(gSpiReceiveQueue.depth==saved_depth && reset_count==saved_reset && arm_count==saved_arm);
    assert(gTransmitIndex==saved_tx && gReceiveIndex==saved_rx && gSpiTransmitReady);
    assert(gSpiRetirementProof.generation==saved_proof && gService.receptions[0].count==2);
    assert(!memcmp(owned_before,gTransmitSlots,sizeof owned_before));
    cs_high=1;prefetched_tx=1;
    remaining=0;retire_spi_boundary();
    BodaqsMeasurementSlot decoded;
    assert(bodaqs_measurement_decode(gTransmitSlots[0],256,&decoded) && !decoded.kind);
    assert(bodaqs_measurement_decode(gTransmitSlots[1],256,&decoded) && !decoded.kind);
    assert(gService.receptions[0].count==2 && gSpiRetirementProof.generation==1);
    service_spi_retirement();
    assert(!gService.receptions[0].count && !gService.acquisition_retirement_pending);
#if defined(BODAQS_MASTER_PHASE_TIMING) && BODAQS_MASTER_PHASE_TIMING
    gMasterDrainInfo.state=1;
    memset((void*)gMasterDrainInfo.phase_calls,0,sizeof gMasterDrainInfo.phase_calls);
    memset((void*)gMasterDrainInfo.phase_total_us,0,sizeof gMasterDrainInfo.phase_total_us);
    memset((void*)gMasterDrainInfo.phase_max_us,0,sizeof gMasterDrainInfo.phase_max_us);
    bodaqs_master_profile_record(11,22,33,14,0);
    bodaqs_master_profile_record(3,4,5,14,2);
    bodaqs_master_profile_record(7,8,9,1,0);
    bodaqs_master_profile_record(10,20,30,1,2);
    bodaqs_master_profile_record(6,7,8,6,6);
    assert(gMasterDrainInfo.phase_calls[0]==2 && gMasterDrainInfo.phase_total_us[0][0]==14);
    assert(gMasterDrainInfo.phase_max_us[0][2]==33);
    assert(gMasterDrainInfo.phase_calls[1]==1 && gMasterDrainInfo.phase_total_us[1][1]==8);
    assert(gMasterDrainInfo.phase_calls[2]==1 && gMasterDrainInfo.phase_calls[3]==1);
    gMasterDrainInfo.state=2;
    bodaqs_master_profile_record(100,100,100,14,0);
    assert(gMasterDrainInfo.phase_calls[0]==2 && bodaqs_master_profile_clock()==0);
    gService.measurement.mode.context=123;gService.measurement.mode.recording=456;
    gService.acquisition_started=1;drain_check();
#if defined(BODAQS_MASTER_QUEUE_TIMING) && BODAQS_MASTER_QUEUE_TIMING
    assert(gMasterDrainInfo.version==5 && gMasterDrainInfo.phase_calls[0]==0);
#else
    assert(gMasterDrainInfo.version==5 && gMasterDrainInfo.phase_calls[0]==0);
#endif
    puts("production phase classification, accumulation, freeze and new-scope reset: PASS");
    memset((void *)&gMasterSteadyInfo,0,sizeof gMasterSteadyInfo);
    const uint32_t warm=UINT32_MAX-1000000U;
    steady_observe(901,1,true,warm,1);
    assert(gMasterSteadyInfo.state==1);
    steady_observe(901,1,true,warm+5000000U,1);
    assert(gMasterSteadyInfo.state==2);
    gMasterDrainInfo.state=2; /* Loss froze original diagnostics, not this window. */
    bodaqs_master_profile_record(10,20,30,1,2);
    assert(gMasterSteadyInfo.phase_calls[2]==1 && gMasterSteadyInfo.phase_total_us[2][2]==30);
    steady_observe(901,1,true,warm+35000000U,1);
    assert(gMasterSteadyInfo.state==3 && gMasterSteadyInfo.finish_reason==1);
    bodaqs_master_profile_record(10,20,30,1,2);
    assert(gMasterSteadyInfo.phase_calls[2]==1);
    steady_observe(901,1,false,warm+36000000U,1);
    assert(gMasterSteadyInfo.finish_reason==1);
    steady_observe(902,2,true,100,1);
    assert(gMasterSteadyInfo.state==1 && !gMasterSteadyInfo.phase_calls[2]);
    steady_observe(902,2,false,200,1);
    assert(gMasterSteadyInfo.finish_reason==2 && gMasterSteadyInfo.state==3);
    steady_observe(903,3,true,100,1);steady_observe(903,3,true,101,0);
    assert(gMasterSteadyInfo.timing_invalid && gMasterSteadyInfo.finish_reason==4);
    puts("steady acquisition window: wrap, loss independence, bounded freeze, STOP/reset/clock validity PASS");
#endif
    /* QUEUE_TIMING_CASES */
    /* RX_RETRY_CASES */
    printf("production v2 CS/DMA extent, %u-cell length ownership and fence retirement: PASS\n",capacity);
}
