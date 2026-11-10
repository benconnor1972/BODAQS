    {
        /* The public physical adapter must attribute combined retirement to
         * the predecessor, even when the fetch selects another class/node. */
        bodaqs_master_service_init(&gService,NULL);
        bodaqs_record_queue_init(&gSpiReceiveQueue,gSpiReceiveStorage,256,capacity);
        memset((void*)&gMasterDrainInfo,0,sizeof gMasterDrainInfo);
        memset(gRejectedCan,0,sizeof gRejectedCan);
        gSpiRetirementRequest=(SpiRetirement){0};gSpiRetirementProof=(SpiRetirement){0};
        gSpiTransmitReady=false;gService.measurement.mode.phase=2;
        gService.measurement.mode.context=901;gService.measurement.mode.recording=11;
        gService.measurement.fenced=false;
        BodaqsMeasurementSlot idle={0},ack,invalid;
        uint8_t tx[256],reply[256];idle.context=901;idle.node=255;
        assert(bodaqs_measurement_encode(&idle,tx,256));
        assert(bodaqs_master_service_process_transfer(&gService,tx,256,0,reply)==BODAQS_MASTER_SLOT_PROCESSED);
        gService.acquisition_started=1;test_epoch=1;drain_check();
        BodaqsReceptionBatch *old=&gService.receptions[0],*next=&gService.receptions[1];
        old->cls=1;old->count=3;old->bytes[0]=1;old->bytes[2]=3;
        next->cls=2;next->count=1;next->bytes[0]=1;next->bytes[2]=1;
        assert(bodaqs_fragment_seal(&old->object,old->bytes,1024,901,17,0,1,1,228));
        assert(bodaqs_fragment_seal(&next->object,next->bytes,1024,901,23,1,2,1,88));
        bodaqs_fragment_ack(&old->object,1,&ack);ack.kind=14;ack.body[2]=2;ack.body[3]=1;
        invalid=ack;invalid.body[4]^=1;
#define SUBMIT_ACCOUNTING_SLOT(q) do { \
        assert(bodaqs_measurement_encode(&(q),tx,256)); \
        memcpy(gReceiveSlots[gReceiveIndex],tx,256);remaining=0;retire_spi_boundary(); \
        service_spi_receive();assert(gSpiTransmitReady); \
    } while(0)
        SUBMIT_ACCOUNTING_SLOT(invalid);
        assert(!gMasterDrainInfo.data_acked_objects[0] && old->count==3);
        SUBMIT_ACCOUNTING_SLOT(ack);
        assert(gMasterDrainInfo.data_acked_objects[0]==1);
        assert(gMasterDrainInfo.data_acked_records[0]==3);
        assert(!gMasterDrainInfo.data_acked_objects[1] && next->count==1);
        SUBMIT_ACCOUNTING_SLOT(ack);
        assert(gMasterDrainInfo.data_acked_objects[0]==1 && gMasterDrainInfo.data_acked_records[0]==3);
        assert(gMasterDrainInfo.ack_fetches[0]==3 && gMasterDrainInfo.ack_fetch_targets[1]==3);
        assert(!gMasterDrainInfo.acks[0]); // Separate-ACK denominator stays separate.
        assert(gMasterDrainInfo.version==5);
        unsigned layout=0;
#if defined(BODAQS_MASTER_PHASE_TIMING) && BODAQS_MASTER_PHASE_TIMING
        layout|=1;
#endif
#if defined(BODAQS_MASTER_QUEUE_TIMING) && BODAQS_MASTER_QUEUE_TIMING
        layout|=2;
#endif
        assert(gMasterDrainInfo.layout_flags==layout && gMasterDrainInfo.size_bytes==sizeof(gMasterDrainInfo));
#undef SUBMIT_ACCOUNTING_SLOT
        puts("actual ACK_FETCH accounting: old multi-record batch, cross-class fetch, invalid proof and duplicate PASS");
    }
    {
        /* Actual queue overflow drops a new ACK_FETCH, not retained sensor
         * data. Validate the logical batch before constructing that ACK, then
         * drive retries through real boundary publication/main service. */
        bodaqs_master_service_init(&gService,NULL);
        bodaqs_record_queue_init(&gSpiReceiveQueue,gSpiReceiveStorage,256,capacity);
        gSpiRetirementRequest=(SpiRetirement){0};gSpiRetirementProof=(SpiRetirement){0};
        gSpiTransmitReady=false;gService.measurement.mode.phase=2;
        gService.measurement.mode.context=101;gService.measurement.fenced=false;
        BodaqsMeasurementSlot tickle={0},fragment,ack,reply;
        uint8_t tx[256],wire[256],accepted[1024];BodaqsFragmentState receiver={0};
        tickle.context=101;tickle.node=255;
        assert(bodaqs_measurement_encode(&tickle,tx,256));
        assert(bodaqs_master_service_process_transfer(&gService,tx,256,0,wire)==BODAQS_MASTER_SLOT_PROCESSED);
        BodaqsReceptionBatch *batch=&gService.receptions[0];
        batch->cls=1;batch->count=1;batch->bytes[0]=1;batch->bytes[2]=1;
        batch->bytes[4]=17;batch->bytes[12]=1;batch->bytes[17]=1;batch->bytes[18]=64;
        batch->bytes[30]=1;batch->bytes[31]=5;
        assert(bodaqs_fragment_seal(&batch->object,batch->bytes,1024,101,1,0,1,1,92));
        assert(bodaqs_fragment_emit(&batch->object,batch->bytes,0,&fragment));
        assert(bodaqs_fragment_accept(&receiver,accepted,sizeof accepted,&fragment,1,&ack)==1);
        assert(receiver.complete && !memcmp(accepted,batch->bytes,96));
        ack.kind=14;ack.body[2]=1;ack.body[3]=0;
        for(unsigned i=0;i<capacity;++i) {
            memcpy(gReceiveSlots[gReceiveIndex],tx,256);remaining=0;retire_spi_boundary();
        }
        assert(gSpiReceiveQueue.depth==capacity);
        assert(bodaqs_measurement_encode(&ack,tx,256));
        memcpy(gReceiveSlots[gReceiveIndex],tx,256);remaining=0;retire_spi_boundary();
        assert(gSpiReceiveQueue.dropped==1 && !gService.objects_acked && batch->object.complete);
        service_spi_receive();assert(gSpiTransmitReady && !gService.objects_acked);
        for(unsigned i=0;i<capacity;++i) {
            memcpy(gReceiveSlots[gReceiveIndex],tx,256);remaining=0;retire_spi_boundary();
            service_spi_receive();
            assert(gService.objects_acked==(i+1==capacity?1U:0U));
        }
        assert(!batch->count && !batch->object.complete);
        /* Ignore the first delivered proof and keep retrying the immutable
         * ACK. Cached confirmation must return without retiring anything twice. */
        for(unsigned i=0;i<3;++i) {
            memcpy(wire,gTransmitSlots[gTransmitIndex],256);
            memcpy(gReceiveSlots[gReceiveIndex],tx,256);remaining=0;retire_spi_boundary();
            service_spi_receive();assert(gService.objects_acked==1);
        }
        assert(bodaqs_measurement_decode(wire,256,&reply) && reply.retired);
        assert(reply.context==101 && reply.retiredClass==1 && reply.retiredNode==0);
        assert(reply.retiredObject==receiver.object && reply.retiredTotal==receiver.total);
        assert(reply.retiredChecksum==receiver.checksum && !reply.kind);
        printf("production %u-cell full-queue ACK_FETCH loss, retry and exact retirement proof PASS\n",capacity);
    }
