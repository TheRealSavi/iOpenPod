/* SPDX-License-Identifier: GPL-3.0-only */

#include "sha256.h"
#include <string.h>

static uint32_t rotr(uint32_t x, unsigned n)
{
    return (x >> n) | (x << (32 - n));
}

static void block(struct sha256 *s, const uint8_t *data)
{
    static const uint32_t k[64] = {
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
        0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
        0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
        0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
        0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
        0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
        0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
        0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
        0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
        0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};
    uint32_t *h = s->h, w[64];
    for (unsigned j = 0; j < 16; ++j) {
        const uint8_t *p = data + 4 * j;
        w[j] = (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
    }
    for (unsigned j = 16; j < 64; j++) {
        uint32_t x = w[j - 15], y = w[j - 2];
        w[j] = w[j - 16] + (rotr(x, 7) ^ rotr(x, 18) ^ (x >> 3)) + w[j - 7] +
               (rotr(y, 17) ^ rotr(y, 19) ^ (y >> 10));
    }
    uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6],
             hh = h[7];
#define ROUND(a, b, c, d, e, f, g, h, i)                                               \
    do {                                                                               \
        h += (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + k[i] +  \
             w[i];                                                                     \
        d += h;                                                                        \
        h += (rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c)); \
    } while (0)
    /* Rotate register roles across eight rounds instead of copying them. */
    for (unsigned j = 0; j < 64; j += 8) {
        ROUND(a, b, c, d, e, f, g, hh, j);
        ROUND(hh, a, b, c, d, e, f, g, j + 1);
        ROUND(g, hh, a, b, c, d, e, f, j + 2);
        ROUND(f, g, hh, a, b, c, d, e, j + 3);
        ROUND(e, f, g, hh, a, b, c, d, j + 4);
        ROUND(d, e, f, g, hh, a, b, c, j + 5);
        ROUND(c, d, e, f, g, hh, a, b, j + 6);
        ROUND(b, c, d, e, f, g, hh, a, j + 7);
    }
#undef ROUND
    h[0] += a;
    h[1] += b;
    h[2] += c;
    h[3] += d;
    h[4] += e;
    h[5] += f;
    h[6] += g;
    h[7] += hh;
}

void sha256_init(struct sha256 *s)
{
    static const uint32_t initial[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                                        0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
    memcpy(s->h, initial, sizeof(initial));
    s->bytes = 0;
}

void sha256_update(struct sha256 *s, const void *input, size_t bytes)
{
    const uint8_t *data = input;
    unsigned used = s->bytes & 63;
    s->bytes += bytes;
    if (used) {
        size_t n = bytes < 64 - used ? bytes : 64 - used;
        memcpy(s->tail + used, data, n);
        used += n;
        data += n;
        bytes -= n;
        if (used < 64)
            return;
        block(s, s->tail);
    }
    while (bytes >= 64) {
        block(s, data);
        data += 64;
        bytes -= 64;
    }
    if (bytes)
        memcpy(s->tail, data, bytes);
}

void sha256_final(struct sha256 *s, uint8_t digest[32])
{
    unsigned used = s->bytes & 63;
    uint64_t bits = s->bytes * 8;
    s->tail[used++] = 0x80;
    if (used > 56) {
        memset(s->tail + used, 0, 64 - used);
        block(s, s->tail);
        used = 0;
    }
    memset(s->tail + used, 0, 56 - used);
    for (unsigned i = 0; i < 8; ++i)
        s->tail[63 - i] = bits >> (8 * i);
    block(s, s->tail);
    for (unsigned i = 0; i < 32; ++i)
        digest[i] = s->h[i / 4] >> (24 - 8 * (i % 4));
}
