/* Optional, bounded diagnostic capture. Never owns or changes an image.
 * Schema 2: view/source snapshots plus actual blit inputs and pixel samples.
 * No image copy, allocation, provider retry or change to rendering behavior.
 */
#include <stdint.h>

#define DRAW 0x44726177u
#define ART 0x7f05u
#define WORDS 144
static volatile uint32_t artwork_sequence;
static volatile uint32_t artwork_trace[WORDS];
/* Scoped to the UI paint stack; never read/dereferenced by the USB writer. */
static unsigned char *painting_view;

static int ram(uintptr_t pointer, unsigned bytes)
{
    return !(pointer & 3) && pointer >= 0x08000000u &&
           pointer <= 0x0c000000u - bytes;
}

static uint32_t word(const void *base, unsigned offset)
{
    return *(const uint32_t *)((const unsigned char *)base + offset);
}

static int preview(const unsigned char *view)
{
    return word(view, 0x40) == DRAW && word(view, 0x44) == ART;
}

static void begin(void)
{
    artwork_sequence++;
    __asm__ volatile("" : : : "memory");
}

static void end(void)
{
    __asm__ volatile("" : : : "memory");
    artwork_sequence++;
}

static void bitmap(volatile uint32_t *out, uintptr_t address)
{
    out[0] = address;
    if (!ram(address, 0xb8)) return;
    out[1] = word((void *)address, 4); /* Native surface pixel pointer. */
    out[2] = word((void *)address, 0x14);
    for (unsigned i = 0; i < 4; i++) out[3+i] = word((void *)address, 0x98+4*i);
}

static void snapshot(volatile uint32_t *out, unsigned char *view)
{
    for (unsigned i = 0; i < 20; i++) out[i] = 0;
    out[0] = (uintptr_t)view;
    out[1] = word(view, 0x48);
    out[2] = view[0xa1];
    out[3] = word(view, 0x38);
    out[4] = word(view, 0x15c);
    for (unsigned i = 0; i < 4; i++) out[5+i] = word(view, 0x80+4*i);
    if (ram(out[4], 68)) {
        bitmap(out+9, word((void *)(uintptr_t)out[4], 0x1c));
        for (unsigned i = 0; i < 4; i++)
            out[16+i] = word((void *)(uintptr_t)out[4], 0x34+4*i);
    }
}

static void source_snapshot(volatile uint32_t *out, void *service, void *result)
{
    for (unsigned i = 0; i < 16; i++) out[i] = 0;
    out[0] = (uintptr_t)service;
    if (ram((uintptr_t)service, 4)) out[1] = word(service, 0);
    bitmap(out+2, (uintptr_t)result);
    if (out[1] == 0x089986a4u && ram((uintptr_t)service, 0x3bc)) {
        out[9] = word(service, 0x3b4);
        out[10] = word(service, 0xcc);
        out[11] = word(service, 0x190);
        for (unsigned i = 0; i < 4; i++) out[12+i] = word(service, 0x224+4*i);
    }
}

void iop_artwork_trace_visibility(unsigned char *view, uint32_t visible)
{
    if (!preview(view)) return;
    begin();
    artwork_trace[visible ? 1 : 2]++;
    /* Preserve the last show when USB later hides the menu. */
    if (visible) snapshot(artwork_trace+44, view);
    end();
}

void iop_artwork_trace_paint(unsigned char *view)
{
    int watched = preview(view);
    unsigned char *previous = painting_view;
    painting_view = watched ? view : 0;
    if (watched) {
        begin();
        artwork_trace[0]++;
        snapshot(artwork_trace+4, view);
        /* A skipped draw must not inherit the previous paint's blit inputs. */
        for (unsigned i = 81; i < 128; i++) artwork_trace[i] = 0;
        end();
    }
    typedef void (*paint_fn)(void *);
    ((paint_fn)0x0810012cu)(view);
    if (watched) {
        begin();
        snapshot(artwork_trace+24, view);
        uintptr_t service = word(view, 0x38);
        uintptr_t context = word(view, 0x15c);
        uintptr_t image = ram(context, 68) ? word((void *)context, 0x1c) : 0;
        source_snapshot(artwork_trace+128, (void *)service, (void *)image);
        end();
    }
    painting_view = previous;
}

void *iop_artwork_trace_query(void *service, uint32_t type, uint32_t id)
{
    typedef void *(*query_fn)(void *, uint32_t, uint32_t);
    void *result = ((query_fn)0x08268b64u)(service, type, id);
    if (type == DRAW && id == ART) {
        begin();
        artwork_trace[3]++;
        source_snapshot(artwork_trace+64, service, result);
        end();
    }
    return result;
}

static void pixel_samples(uintptr_t image)
{
    volatile uint32_t *out = artwork_trace+120;
    if (!ram(image, 0xb8)) return;
    out[7] = word((void *)image, 0x14);
    /* Only the qualified tightly-packed 128-square RGB565 preview format. */
    if ((out[7] & 0xffff) != 0x565 || word((void *)image, 8) != 256 ||
        word((void *)image, 0x98) || word((void *)image, 0x9c) ||
        word((void *)image, 0xa0) != 128 || word((void *)image, 0xa4) != 128) return;
    uintptr_t pixels = word((void *)image, 4);
    if (!ram(pixels, 32768)) return;
    uint32_t any = 0, all = 0xffffffffu, hash = 2166136261u;
    for (unsigned i = 0; i < 64; i++) {
        uint32_t sample = word((void *)pixels, i*512);
        any |= sample;
        all &= sample;
        hash = (hash ^ sample) * 16777619u;
    }
    out[0] = 64;
    out[1] = any;
    out[2] = all;
    out[3] = hash;
    out[4] = word((void *)pixels, 0);
    out[5] = word((void *)pixels, 16384);
    out[6] = word((void *)pixels, 32764);
}

void iop_artwork_trace_blit(void *dst, void *src, const uint32_t *source_rect,
                          const uint32_t *target_rect, uint32_t alpha, uint32_t flags)
{
    /* dst is the patched native caller's live stack context, not heap DRAM. */
    if (painting_view && word(painting_view, 0x15c) == (uintptr_t)src &&
        ram((uintptr_t)src, 68)) {
        begin();
        volatile uint32_t *out = artwork_trace+80;
        out[0]++;
        out[1] = (uintptr_t)painting_view;
        out[2] = (uintptr_t)dst;
        out[3] = (uintptr_t)src;
        out[4] = alpha;
        out[5] = flags;
        uintptr_t target = word(dst, 0x1c), image = word(src, 0x1c);
        out[6] = target;
        if (ram(target, 0xb8)) {
            out[7] = word((void *)target, 4);
            out[8] = word((void *)target, 0x14);
            for (unsigned i = 0; i < 4; i++) artwork_trace[112+i] = word((void *)target, 0x18+4*i);
            artwork_trace[117] = word((void *)target, 8);
            artwork_trace[119] = word((void *)target, 0xc);
        }
        out[9] = word(dst, 0x10);
        out[10] = word(dst, 0x2c);
        out[11] = word(dst, 0x30);
        for (unsigned i = 0; i < 4; i++) out[12+i] = word(dst, 0x34+4*i);
        out[16] = word(src, 0x2c);
        out[17] = word(src, 0x30);
        out[18] = image;
        if (ram(image, 0xb8)) {
            out[19] = word((void *)image, 4);
            for (unsigned i = 0; i < 4; i++) artwork_trace[108+i] = word((void *)image, 0x18+4*i);
            artwork_trace[116] = word((void *)image, 8);
            artwork_trace[118] = word((void *)image, 0xc);
        }
        /* These point to the native caller's live stack, including on IRAM. */
        for (unsigned i = 0; i < 4; i++) {
            artwork_trace[100+i] = source_rect[i];
            artwork_trace[104+i] = target_rect[i];
        }
        pixel_samples(image);
        end();
    }
    typedef void (*blit_fn)(void *, void *, const uint32_t *, const uint32_t *, uint32_t, uint32_t);
    ((blit_fn)0x08259568u)(dst, src, source_rect, target_rect, alpha, flags);
}

void iop_artwork_trace_xml(void *writer)
{
    uint32_t copy[WORDS] = {0};
    unsigned stable = 0;
    for (unsigned attempt = 0; attempt < 3; attempt++) {
        uint32_t before = artwork_sequence;
        if (before & 1) continue;
        for (unsigned i = 0; i < WORDS; i++) copy[i] = artwork_trace[i];
        __asm__ volatile("" : : : "memory");
        if (artwork_sequence == before) { stable = 1; break; }
    }
    if (!stable) for (unsigned i = 0; i < WORDS; i++) copy[i] = 0;
    typedef void (*integer_fn)(void *, const char *, uint32_t, unsigned);
    typedef void (*string_fn)(void *, const char *, const char *, unsigned);
    typedef void (*dict_fn)(void *, const char *, unsigned);
    typedef void (*close_fn)(void *, unsigned);
    ((dict_fn)0x08118a14u)(writer, "iOpenPodArtworkTrace", 1);
    ((integer_fn)0x0811891cu)(writer, "Schema", 2, 2);
    ((integer_fn)0x0811891cu)(writer, "Stable", stable, 2);
    /* Apple's per-string formatter has a small temporary buffer. Keep each
     * field at most 160 characters, including when every counter is nonzero. */
    static const char digits[] = "0123456789abcdef";
    /* SysInfo has a 15376-byte transport limit. Schema 2 omits the redundant
     * pre-paint/show snapshots on the wire to leave room for source/blit data. */
    static const char *const keys[] = {"Counts", "AfterPaint", "Query", "Blit", "Rects", "Pixels", "Model"};
    static const unsigned offsets[] = {0, 24, 64, 80, 100, 120, 128};
    static const unsigned counts[] = {4, 20, 16, 20, 20, 8, 16};
    for (unsigned block = 0; block < 7; block++) {
        unsigned count = counts[block], offset = offsets[block];
        char encoded[161];
        for (unsigned i = 0; i < count; i++)
            for (unsigned j = 0; j < 8; j++)
                encoded[8*i+j] = digits[(copy[offset+i] >> (28-4*j)) & 15];
        encoded[count*8] = 0;
        ((string_fn)0x08118b50u)(writer, keys[block], encoded, 2);
    }
    ((close_fn)0x08118cf0u)(writer, 1);
}
