#ifndef BODAQS_IMU_DISABLED_H
#define BODAQS_IMU_DISABLED_H
#include <stdbool.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C"
{
#endif
    /* One nonblocking register exchange. Repeated calls poll the same exchange:
     * -1 transport failure, 0 pending, 1 complete. No callback may wait for IO. */
    typedef int (*BodaqsImuRegister)(void *, bool write, uint8_t address, uint8_t *value,
                                     uint32_t now);
    typedef void (*BodaqsImuCancel)(void *);
    typedef struct
    {
        BodaqsImuRegister reg;
        BodaqsImuCancel cancel;
        void *context;
        uint32_t started, reset_started;
        uint8_t phase, index, value, bank_low, bank, reason;
        uint8_t image[24], mismatch_address, expected, observed, mask;
        bool no_op, changed;
    } BodaqsImuDisabled;
    void bodaqs_imu_disabled_init(BodaqsImuDisabled *, BodaqsImuRegister, BodaqsImuCancel, void *);
    void bodaqs_imu_disabled_start(BodaqsImuDisabled *, bool previously_verified, uint32_t now);
    /* 0 pending, 1 verified, -1 failure; total budget 2000ms, reset budget 100ms. */
    int bodaqs_imu_disabled_tick(BodaqsImuDisabled *, uint32_t now);
    void bodaqs_imu_disabled_cancel(BodaqsImuDisabled *);
#ifdef __cplusplus
}
#endif
#endif
