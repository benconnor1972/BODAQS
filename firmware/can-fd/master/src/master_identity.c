#include "master_identity.h"
#include "bodaqs_measurement.h"
#include "bodaqs_control.h"

#include <ti/driverlib/driverlib.h>
#include "ti_msp_dl_config.h"
#include "bodaqs_can_link_ti.h"

BodaqsMasterIdentity master_identity_read(void)
{
    BodaqsMasterIdentity identity = {0};
    uint32_t device_description;

    device_description = ((uint32_t) DL_FactoryRegion_getPartNumber() << 16) |
        ((uint32_t) DL_FactoryRegion_getUserIDVariant() << 8) |
        ((uint32_t) DL_FactoryRegion_getUserIDMajorRev() << 4) |
        (uint32_t) DL_FactoryRegion_getUserIDMinorRev();

    identity.firmware_version = BODAQS_MASTER_FIRMWARE_VERSION;
    identity.capabilities = BODAQS_MEASUREMENT_CAPABILITY | BODAQS_MASTER_CAPABILITY_STATUS |
        BODAQS_MASTER_CAPABILITY_DISCOVERY | BODAQS_CONTROL_CAPABILITY |
        bodaqs_can_link_capability(bodaqs_can_link_active(MCAN0_INST));
    #if defined(BODAQS_PACKED_EXCHANGE) && BODAQS_PACKED_EXCHANGE
    identity.capabilities |= 0x20U;
    #if defined(BODAQS_PACKED_PROGRESS) && BODAQS_PACKED_PROGRESS
    identity.capabilities |= 0x40U;
    #endif
#endif
    identity.hardware_uid = ((uint64_t) device_description << 32) |
        DL_FactoryRegion_getTraceID();
    identity.minimum_protocol_version = BODAQS_MASTER_PROTOCOL_VERSION;
    identity.maximum_protocol_version = BODAQS_MASTER_PROTOCOL_VERSION;
    return identity;
}


/* Fresh platform randomness, independent of UID and uptime. Fail closed until
 * the peripheral provides a nonzero identity. */
uint64_t master_control_boot_id_read(void)
{
    uint64_t boot;
    do {
        uint32_t low, high;
        while (!DL_TRNG_isCaptureReady(TRNG)) { ; }
        DL_TRNG_clearInterruptStatus(TRNG, DL_TRNG_INTERRUPT_CAPTURE_RDY_EVENT);
        low = DL_TRNG_getCapture(TRNG);
        while (!DL_TRNG_isCaptureReady(TRNG)) { ; }
        DL_TRNG_clearInterruptStatus(TRNG, DL_TRNG_INTERRUPT_CAPTURE_RDY_EVENT);
        high = DL_TRNG_getCapture(TRNG);
        boot = ((uint64_t)high << 32) | low;
    } while (boot == 0U);
    DL_TRNG_disablePower(TRNG);
    return boot;
}
