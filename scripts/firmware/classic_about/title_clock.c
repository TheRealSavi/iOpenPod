/* Display the native clock alongside the original Classic title binding. */
#include <stdint.h>
#include "title_clock_layouts.h"

typedef void *(*layout_fn)(uint32_t, uint32_t);
typedef int (*property_fn)(void *, uint32_t, uint32_t, const void **);

void *iop_title_clock_layout(uint32_t id, uint32_t kind)
{
    if (kind == 0x564c7974u) { /* VLyt in the native layout application path */
        uint32_t enabled = clock_layout(id);
        if (enabled != id) {
            void *settings = ((void *(*)(void))0x08167a54u)();
            if (settings && ((int (*)(void *))0x0816833cu)(settings))
                id = enabled;
        }
    }
    return ((layout_fn)0x0817a900u)(id, kind);
}

int iop_title_clock_property(unsigned char *proxy, uint32_t kind,
                             uint32_t id, const void **result)
{
    /* The applied left constraint of these titles names their clock sibling.
     * Apple's alternator retains the screen's current source, including rebinds. */
    unsigned char *title = *(unsigned char **)(proxy + 0x5c);
    if (kind == 0x53747220u && title) {
        uint32_t relative = *(uint32_t *)(title + 0x5c);
        if (relative - CLOCK_FIRST < CLOCK_COUNT) {
            void *source = *(void **)(proxy + 0x60);
            if (!source) return 0;
            *result = ((const void *(*)(void *, uint32_t, uint32_t))0x08268b64u)(
                source, kind, id);
            return 1;
        }
    }
    return ((property_fn)0x0819ce88u)(proxy, kind, id, result);
}

void iop_title_clock_left(unsigned char *view, const uint32_t *bounds, unsigned redraw)
{
    /* Only a modded title's left constraint can name one of these clocks.
     * Apple's TextView constructor stores left=0, center=1 at offset 0xe9. */
    if (originally_centered(bounds[3]))
        view[0xe9] = 0;
    else if (originally_centered(*(uint32_t *)(view + 0x5c)))
        view[0xe9] = 1;
    ((void (*)(void *, const uint32_t *, unsigned))0x082641dcu)(view, bounds, redraw);
}
