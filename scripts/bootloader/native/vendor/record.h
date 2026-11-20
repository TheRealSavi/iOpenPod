/* SPDX-License-Identifier: GPL-3.0-only */

#ifndef REPRISE_RECORD_H
#define REPRISE_RECORD_H

#include <stdint.h>

#define RECORD_ADDR 0x2201f000u
#define RETURN_ADDR 0x22010000u
#define RECORD_MAGIC 0x44505231u

struct dfu_record {
    uint32_t magic, version, phase;
    int32_t storage_rc;
    uint32_t sector_size, sectors_low, sectors_high, battery_mv;
    uint8_t nonce[16];
    uint32_t returns, reserved[3];
};

_Static_assert(sizeof(struct dfu_record) == 64, "record layout");

#define RECORD ((volatile struct dfu_record *)RECORD_ADDR)

#endif
