#include "master_identity.h"

#include <ti/driverlib/driverlib.h>

BodaqsMasterIdentity master_identity_read(void)
{
    BodaqsMasterIdentity identity = {0};
    uint32_t device_description;

    device_description = ((uint32_t) DL_FactoryRegion_getPartNumber() << 16) |
        ((uint32_t) DL_FactoryRegion_getUserIDVariant() << 8) |
        ((uint32_t) DL_FactoryRegion_getUserIDMajorRev() << 4) |
        (uint32_t) DL_FactoryRegion_getUserIDMinorRev();

    identity.firmware_version = BODAQS_MASTER_FIRMWARE_VERSION;
    identity.capabilities = BODAQS_MASTER_CAPABILITY_STATUS |
        BODAQS_MASTER_CAPABILITY_DISCOVERY;
    identity.hardware_uid = ((uint64_t) device_description << 32) |
        DL_FactoryRegion_getTraceID();
    identity.minimum_protocol_version = BODAQS_MASTER_PROTOCOL_VERSION;
    identity.maximum_protocol_version = BODAQS_MASTER_PROTOCOL_VERSION;
    return identity;
}

