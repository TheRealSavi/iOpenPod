/* Classic 2.0.5 full-size Photos browser. Rect coordinates are top, left,
 * bottom, right, with exclusive ends. F1024 is RGB565; F1067 is planar I420. */
#include <stdint.h>

enum { WIDTH = 320, HEIGHT = 240, STRIP = 8, FIT = 96, MAX_ZOOM = 5 * FIT };
enum { TV_WIDTH = 720, TV_HEIGHT = 480, TV_BYTES = TV_WIDTH * TV_HEIGHT * 3 / 2 };
enum { MENU = 0x6e, CENTER = 0x6f, PREV = 0x59, NEXT = 0x5a, PLAY = 0x10 };
/* Phases constructed by the native kDwn, kAut, kP&H and kUp handlers. */
enum { KEY_DOWN = 6, KEY_REPEAT = 7, KEY_HOLD = 8, KEY_UP = 13 };
typedef struct { int top, left, bottom, right; } Rect;
typedef struct {
    unsigned char *model;
    int album, index;
    int scale, x, y;
    unsigned touch, angle, tracking;
    Rect content;
} PhotoZoom;
static PhotoZoom zoom;
/* One native one-shot timer, addressed to the same process-lifetime photo
 * model as Apple's photo retry timer. Only an active pan schedules it. */
static uint32_t pan_timer[11];
static unsigned held, previous_us, remainder_us;
enum { FRAME_MS = 25, US_PER_PIXEL = 5000 };
static uint16_t strip[STRIP][WIDTH] __attribute__((aligned(4)));
static uint16_t columns[WIDTH];

static int word(const void *object, unsigned offset)
{
    return *(const int *)((const unsigned char *)object + offset);
}

static int divide(int a, int b)
{
    return ((int (*)(int, int))0x08026690u)(a, b);
}

static int clamp(int value, int low, int high)
{
    return value < low ? low : value > high ? high : value;
}

static int current(const unsigned char *model)
{
    return model && model == zoom.model && model[0x18] == 2 &&
           zoom.album == word(model, 0x8c4) && zoom.index == word(model, 0x8b8);
}

static void repaint(void)
{
    unsigned char *root = ((unsigned char *(*)(void))0x08113600u)();
    if (root)
        ((void (*)(void *, const void *))0x082655a0u)(root, root + 0x80);
}

static int photo_dimensions(int format, int *width, int *height)
{
    /* Follow Rect/0x8482's album lookup. Its stock caller ignores the
     * dimension getter's failure; only cache geometry from an actual record. */
    void *library = zoom.model + 0x1c;
    void **reference = 0;
    ((void (*)(void ***, void *))0x082217f4u)(&reference, library);
    int found = 0;
    if (reference && *reference) {
        void *album = *reference;
        int selected = ((int (*)(void *))0x0822166cu)(library);
        int item = ((int (*)(void *, int))0x08221804u)(library, selected);
        uintptr_t *methods = *(uintptr_t **)album;
        typedef int (*dimensions_fn)(void *, int, int, int *, int *);
        found = ((dimensions_fn)methods[0x24 / 4])(album, item, format, width, height);
    }
    ((void (*)(void ***))0x082594b8u)(&reference);
    return found;
}

static int content_bounds(void)
{
    if (zoom.content.right) return 1;
    int width = 0, height = 0;
    int found = photo_dimensions(1024, &width, &height);
    if (!found || width < 1 || height < 1 || width > WIDTH || height > HEIGHT) return 0;
    int x = (WIDTH - width) / 2, y = (HEIGHT - height) / 2;
    zoom.content = (Rect){y, x, y + height, x + width};
    return 1;
}

static int pan_limit(int offset, int length, int viewport)
{
    int excess = length * zoom.scale / FIT - viewport;
    if (excess <= 0) return 0;
    return clamp(offset, -(excess / 2), excess - excess / 2);
}

static void move(int dx, int dy, int scale)
{
    int x = zoom.x, y = zoom.y;
    int old = zoom.scale;
    zoom.scale = clamp(scale, FIT, MAX_ZOOM);
    if (old != zoom.scale) {
        x = divide(x * zoom.scale, old);
        y = divide(y * zoom.scale, old);
    }
    Rect r = zoom.content;
    zoom.x = pan_limit(x + dx, r.right - r.left, WIDTH);
    zoom.y = pan_limit(y + dy, r.bottom - r.top, HEIGHT);
    if (old != zoom.scale || zoom.x != x || zoom.y != y) repaint();
}

static void stop_pan(void)
{
    if (held) ((void (*)(void *))0x081219d0u)(pan_timer);
    held = remainder_us = 0;
}

void iop_photo_open_large(void *model)
{
    stop_pan();
    zoom.model = 0;
    ((void (*)(void *))0x081c2624u)(model);
}

static void advance_pan(unsigned now)
{
    /* Unsigned subtraction also works across the 32-bit microsecond wrap.
     * Eight seconds covers the entire largest possible scaled dimension. */
    unsigned elapsed = now - previous_us;
    previous_us = now;
    unsigned total = (elapsed > 8000000u ? 8000000u : elapsed) + remainder_us;
    int pixels = divide((int)total, US_PER_PIXEL);
    remainder_us = total - pixels * US_PER_PIXEL;
    int dx = (int)((held >> 1) & 1) - (int)((held >> 2) & 1);
    int dy = (int)((held >> 3) & 1) - (int)(held & 1);
    if (pixels && content_bounds()) move(dx * pixels, dy * pixels, zoom.scale);
}

static unsigned now_us(void)
{
    return ((unsigned (*)(void))0x083619b4u)();
}

static void schedule_frame(void)
{
    ((void (*)(void *))0x08121268u)(pan_timer);
}

int iop_photo_timer(void *model, const unsigned *event)
{
    if (event[1] != 15 || event[2] != (uintptr_t)pan_timer)
        return ((int (*)(void *, const void *))0x081c2fa8u)(model, event);
    if (held && current(model)) {
        /* Stock's latest five on-device switch bits. A missed button-up
         * (for example after a long press) must never leave a pan running. */
        unsigned physical = *(const volatile unsigned *)0x089d2bacu;
        if (physical & held) {
            held &= physical;
            advance_pan(now_us());
            schedule_frame();
            return 1;
        }
    }
    stop_pan();
    return 1;
}

static void direction(unsigned bit, unsigned phase, void *model)
{
    unsigned now = now_us();
    if (held) advance_pan(now);
    if (phase == KEY_UP) {
        if (!(held & ~bit)) stop_pan();
        else held &= ~bit;
    } else if ((phase == KEY_DOWN || phase == KEY_HOLD) && !(held & bit) && zoom.scale > FIT) {
        if (!held) {
            ((void (*)(void *, void *, int, int))0x0810635cu)(model, pan_timer, 0, 0);
            ((void (*)(void *, int))0x0812195cu)(pan_timer, FRAME_MS);
            previous_us = now;
            remainder_us = 0;
            schedule_frame();
        }
        held |= bit;
    }
}

static int wheel_travel(const unsigned *event)
{
    /* Materialize position, contact serial and unaccelerated motion together.
     * The native menu filter discards a few slow steps after touchdown.
     * Invert its 256-angle report to recover the actual 96-position travel. */
    int delta = ((int (*)(const void *))0x08289490u)(event);
    unsigned position = event[4];
    if (position & 0x40000000u) {
        unsigned angle = ((position & 255) * 3 + 7) / 8;
        if (zoom.tracking && zoom.touch == event[6]) {
            int travel = (int)zoom.angle - (int)angle;
            int difference = delta - travel;
            /* The relative counter disambiguates coalesced whole turns. */
            int turns = divide(difference + (difference < 0 ? -48 : 48), 96);
            delta = travel + turns * 96;
        }
        zoom.angle = angle;
        zoom.touch = event[6];
        zoom.tracking = 1;
    } else {
        zoom.tracking = 0;
    }
    return delta;
}

int iop_photo_event(unsigned char *controller, const unsigned *event)
{
    unsigned char *model = *(unsigned char **)(controller + 0xb0);
    if (!current(model)) {
        stop_pan();
        zoom.model = 0;
    }
    if (!model || model[0x18] != 2) goto stock;

    if (event[0] == 0x089af1d0u && zoom.model) {
        /* Apple's signed wheel accumulator unwraps 0..95 around the seam.
         * Scale uses those same units: one revolution adds exactly 1x. */
        int delta = wheel_travel(event);
        if (delta) {
            move(0, 0, zoom.scale + delta);
            if (zoom.scale == FIT) stop_pan();
        }
        return 1;
    }
    if (event[0] != 0x089adeb8u) goto stock;
    unsigned key = (event[4] >> 16) & 255;
    if (key != CENTER && key != MENU && key != PREV && key != NEXT && key != PLAY)
        goto stock;
    if (event[1] < KEY_DOWN || event[1] > KEY_UP) goto stock;
    if (!zoom.model) {
        if (key != CENTER) goto stock;
        if (event[1] == KEY_UP) {
            zoom.model = model;
            zoom.album = word(model, 0x8c4);
            zoom.index = word(model, 0x8b8);
            zoom.content.right = 0;
            zoom.x = zoom.y = 0;
            zoom.tracking = 0;
            zoom.scale = FIT;
            content_bounds();
            repaint();
        }
    } else if (key == MENU) {
        /* Consume repeats too: stock calls both repeat and release ".up". */
        if (event[1] == KEY_UP) {
            stop_pan();
            if (zoom.scale == FIT && !zoom.x && !zoom.y) {
                zoom.model = 0;
                repaint();
            } else {
                move(0, 0, FIT);
            }
        }
    } else {
        unsigned bit = key == NEXT ? 2 : key == PREV ? 4 : key == PLAY ? 8 : 1;
        direction(bit, event[1], model);
    }
    return 1;
stock:
    return ((int (*)(void *, const void *))0x0812a070u)(controller, event);
}

/* The base and derived photo controllers both run this lifecycle path. */
int iop_photo_leave(unsigned char *controller, unsigned reason)
{
    if (zoom.model == *(unsigned char **)(controller + 0xb0)) {
        stop_pan();
        zoom.model = 0;
    }
    return ((int (*)(void *, unsigned))0x08103118u)(controller, reason);
}

typedef void (*blit_fn)(void *, const void *, const Rect *, const Rect *, unsigned, unsigned);
#define NATIVE_BLIT ((blit_fn)0x08259568u)
#ifdef IOP_ARTWORK_DIAGNOSTICS
extern void iop_artwork_trace_blit(void *, void *, const uint32_t *,
                                  const uint32_t *, uint32_t, uint32_t);
#endif

typedef struct {
    const unsigned char *pixels;
    void *reference;
    int width, height;
} PhotoSource;

static void release_source(PhotoSource *source)
{
    ((void (*)(void *))0x08393de0u)(&source->reference);
}

static int high_resolution(PhotoSource *source)
{
    /* Selector 5 is registered by Photos and loaded by its existing cache.
     * Keep the native cache reference until the last strip has been copied. */
    ((void (*)(void *, void *, int, int))0x0822178cu)(
        &source->reference, zoom.model + 0x1c, zoom.index, 5);
    void *image = ((void *(*)(void *))0x083ccd8cu)(&source->reference);
    if (!image || !((int (*)(void *))0x08277508u)(image)) return 0;
    uintptr_t *methods = *(uintptr_t **)image;
    void *surface = ((void *(*)(void *, int, int, int))methods[4])(image, 0, 0, 0);
    if (!surface) return 0;
    uintptr_t *surface_methods = *(uintptr_t **)surface;
    unsigned bytes = 0;
    const unsigned char *pixels = ((const unsigned char *(*)(void *, unsigned *))
        surface_methods[0x44 / 4])(surface, &bytes);
    const unsigned char *format = ((const unsigned char *(*)(void *))methods[5])(image);
    if (!pixels || bytes < TV_BYTES || !format || word(format, 0) != TV_HEIGHT ||
        word(format, 4) != TV_WIDTH || word(format, 8) != TV_WIDTH * 3 / 2 ||
        *(const uint16_t *)(format + 12) || word(format, 16) || word(format, 20) ||
        word(format, 24) != 12 || *(const uint16_t *)(format + 28) != 0xc420)
        return 0;
    if (!photo_dimensions(1067, &source->width, &source->height) ||
        source->width < 1 || source->width > TV_WIDTH ||
        source->height < 1 || source->height > TV_HEIGHT) return 0;
    source->pixels = pixels;
    return 1;
}

static uint16_t tv_pixel(const unsigned char *pixels, int x, int y)
{
    /* BT.601 limited-range Y, Cb, Cr planes. Convert only sampled pixels. */
    int luma = 298 * ((int)pixels[y * TV_WIDTH + x] - 16);
    int chroma = (y / 2) * (TV_WIDTH / 2) + x / 2;
    int u = (int)pixels[TV_WIDTH * TV_HEIGHT + chroma] - 128;
    int v = (int)pixels[TV_WIDTH * TV_HEIGHT * 5 / 4 + chroma] - 128;
    int r = clamp((luma + 409 * v + 128) >> 8, 0, 255);
    int g = clamp((luma - 100 * u - 208 * v + 128) >> 8, 0, 255);
    int b = clamp((luma + 516 * u + 128) >> 8, 0, 255);
    return (uint16_t)(((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3));
}

/* A 20px magnifier tile stays visible over light and dark photos at every zoom.
 * Reuse the finished render strip, then submit through the same native clip. */
static void draw_indicator(void *dst, const Rect *from, const Rect *to,
                           unsigned alpha, unsigned flags)
{
    static const uint16_t glyph[16] = {
        0x0000, 0x03f0, 0x0408, 0x0804, 0x08c4, 0x08c4, 0x0bf4, 0x08c4,
        0x08c4, 0x0408, 0x03f0, 0x0e00, 0x1c00, 0x3800, 0x3000, 0x0000
    };
    uint16_t *pixels = &strip[0][0];
    for (int y = 0; y < 20; ++y) {
        for (int x = 0; x < 20; ++x) {
            int ink = x >= 2 && x < 18 && y >= 2 && y < 18 &&
                      (glyph[y - 2] & (1u << (x - 2)));
            pixels[y * 20 + x] = ink ? 0xffff : 0x2104;
        }
    }
    int left = to->left - (WIDTH - (from->right - from->left)) / 2 + WIDTH - 24;
    int top = to->top - (HEIGHT - (from->bottom - from->top)) / 2 + HEIGHT - 24;
    Rect buffer = {0, 0, 20, 20}, target = {top, left, top + 20, left + 20};
    uint32_t surface[0xb8/4], context[0x44/4];
    ((void (*)(void *))0x08103e8cu)(surface);
    typedef void (*bind_fn)(void *, const Rect *, void *, int, int, int, int, int);
    ((bind_fn)0x08103aa0u)(surface, &buffer, pixels, 40, 16, 0x565, 0, 0);
    ((void (*)(void *, void *))0x0825aefcu)(context, surface);
    NATIVE_BLIT(dst, context, &buffer, &target, alpha, flags);
    ((void (*)(void *))0x0825b038u)(context);
    ((void (*)(void *))0x08103ee0u)(surface);
}

void iop_photo_blit(void *dst, const unsigned char *src, const Rect *from,
                    const Rect *to, unsigned alpha, unsigned flags)
{
    const unsigned char *bitmap = *(const unsigned char *const *)(src + 0x1c);
    int active = bitmap == (const unsigned char *)0x08aed688u && current(zoom.model);
    if (!active || zoom.scale == FIT || !content_bounds()) goto stock;

    /* Use only a qualified F1024 surface. Respect an already cropped native
     * bitmap as well as a full LCD raster with centered PhotosDB padding. */
    const uint16_t *pixels = *(const uint16_t *const *)(bitmap + 4);
    const Rect *bounds = (const Rect *)(bitmap + 0x18);
    int w = from->right, h = from->bottom;
    if (!pixels || word(bitmap, 8) != WIDTH * 2 || word(bitmap, 12) != 16 ||
        *(const uint16_t *)(bitmap + 0x14) != 0x565 ||
        from->top || from->left || word(src, 0x2c) || word(src, 0x30) ||
        bounds->top < 0 || bounds->left < 0 || bounds->right > WIDTH ||
        bounds->bottom > HEIGHT || bounds->right - bounds->left != w ||
        bounds->bottom - bounds->top != h || w <= 0 || h <= 0 ||
        to->right - to->left != w || to->bottom - to->top != h) goto stock;

    Rect image = zoom.content;
    int content_w = image.right - image.left, content_h = image.bottom - image.top;
    /* Map the native centered content rectangle back into the source buffer. */
    int sx = bounds->left + image.left - (WIDTH - w) / 2;
    int sy = bounds->top + image.top - (HEIGHT - h) / 2;
    if (sx < bounds->left || sy < bounds->top || sx + content_w > bounds->right ||
        sy + content_h > bounds->bottom) goto stock;

    int scaled_w = content_w * zoom.scale / FIT;
    int scaled_h = content_h * zoom.scale / FIT;
    int left = (WIDTH - scaled_w) / 2 - zoom.x;
    int top = (HEIGHT - scaled_h) / 2 - zoom.y;
    int x0 = clamp(left, 0, WIDTH), x1 = clamp(left + scaled_w, 0, WIDTH);
    int y0 = clamp(top, 0, HEIGHT), y1 = clamp(top + scaled_h, 0, HEIGHT);
    int screen_x = to->left - (WIDTH - w) / 2;
    int screen_y = to->top - (HEIGHT - h) / 2;
    PhotoSource source = {0};
    int high = high_resolution(&source);
    int sample_w = content_w, sample_h = content_h;
    if (high) {
        sample_w = source.width;
        sample_h = source.height;
        sx = (TV_WIDTH - sample_w) / 2;
        sy = (TV_HEIGHT - sample_h) / 2;
    }
    for (int x = x0; x < x1; ++x)
        columns[x] = sx + divide((x - left) * sample_w, scaled_w);

    /* Borrow a strip for this synchronous native blit. The original photo's
     * pixels, the cached BitmapView context and the display clip stay owned by Apple. */
    uint32_t surface[0xb8/4], context[0x44/4];
    Rect buffer = {0, 0, STRIP, WIDTH};
    ((void (*)(void *))0x08103e8cu)(surface);
    typedef void (*bind_fn)(void *, const Rect *, void *, int, int, int, int, int);
    ((bind_fn)0x08103aa0u)(surface, &buffer, strip, WIDTH * 2, 16, 0x565, 0, 0);
    ((void (*)(void *, void *))0x0825aefcu)(context, surface);
    for (int y = 0; y < HEIGHT; y += STRIP) {
        for (int row = 0; row < STRIP; ++row) {
            int x = 0;
            if (y + row >= y0 && y + row < y1) {
                int source_y = sy + divide((y + row - top) * sample_h, scaled_h);
                for (; x < x0; ++x) strip[row][x] = 0;
                if (high) {
                    for (; x < x1; ++x)
                        strip[row][x] = tv_pixel(source.pixels, columns[x], source_y);
                } else {
                    const uint16_t *line = pixels + source_y * WIDTH;
                    for (; x < x1; ++x) strip[row][x] = line[columns[x]];
                }
            }
            for (; x < WIDTH; ++x) strip[row][x] = 0;
        }
        Rect target = {screen_y + y, screen_x, screen_y + y + STRIP, screen_x + WIDTH};
        NATIVE_BLIT(dst, context, &buffer, &target, alpha, flags);
    }
    ((void (*)(void *))0x0825b038u)(context);
    ((void (*)(void *))0x08103ee0u)(surface);
    release_source(&source);
    goto indicator;
stock:
#ifdef IOP_ARTWORK_DIAGNOSTICS
    iop_artwork_trace_blit(dst, (void *)src, (const uint32_t *)from,
                          (const uint32_t *)to, alpha, flags);
#else
    NATIVE_BLIT(dst, src, from, to, alpha, flags);
#endif
indicator:
    if (active) draw_indicator(dst, from, to, alpha, flags);
}

