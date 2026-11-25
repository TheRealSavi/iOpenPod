/* SPDX-License-Identifier: GPL-3.0-only
 * Native ABI/hooks: osos-lab d2c8e357. Semantic palette and embedded reversible
 * artwork: iOpenPod. All addresses qualified against the prepared 2.0.5 hash.
 */
#include <stdint.h>
#include "appearance_resources.h"
#include "preference.h"

static uint32_t active;
static uint32_t selected;
static uint32_t save_error;
static uint32_t selection_cache_mode;
static const struct setting_file preference = {
    0x31504f49u, 2, {0, "iPod_Control\\Device\\iOPAppearance"}
};

void iop_appearance_apply(uint32_t mode)
{
    if (mode > 1 || mode == active)
        return;
    /* Called only on the native UI/settings thread. Decode the linked deltas
     * directly into the original resource storage, with no temporary buffer.
     * Rendering does no decoding or file I/O; cached pointers remain valid. */
    for (uint32_t i = 0; i < sizeof(appearance_patches) / sizeof(appearance_patches[0]); i++) {
        const struct appearance_patch *patch = &appearance_patches[i];
        unsigned char *out = patch->address;
        unsigned char *end = out + patch->size;
        const unsigned char *encoded = patch->xor_bytes;
        while (out < end) {
            uint32_t control = *encoded++;
            if (control < 128) {
                for (uint32_t j = 0; j <= control; j++) *out++ ^= *encoded++;
            } else if (control < 192) {
                unsigned char value = *encoded++;
                for (uint32_t j = 0; j < (control & 63) + 3; j++) *out++ ^= value;
            } else {
                unsigned char first = *encoded++, second = *encoded++;
                for (uint32_t j = 0; j < (control & 63) + 2; j++) {
                    *out++ ^= first;
                    *out++ ^= second;
                }
            }
        }
    }
    active = mode;
}

static uint32_t resolved_mode(void)
{
    if (selected != 2) return selected;
    /* Native adjusted Firmware Calendar: year/month/day, metadata, then
     * binary hour/minute/second and validity flags. This is the displayed
     * local calendar, not the raw hardware RTC or a host UTC conversion. */
    unsigned char calendar[12] = {0};
    typedef void (*calendar_fn)(unsigned char *);
    ((calendar_fn)0x08059408u)(calendar);
    if (!(calendar[11] & 1) || calendar[8] >= 24 ||
        calendar[9] >= 60 || calendar[10] >= 60)
        return active;
    return calendar[8] < APPEARANCE_LIGHT_START_HOUR || calendar[8] >= APPEARANCE_LIGHT_END_HOUR;
}

void iop_appearance_load(void)
{
    selected = 0;
    iop_read_setting(&preference, &selected);
    iop_appearance_apply(resolved_mode());
    save_error = 0;
}

static void notify(void *model, uint32_t type, uint32_t property)
{
    if (!model) return;
    typedef void (*fn)(void *, uint32_t, uint32_t);
    uintptr_t *vtable = *(uintptr_t **)model;
    ((fn)vtable[0x58 / 4])(model, type, property);
}

static void *model_for_service(uint32_t id)
{
    typedef void *(*lookup_fn)(uint32_t);
    typedef void *(*interface_fn)(void *, uint32_t);
    void *service = ((lookup_fn)0x081c7d44u)(id);
    if (!service) return 0;
    uintptr_t *vtable = *(uintptr_t **)service;
    return ((interface_fn)vtable[0x14 / 4])(service, 5);
}

static void repaint(void)
{
    typedef unsigned char *(*root_fn)(void);
    typedef void (*invalidate_fn)(void *, const void *);
    unsigned char *root = ((root_fn)0x08113600u)();
    if (root) ((invalidate_fn)0x082655a0u)(root, root + 0x80);
}

static void notify_playback(void)
{
    void *model = model_for_service(0x7f00);
    /* A root repaint alone does not invalidate a BitmapView's borrowed
     * context. Refresh the shared artwork property as well as the controls,
     * so an attached Now Playing preview queries its current image again.
     * The native observer owns context cleanup; the model owns its pixels.
     */
    notify(model, 0x44726177u, 0x7f05);
    notify(model, 0x44726177u, 0x7f0c);
    notify(model, 0x44726177u, 0x7f0d);
}

void iop_appearance_poll(void)
{
    if (selected != 2) return;
    uint32_t next = resolved_mode();
    if (next == active) return;
    iop_appearance_apply(next);
    /* Borrow the current native service model for this notification only. */
    notify(model_for_service(0x8900), 0x2a2a2a2au, APPEARANCE_PREVIEW_IMAGE);
    notify_playback();
    repaint();
}

int iop_appearance_action(void *controller, const char *action, uint32_t argument)
{
    const char *wanted = "iOpenPod_Appearance_Toggle";
    const char *given = action;
    while (*given && *given == *wanted) { given++; wanted++; }
    if (*given || *wanted) {
        typedef int (*fn)(void *, const char *, uint32_t);
        return ((fn)0x0821daf4u)(controller, action, argument);
    }
    if (argument == 0xdeadbeefu) return 1;
    uint32_t next = selected == 2 ? 0 : selected + 1;
    save_error = !iop_save_setting(&preference, next);
    if (!save_error) {
        selected = next;
        iop_appearance_apply(resolved_mode());
    }
    notify(*(void **)((unsigned char *)controller + 0xb0), 0x2a2a2a2au, APPEARANCE_VALUE);
    notify(*(void **)((unsigned char *)controller + 0xb0), 0x2a2a2a2au, APPEARANCE_PREVIEW_IMAGE);
    if (!save_error) notify_playback();
    repaint();
    return 1;
}

int iop_appearance_property(void *model, uint32_t type, uint32_t property, uintptr_t *out)
{
    if (type == 0x424d6170u && property == APPEARANCE_PREVIEW_IMAGE) {
        typedef void *(*resources_fn)(void);
        typedef uintptr_t (*bitmap_fn)(void *, uint32_t);
        *out = ((bitmap_fn)0x08268d84u)(((resources_fn)0x08268d34u)(), active ? APPEARANCE_MOON : 0x0dad0bffu);
        return 1;
    }
    if (type == 0x53747220u && property == APPEARANCE_VALUE) {
        typedef void *(*resources_fn)(void);
        typedef uintptr_t (*string_fn)(void *, uint32_t);
        uint32_t id = save_error ? APPEARANCE_SAVE_ERROR : selected == 2 ? APPEARANCE_AUTO : selected ? APPEARANCE_DARK : APPEARANCE_LIGHT;
        *out = ((string_fn)0x08268d94u)(((resources_fn)0x08268d34u)(), id);
        return 1;
    }
    typedef int (*fn)(void *, uint32_t, uint32_t, uintptr_t *);
    return ((fn)0x081e11f4u)(model, type, property, out);
}

static uint32_t rgb(const unsigned char *color)
{
    return ((uint32_t)color[0] << 16) | ((uint32_t)color[1] << 8) | color[2];
}

static void rgba(uint32_t value, unsigned char alpha, unsigned char *out)
{
    out[0] = value >> 16; out[1] = value >> 8; out[2] = value; out[3] = alpha;
}

/* Foreground-only native text paths. Shadow has its own hook below. */
void iop_appearance_text(void *context, const unsigned char *color)
{
    unsigned char mapped[4];
    uint32_t value = rgb(color);
    if (value == 1) value = 0; /* black ink on intentionally light calendar paper */
    else if (active) {
        if (value == 0x236cc4u || value == 0x236cc5u || value == 0x3185d0u || value == 0x176ec1u)
            value = 0x77c2ffu;
        else if (color[0] == color[1] && color[1] == color[2] && color[0] <= 0xa4)
            value = color[0] <= 0x26 ? 0xedf3f9u : 0xb7c6d5u;
        else if (value == 0xff0000u) value = 0xff9292u;
        else if (value == 0x717d88u || value == 0x5e686fu) value = 0xb7c6d5u;
    }
    rgba(value, color[3], mapped);
    typedef void (*fn)(void *, const unsigned char *);
    ((fn)0x08259b28u)(context, mapped);
}

void iop_appearance_shadow(void *context, const unsigned char *color)
{
    typedef void (*fn)(void *, const unsigned char *);
    /* This qualified call passes TextView+0xa4, while its cached foreground is
     * at TextView+0xf4. Tagged black ink sits on unchanged light artwork and
     * keeps Apple's light embossed shadow, even while the rest of UI is dark. */
    if (!active || rgb((const unsigned char *)context + 0x50) == 1) {
        ((fn)0x08259b28u)(context, color);
        return;
    }
    unsigned char mapped[4];
    rgba(0x060a0fu, color[3], mapped);
    ((fn)0x08259b28u)(context, mapped);
}

void iop_appearance_option_text(void *context, const unsigned char *color)
{
    /* Apple's selected shuffle label is blue on a pale thumb. The themed
     * thumb is blue, so only this qualified option-bar path needs white ink. */
    unsigned char mapped[4];
    if (active && rgb(color) == 0x0071c4u) {
        rgba(0xedf3f9u, color[3], mapped);
        color = mapped;
    }
    iop_appearance_text(context, color);
}

void iop_appearance_mask(void *context, const unsigned char *color)
{
    /* BitmapView has its own cached tint and bypasses the text setter. Only
     * the sync-arrow resource is tagged; clock hands and battery overlays
     * retain their original colors on their original light artwork. */
    typedef void (*fn)(void *, const unsigned char *);
    if (rgb(color) != 2) {
        ((fn)0x08259b28u)(context, color);
        return;
    }
    unsigned char mapped[4];
    rgba(active ? 0xedf3f9u : 0, color[3], mapped);
    ((fn)0x08259b28u)(context, mapped);
}

int iop_appearance_selection_rect(const void *first, const void *second)
{
    /* Apple's one shared selection bitmap is keyed only by its rectangle.
     * Force its existing regeneration path on a theme change. No cache-owner
     * pointers, allocation metadata or view hierarchy are modified here. */
    if (selection_cache_mode != active) return 1;
    typedef int (*fn)(const void *, const void *);
    return ((fn)0x08298e0cu)(first, second);
}

static void gradient(void *context, const unsigned char *color, int low, int range,
                     const uint32_t *palette)
{
    unsigned char mapped[4];
    uint32_t value = rgb(color);
    if (active) {
        int level = color[1] - low;
        if (level < 0) level = 0;
        if (level > range) level = range;
        /* #2368a3 -> #2c70ad: all quantized stops retain >=4.5:1 primary
         * text contrast and >=3:1 separation from the main list surface. */
        value = palette[level];
    }
    selection_cache_mode = active;
    rgba(value, color[3], mapped);
    typedef void (*fn)(void *, const unsigned char *);
    ((fn)0x08259b28u)(context, mapped);
}

void iop_appearance_gradient_first(void *context, const unsigned char *color)
{
    gradient(context, color, 99, 65, appearance_gradient_first);
}

void iop_appearance_gradient_second(void *context, const unsigned char *color)
{
    gradient(context, color, 100, 52, appearance_gradient_second);
}

void iop_appearance_selection_border(void *context, const unsigned char *color)
{
    unsigned char mapped[4];
    /* A quiet top glint; bottom edge stays darker. */
    uint32_t value = active ? (color[1] > 170 ? 0x477da9u : 0x163d60u) : rgb(color);
    rgba(value, color[3], mapped);
    typedef void (*fn)(void *, const unsigned char *);
    ((fn)0x08259b28u)(context, mapped);
}

void iop_appearance_fill(void *surface, const void *rect, const unsigned char *color,
                         uint32_t mode, void *clip)
{
    unsigned char mapped[4];
    uint32_t value = rgb(color);
    if (active) {
        /* Only the native UI fill path; bitmap/photo/video pixels bypass it.
         * White list/lyrics surfaces become BASE. Bitmap chrome is themed by
         * semantic asset ID, so its gradient and shadow direction are retained. */
        if (color[0] == color[1] && color[1] == color[2] && color[0] >= 0xb0) {
            uint32_t step = (color[0] - 0xb0) / 8;
            value = ((9 + step) << 16) | ((15 + step) << 8) | (22 + step);
        } else if (value == 0x7e8183u) value = 0x405265u;
        else if (value == 0x236cc4u || value == 0x236cc5u) value = 0x2368a3u;
        /* Named native stopwatch/date bands and accessory background. These
         * tinted surfaces are not neutral white and need explicit treatment. */
        else if (value == 0xcddcf3u || value == 0x9ba9b8u) value = 0x243241u;
        else if (value == 0x717d88u) value = 0x1f2934u;
        else if (value == 0x5e686fu || value == 0xaaaaaau) value = 0x12181fu;
    }
    rgba(value, color[3], mapped);
    typedef void (*fn)(void *, const void *, const unsigned char *, uint32_t, void *);
    ((fn)0x08069a5cu)(surface, rect, mapped, mode, clip);
}

void iop_appearance_clear(int red, int green, int blue, int alpha)
{
    if (active) { red = 18 * 0x10000 / 255; green = 24 * 0x10000 / 255; blue = 31 * 0x10000 / 255; }
    typedef void (*fn)(int, int, int, int);
    ((fn)0x082c7820u)(red, green, blue, alpha);
}

uint32_t iop_appearance_reflection(uint32_t pixel, uint32_t background, int weight)
{
    if (active) background = ((18 >> 3) << 11) | ((24 >> 2) << 5) | (31 >> 3);
    typedef uint32_t (*fn)(uint32_t, uint32_t, int);
    return ((fn)0x0826a9a8u)(pixel, background, weight);
}

void *iop_resource_get_original(void *, uint32_t, uint32_t);
const void *iop_appearance_resource(void *service, uint32_t type, uint32_t id)
{
    static const uint32_t paper_ink = 1;
    static const uint32_t sync_arrow_ink = 2;
    const void *resource = iop_resource_get_original(service, type, id);
    /* The Settings calendar illustration intentionally remains light. A one-bit
     * tag survives native caches; the text hook resolves it to exact black in
     * both modes. It also quantizes to black in native RGB565 consumers. */
    if (resource && type == 0x434f4c52u && id == 0x0dad030fu
        && *(const uint32_t *)resource == 0)
        return &paper_ink;
    if (resource && type == 0x434f4c52u && id == 0x0dad0df2u
        && *(const uint32_t *)resource == 0)
        return &sync_arrow_ink;
    return resource;
}
