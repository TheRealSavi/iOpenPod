/* Dynamic BitmapView contexts borrow model bitmaps; they do not own pixels.
 * Qualified against Classic 2.0.5. See the artwork-lifetime research note.
 */
#include <stdint.h>
#ifdef IOP_ARTWORK_DIAGNOSTICS
void iop_artwork_trace_visibility(unsigned char *, uint32_t);
#endif

/* Follow Apple's 0x081eefc0 retained-thumbnail recipe, including its native
 * reference ownership and format 1055. Unlike that routine, check both the
 * wrapper and its loaded resource before initializing the bitmap: a failed
 * thumbnail-file read can leave a valid wrapper with no pixel resource.
 * The model's existing reference owns at most one current-track thumbnail.
 */
static void retain_current_art(unsigned char *model)
{
    typedef void *(*root_fn)(void);
    typedef void (*init_fn)(void *, unsigned);
    typedef void (*one_fn)(void *);
    typedef void (*track_fn)(void *, void *);
    typedef void (*view_fn)(void *, void *, unsigned);
    typedef void (*lookup_fn)(void *, void *, void *);
    typedef unsigned (*value_fn)(void *);
    typedef void (*load_fn)(void *, void *, unsigned, unsigned, unsigned);
    typedef void *(*object_fn)(void *);
    typedef void (*assign_fn)(void *, void *);
    typedef void (*bitmap_fn)(void *, void *, unsigned, unsigned);
    void *player = ((root_fn)0x0824ff20u)();
    if (!player) return;
    uint32_t database[18], track[4], view[6], record[3];
    void *reference = 0;
    ((init_fn)0x0815e378u)(database, 0);
    ((one_fn)0x0824f6d4u)(track);
    uintptr_t *vtable = *(uintptr_t **)player;
    ((track_fn)vtable[0xe4/4])(player, track);
    ((view_fn)0x08266d5cu)(view, track, 0);
    /* Video has different live-frame semantics; keep its native provider. */
    if (!((value_fn)0x08299644u)(view)) {
        ((lookup_fn)0x0815e1d0u)(record, database, view);
        if (((value_fn)0x082665a0u)(record)) {
            ((load_fn)0x082664d8u)(&reference, record, 1055, 1, 0);
            void *wrapper = ((object_fn)0x083cccfcu)(&reference);
            void *resource = wrapper ? ((object_fn)0x080f36a4u)(wrapper) : 0;
            if (resource) {
                ((assign_fn)0x083956a4u)(model+0xcc, &reference);
                ((bitmap_fn)0x08103984u)(model+0x18c, resource, 0, 0);
                *(uint32_t *)(model+0x3b4) = ((value_fn)0x082664d0u)(record);
            }
            ((one_fn)0x083935f4u)(&reference);
        }
        ((one_fn)0x082665f0u)(record);
    }
    ((one_fn)0x08266da0u)(view);
    ((one_fn)0x082509b4u)(database);
}

int iop_artwork_property(unsigned char *model, uint32_t type,
                         uint32_t property, uintptr_t *out)
{
    if (type == 0x44726177u && property == 0x7f05) {
        typedef uint32_t (*id_fn)(void *);
        typedef void *(*object_fn)(void *);
        uint32_t id = ((id_fn)0x081ed938u)(model);
        void *wrapper = ((object_fn)0x083cccfcu)(model+0xcc);
        if (id && (*(uint32_t *)(model+0x3b4) != id || !wrapper ||
                   !((object_fn)0x080f36a4u)(wrapper))) {
            *(uint32_t *)(model+0x3b4) = 0;
            retain_current_art(model);
        }
    }
    /* Preserve native property handling, placeholder selection, notifications,
     * track-ID validation and release of the old reference on fallback. */
    typedef int (*property_fn)(void *, uint32_t, uint32_t, uintptr_t *);
    return ((property_fn)0x081eda2cu)(model, type, property, out);
}

void iop_artwork_visibility(unsigned char *view, uint32_t visible)
{
#ifdef IOP_ARTWORK_DIAGNOSTICS
    iop_artwork_trace_visibility(view, visible);
#endif
    /* Keep immutable BMap resources cached. A Draw source can replace or evict
     * its image while this view is hidden, without a track/property event.
     * Drop only this view's 68-byte context on both edges of visibility. Do
     * not invalidate the shared model, release its bitmap, or flush its cache.
     * Calling the generic invalidator here can eagerly reload a visible view;
     * the original visibility handler below owns loading and repainting.
     */
    if (*(uint32_t *)(view + 0x40) == 0x44726177u) {
        void **context = (void **)(view + 0x15c);
        view[0xa1] = 0;
        if (*context) {
            typedef void (*destroy_fn)(void *);
            ((destroy_fn)0x0825b038u)(*context);
            ((destroy_fn)0x082a1730u)(*context);
            *context = 0;
        }
    }
    typedef void (*visibility_fn)(void *, uint32_t);
    ((visibility_fn)0x08100318u)(view, visible);
}
