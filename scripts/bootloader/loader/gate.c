/* Classic ROM protocol extension: unkeyed, explicitly framed custom OSOS.
 * The original ROM wrapper still owns hardware/context setup and cleanup.
 */
#include <stdint.h>
#ifndef UPDATER_FAMILY
#error "Select an exact Classic updater family"
#endif
#ifndef MAX_BODY
#error "Select the qualified OSOS slot bound"
#endif

typedef int (*body_fn)(const uint8_t *, const uint8_t *, unsigned);
extern int native_header(void *, const uint8_t *, unsigned);
extern uint32_t unsigned_crc32(const uint8_t *, uint32_t);

static uint32_t word(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

/* This gate runs before Bds allocates and reads the image body. */
static int custom_header(const uint8_t *h)
{
    uint32_t n = word(h + 12);
#ifdef SHARED_CLASSIC
    uint32_t target = word(h + 24), schema = word(h + 28);
    uint32_t marker = 0x00324445u;
    if (schema == 1) {
        uint32_t limit;
        switch (target) {
        case 24: limit = 0x978800; break;
        case 33: limit = 0xa07800; break;
        case 35: limit = 0xa1c800; break;
        case 38: limit = 0xa25800; break;
        default: return 0;
        }
        if (n > limit) return 0;
        marker = 0x00314445u;
    } else if (schema != 2 || target != 0x43534c43u) {
        return 0;
    }
#endif
    if (word(h) != 0x32303738u || word(h + 4) != 0x7f302e31u ||
        word(h + 8) != 0 || n < 16 || n > MAX_BODY || (n & 15u) ||
        word(h + 20) != 0x800 ||
#ifndef SHARED_CLASSIC
        word(h + 24) != UPDATER_FAMILY || word(h + 28) != 1 ||
#endif
        word(h + 32) != 0x4f504f49u || word(h + 36) != 0x4e552e44u ||
        word(h + 40) != 0x4e474953u ||
#ifdef SHARED_CLASSIC
        word(h + 44) != marker ||
#else
        word(h + 44) != 0x00314445u ||
#endif
        word(h + 48) || word(h + 52) || word(h + 56) || word(h + 60))
        return 0;
    return unsigned_crc32(h, 64) == word(h + 64);
}

int unsigned_header_gate(void *self, const uint8_t *h, unsigned key,
                         uint32_t file_bytes)
{
    if (h[7] == 0x7f) {
        /* Bds supplies GetInfo's media block size as argument 3 for custom
         * images. FirmwareFS Open adds one media block, then rounds to the
         * NEXT 64-byte boundary, even for an already aligned length.
         * Bds must allocate/read only the header-declared body, not this
         * inflated virtual file length. */
        return custom_header(h) && (key == 512 || key == 4096) &&
                       file_bytes == ((0x800u + word(h + 12) + key + 64u) & ~63u)
                   ? 0 : (int)0x80000003u;
    }
    if (h[7] == 1 || h[7] == 2)
        key = 2;
    return native_header(self, h, key);
}

#ifdef SHARED_CLASSIC
/* Invoked by Bds after copying SysInfo and successfully validating the OS.
 * Keep native hardware configuration and legacy handoffs unchanged.
 */
void shared_context(const uint8_t *h)
{
    if (h[7] == 0x7f && word(h + 28) == 2 && word(h + 24) == 0x43534c43u) {
        volatile uint32_t *copied = (volatile uint32_t *)0x22028cc0u;
        copied[0x84 / 4] = 0x00130300u;
        copied[0x11c / 4] = 0x01808003u;
    }
}
#endif

/* Return convention here is BootROM boolean success, not EFI status. */
int unsigned_body_gate(const uint8_t *h, const uint8_t *body,
                       unsigned unused, body_fn original)
{
    (void)unused;
    if (h[7] != 0x7f)
        return original(h, body, (h[7] == 1 || h[7] == 2) ? 1 : 2);
    if (!custom_header(h) || unsigned_crc32(body, word(h + 12)) != word(h + 16))
        return 0;
    /* Match the successful native BootROM validator's context publication. */
    volatile uint8_t *state = *(volatile uint8_t * volatile *)0x2203fff8u;
    *(volatile uint32_t *)(state + 0x30) = 0;
    state[0x34] = h[4];
    state[0x35] = h[5];
    state[0x36] = h[6];
    return 1;
}
