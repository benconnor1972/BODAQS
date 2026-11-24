#include "bodaqs_imu_disabled.h"
#include <string.h>
/* DS13607 / exact-part ST bitfields; expected bytes are the agreed disabled
 * baseline image (enabled ODR fields are selected below), masks exclude reserved fields and include self-clearing commands. */
typedef struct
{
    uint8_t bank, address, expected, mask;
} Owned;
static const Owned owned[] = {
    {0, 7, 0, 0xff},      {0, 8, 0, 0xd7},     {0, 9, 0, 0xff},    {0, 10, 0, 0xf7},
    {0, 11, 0, 0xe7},     {0, 12, 0, 0xff},    {0, 13, 0, 0xff},   {0, 14, 0, 0x7f},
    {0, 15, 0x6c, 0xff},  {0, 16, 4, 0xfe},    {0, 17, 12, 0xfe},  {0, 18, 0x44, 0xfd},
    {0, 19, 12, 0x6e},    {0, 20, 0, 0xef},    {0, 21, 0, 0xff},   {0, 22, 0, 0xf2},
    {0, 23, 0, 0xfd},     {0, 24, 0xe2, 0xfe}, {0, 25, 0, 0x20},   {0, 1, 0, 0xc0},
    {0, 0x5e, 0, 0xff},   {0, 0x5f, 0, 0xff},  {0x80, 4, 0, 0x38}, {0x80, 5, 0, 0x19},
    {0x40, 0x14, 0, 0x14}};
enum
{
    WAIT = 1,
    BANK_READ,
    BANK_WRITE,
    BANK_VERIFY,
    IDENTITY,
    RESET_READ,
    RESET_WRITE,
    RESET_POLL,
    RESET_ID,
    RESET_BANK_READ,
    SELECT_BANK,
    SELECT_VERIFY,
    READ,
    WRITE,
    RESTORE,
    RESTORE_VERIFY,
    DONE,
    FAILED
};
void bodaqs_imu_disabled_init(BodaqsImuDisabled *s, BodaqsImuRegister r, BodaqsImuCancel c,
                              void *ctx)
{
    memset(s, 0, sizeof(*s));
    s->profile_id = 1;
    s->reg = r;
    s->cancel = c;
    s->context = ctx;
}
void bodaqs_imu_disabled_cancel(BodaqsImuDisabled *s)
{
    if (s->cancel)
        s->cancel(s->context);
}
void bodaqs_imu_disabled_start(BodaqsImuDisabled *s, bool verified, uint32_t now)
{
    s->enabled = false;
    s->started = now;
    s->phase = WAIT;
    s->index = 0;
    s->bank = 0;
    s->reason = 0;
    s->no_op = verified;
    s->changed = false;
    s->proof_invalid = false;
    s->mismatch_address = s->expected = s->observed = s->mask = 0;
    memset(s->image, 0, sizeof(s->image));
}
void bodaqs_imu_profile_start(BodaqsImuDisabled *s, bool enabled, bool verified, uint32_t now)
{
    bodaqs_imu_disabled_start(s, verified, now);
    s->enabled = enabled;
    if(enabled && !bodaqs_imu_profile_rate(s->profile_id)){s->reason=3;s->phase=FAILED;}
}
static int fail(BodaqsImuDisabled *s, uint8_t reason)
{
    s->reason = reason;
    s->phase = FAILED;
    bodaqs_imu_disabled_cancel(s);
    return -1;
}
int bodaqs_imu_disabled_tick(BodaqsImuDisabled *s, uint32_t now)
{
    int rc;
    const Owned *o;
    uint8_t expected;
    if (s->phase == DONE)
        return 1;
    if (s->phase == FAILED)
        return -1;
    if ((uint32_t)(now - s->started) >= 2000)
        return fail(s, 18);
    if (!s->reg)
        return fail(s, 14);
    if (s->phase == WAIT)
    {
        if ((uint32_t)(now - s->started) >= 10)
            s->phase = BANK_READ;
        return 0;
    }
    if (s->phase == RESET_POLL && (uint32_t)(now - s->reset_started) >= 100)
        return fail(s, 16);
    o = &owned[s->index];
    expected = o->expected;
    if (s->enabled && !o->bank && (o->address == 16 || o->address == 17)) expected |= bodaqs_imu_profile_odr(s->profile_id);
    switch (s->phase)
    {
    case BANK_READ:
    case RESET_BANK_READ:
    case BANK_VERIFY:
    case SELECT_VERIFY:
    case RESTORE_VERIFY:
        rc = s->reg(s->context, false, 1, &s->value, now);
        break;
    case BANK_WRITE:
        s->value = s->bank_low;
        rc = s->reg(s->context, true, 1, &s->value, now);
        break;
    case IDENTITY:
    case RESET_ID:
        rc = s->reg(s->context, false, 15, &s->value, now);
        break;
    case RESET_READ:
    case RESET_POLL:
        rc = s->reg(s->context, false, 18, &s->value, now);
        break;
    case RESET_WRITE:
        /* A submitted write may already have changed hardware while SPI is
         * pending or fails. Invalidate current proof in that same loop turn. */
        if (!s->changed)
            s->reset_started = now;
        s->changed = true;
        rc = s->reg(s->context, true, 18, &s->value, now);
        break;
    case SELECT_BANK:
        s->value = s->bank_low | o->bank;
        rc = s->reg(s->context, true, 1, &s->value, now);
        break;
    case READ:
        rc = s->reg(s->context, false, o->address, &s->value, now);
        break;
    case WRITE:
        rc = s->reg(s->context, true, o->address, &s->value, now);
        break;
    case RESTORE:
        s->value = s->bank_low;
        rc = s->reg(s->context, true, 1, &s->value, now);
        break;
    default:
        return fail(s, 14);
    }
    if (rc < 0)
        return fail(s, 14);
    if (!rc)
        return 0;
    switch (s->phase)
    {
    case BANK_READ:
        s->bank_low = s->value & 0x3f;
        s->phase = BANK_WRITE;
        break;
    case BANK_WRITE:
        s->phase = BANK_VERIFY;
        break;
    case BANK_VERIFY:
    case SELECT_VERIFY:
    case RESTORE_VERIFY:
        if ((s->value & 0xc0) != (s->phase == SELECT_VERIFY ? o->bank : 0))
        {
            s->mismatch_address = 1;
            s->expected = s->phase == SELECT_VERIFY ? o->bank : 0;
            s->observed = s->value & 0xc0;
            s->mask = 0xc0;
            return fail(s, 17);
        }
        if (s->phase == BANK_VERIFY)
        {
            s->bank = 0;
            s->phase = IDENTITY;
        }
        else if (s->phase == SELECT_VERIFY)
        {
            s->bank = o->bank;
            s->phase = READ;
        }
        else
        {
            s->bank = 0;
            if (!s->changed && !s->no_op)
                s->phase = RESET_READ;
            else
            {
                s->phase = DONE;
                return 1;
            }
        }
        break;
    case IDENTITY:
    case RESET_ID:
        if (s->value != 0x6c)
            return fail(s, 15);
        s->phase = s->phase == RESET_ID ? RESET_BANK_READ : s->no_op ? READ : RESET_READ;
        break;
    case RESET_BANK_READ:
        if (s->value & 0xc0)
        {
            s->mismatch_address = 1;
            s->expected = 0;
            s->observed = s->value & 0xc0;
            s->mask = 0xc0;
            return fail(s, 17);
        }
        s->bank_low = s->value & 0x3f;
        s->phase = READ;
        break;
    case RESET_READ:
        s->value = (s->value & 0x7e) | 1;
        s->phase = RESET_WRITE;
        break;
    case RESET_WRITE:
        s->changed = true;
        s->no_op = false;
        s->phase = RESET_POLL;
        break;
    case RESET_POLL:
        if (!(s->value & 1))
        {
            s->phase = RESET_ID;
            s->index = 0;
            s->bank = 0;
            s->bank_low = 0;
        }
        break;
    case SELECT_BANK:
        s->phase = SELECT_VERIFY;
        break;
    case READ:
        if (s->index < 22)
            s->image[s->index] = s->value;
        if (!o->bank && o->address == 15 && s->value != 0x6c)
            return fail(s, 15); /* Read-only identity never becomes a write target. */
        if (!o->bank && o->address == 1)
            s->bank_low = s->value & 0x3f;
        if ((s->value & o->mask) != (expected & o->mask))
        {
            if (s->mismatch_address == o->address && s->mask == o->mask)
            {
                s->observed = s->value & o->mask;
                return fail(s, 17);
            }
            if (s->no_op)
            {
                s->proof_invalid = true;
                s->no_op = false;
                s->index = 0;
                s->phase = RESTORE;
                break;
            }
            if (!s->changed)
                return fail(s, 17);
            /* Preserve reserved bits; each changed field gets a separate readback. */
            s->value = (s->value & (uint8_t)~o->mask) | (expected & o->mask);
            s->phase = WRITE;
            break;
        }
        goto next;
    case WRITE:
        /* Verify the just-written fields before moving on. A mismatching read must
         * terminate, rather than writing forever or accepting a partial image. */
        s->phase = READ;
        s->mismatch_address = o->address;
        s->expected = expected & o->mask;
        s->mask = o->mask;
        return 0;
    case RESTORE:
        s->phase = RESTORE_VERIFY;
        break;
    default:
        break;
    }
    return 0;
next:
    s->mismatch_address = s->expected = s->observed = s->mask = 0;
    if (++s->index == sizeof(owned) / sizeof(owned[0]))
    {
        s->index = 0;
        s->phase = RESTORE;
    }
    else
        s->phase = owned[s->index].bank == s->bank ? READ : SELECT_BANK;
    return 0;
}
