    /* Real boundary enqueue, main pop, overflow and freeze; no timing helper
     * is replaced. The fixture supplies only the hardware clock's values. */
    bodaqs_master_service_init(&gService,NULL);
    bodaqs_record_queue_init(&gSpiReceiveQueue,gSpiReceiveStorage,256,4);
    bodaqs_record_queue_init(&gCanReceiveQueue,storage,sizeof storage[0],8);
    memset((void*)&gMasterDrainInfo,0,sizeof gMasterDrainInfo);
    gService.measurement.mode.phase=2;gService.measurement.mode.context=91;
    gService.measurement.mode.recording=92;
    uint8_t scope_wire[256],scope_reply[256];idle.context=91;
    assert(bodaqs_measurement_encode(&idle,scope_wire,256));
    assert(bodaqs_master_service_process_transfer(&gService,scope_wire,256,0,scope_reply)==BODAQS_MASTER_SLOT_PROCESSED);
    gService.acquisition_started=1;
    test_epoch=1;test_tick=1000;drain_check();assert(gMasterDrainInfo.version==4);
    idle.context=91;assert(bodaqs_measurement_encode(&idle,gReceiveSlots[gReceiveIndex],256));
    test_tick=1100;remaining=0;retire_spi_boundary();
    test_tick=1300;assert(bodaqs_measurement_encode(&idle,gReceiveSlots[gReceiveIndex],256));
    remaining=0;retire_spi_boundary();
    test_tick=1700;gSpiTransmitReady=false;service_spi_receive();
    assert(gMasterDrainInfo.spi_queue_wait_count==1);
    assert(gMasterDrainInfo.spi_queue_wait_total_us==600 && gMasterDrainInfo.spi_queue_wait_max_us==600);
    assert(gMasterDrainInfo.spi_queue_wait_hist[2]==1 && gMasterDrainInfo.spi_queue_depth_hist[2]==1);
    assert(gMasterDrainInfo.spi_queue_depth==1 && gMasterDrainInfo.spi_queue_peak==2);
    assert(gMasterDrainInfo.spi_queue_head_valid && gMasterDrainInfo.spi_queue_head_age_us==403);
    test_tick=1900;hardware_depth=1;capture_can_receive_fifo();drop_during_decode=true;service_can_receive();
    assert(gMasterDrainInfo.state==2 && gMasterDrainInfo.finish_reason==1);
    assert(gMasterDrainInfo.spi_queue_head_valid && gMasterDrainInfo.spi_queue_head_age_us==607);
    test_tick=3000;gSpiTransmitReady=false;service_spi_receive();
    assert(gMasterDrainInfo.spi_queue_wait_count==1 && gMasterDrainInfo.spi_queue_depth==1);
    /* A new recording resets aggregates, excludes pre-START cells, and
     * correlates each timestamp with its own FIFO cell across ring wrap. */
    gService.measurement.mode.context=93;gService.measurement.mode.recording=94;
    idle.context=93;assert(bodaqs_measurement_encode(&idle,scope_wire,256));
    assert(bodaqs_master_service_process_transfer(&gService,scope_wire,256,0,scope_reply)==BODAQS_MASTER_SLOT_PROCESSED);
    gService.acquisition_started=1;
    gService.ingress[0].dropped=0;test_tick=4000;drain_check();
    assert(gMasterDrainInfo.state==1 && !gMasterDrainInfo.spi_queue_wait_count);
    idle.context=93;
    bodaqs_record_queue_init(&gSpiReceiveQueue,gSpiReceiveStorage,256,4);
    for(unsigned i=0;i<5;++i) {
        test_tick=4100+i*100;assert(bodaqs_measurement_encode(&idle,gReceiveSlots[gReceiveIndex],256));
        remaining=0;retire_spi_boundary();
    }
    assert(gSpiReceiveQueue.depth==4 && gSpiReceiveQueue.dropped==1);
    for(unsigned i=0;i<4;++i) {
        test_tick=5000;gSpiTransmitReady=false;service_spi_receive();
    }
    assert(gMasterDrainInfo.spi_queue_wait_count==4 && gMasterDrainInfo.spi_queue_wait_total_us==3000);
    for(unsigned i=1;i<=4;++i) assert(gMasterDrainInfo.spi_queue_depth_hist[i]==1);
    /* Pre-START timestamps and stale-context requests never enter the mean. */
    test_tick=3900;assert(bodaqs_measurement_encode(&idle,gReceiveSlots[gReceiveIndex],256));
    remaining=0;retire_spi_boundary();test_tick=6000;gSpiTransmitReady=false;service_spi_receive();
    assert(gMasterDrainInfo.spi_queue_wait_count==4 && gMasterDrainInfo.spi_queue_wait_excluded==1);
    idle.context=91;assert(bodaqs_measurement_encode(&idle,gReceiveSlots[gReceiveIndex],256));
    remaining=0;retire_spi_boundary();gSpiTransmitReady=false;service_spi_receive();
    assert(gMasterDrainInfo.spi_queue_wait_count==4 && gMasterDrainInfo.spi_queue_wait_excluded==2);
    /* Malformed/short slots are not accepted timing observations. */
    idle.context=93;assert(bodaqs_measurement_encode(&idle,gReceiveSlots[gReceiveIndex],256));
    remaining=1;retire_spi_boundary();gSpiTransmitReady=false;service_spi_receive();
    assert(gMasterDrainInfo.spi_queue_wait_count==4);
    /* Clock fault/epoch mismatch cannot produce plausible queue times. */
    test_epoch=0;assert(bodaqs_measurement_encode(&idle,gReceiveSlots[gReceiveIndex],256));
    remaining=0;retire_spi_boundary();test_epoch=1;gSpiTransmitReady=false;service_spi_receive();
    assert(gMasterDrainInfo.spi_queue_time_invalid==1 && gMasterDrainInfo.timing_invalid);
    /* Unsigned low32 wrap in the same epoch is valid for this short scope. */
    gService.measurement.mode.context=95;gService.measurement.mode.recording=96;
    idle.context=95;assert(bodaqs_measurement_encode(&idle,scope_wire,256));
    assert(bodaqs_master_service_process_transfer(&gService,scope_wire,256,0,scope_reply)==BODAQS_MASTER_SLOT_PROCESSED);
    gService.acquisition_started=1;
    test_tick=UINT32_MAX-100;drain_check();drain_check();
    assert(gMasterDrainInfo.state==1 && !gMasterDrainInfo.spi_queue_wait_count);
    idle.context=95;test_tick=UINT32_MAX-50;
    assert(bodaqs_measurement_encode(&idle,gReceiveSlots[gReceiveIndex],256));remaining=0;retire_spi_boundary();
    test_tick=49;gSpiTransmitReady=false;service_spi_receive();
    assert(gMasterDrainInfo.spi_queue_wait_count==1 && gMasterDrainInfo.spi_queue_wait_total_us==100);
    /* An actual boundary immediately before the pop masks IRQs must append
     * its own metadata without replacing the older head's length/time/payload. */
    gService.measurement.mode.context=97;gService.measurement.mode.recording=98;
    idle.context=97;assert(bodaqs_measurement_encode(&idle,scope_wire,256));
    assert(bodaqs_master_service_process_transfer(&gService,scope_wire,256,0,scope_reply)==BODAQS_MASTER_SLOT_PROCESSED);
    gService.acquisition_started=1;test_tick=10000;drain_check();drain_check();
    test_tick=10100;assert(bodaqs_measurement_encode(&idle,gReceiveSlots[gReceiveIndex],256));
    remaining=0;retire_spi_boundary();
    idle.context=99;assert(bodaqs_measurement_encode(&idle,gReceiveSlots[gReceiveIndex],256));
    inject_spi_tick=10800;inject_spi_length=255;inject_spi_on_pop=true;
    gSpiTransmitReady=false;service_spi_receive();
    assert(!inject_spi_on_pop && gMasterDrainInfo.spi_queue_wait_count==1);
    assert(gMasterDrainInfo.spi_queue_wait_total_us==700 && gMasterDrainInfo.spi_queue_depth_hist[2]==1);
    assert(gMasterDrainInfo.spi_queue_head_age_us==3 && gMasterDrainInfo.spi_queue_depth==1);
    assert(gSpiReceiveLengths[gSpiReceiveQueue.head]==255 && !irq_mask);
    gSpiTransmitReady=false;service_spi_receive();assert(gMasterDrainInfo.spi_queue_wait_count==1);
    /* Arrival before a head-age snapshot also remains one coherent FIFO cell. */
    idle.context=97;assert(bodaqs_measurement_encode(&idle,gReceiveSlots[gReceiveIndex],256));
    inject_spi_tick=10900;inject_spi_length=256;inject_spi_on_sample=true;
    drain_queue_sample();
    assert(!inject_spi_on_sample && gMasterDrainInfo.spi_queue_depth==1);
    assert(gMasterDrainInfo.spi_queue_head_valid && !gMasterDrainInfo.spi_queue_head_age_us && !irq_mask);
    puts("production queue timing: cell ownership, waiting age/depth, overflow, scope, freeze and clock wrap PASS");
