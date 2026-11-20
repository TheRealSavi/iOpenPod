/* SPDX-License-Identifier: GPL-3.0-only */

#ifndef REPRISE_SHA256_H
#define REPRISE_SHA256_H

#include <stdint.h>
#include <stddef.h>

struct sha256 {
    uint32_t h[8];
    uint64_t bytes;
    uint8_t tail[64];
};

void sha256_init(struct sha256 *s);
void sha256_update(struct sha256 *s, const void *data, size_t bytes);
void sha256_final(struct sha256 *s, uint8_t digest[32]);

#endif
