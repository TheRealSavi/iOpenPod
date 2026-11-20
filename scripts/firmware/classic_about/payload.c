/* Classic 2.0.5 About version and native Mods menu resource installation.
 * Native addresses are hash-bound by build_classic.py.
 */
#include <stdint.h>
#include "about_resources.h"
#include "menu_resources.h"

__attribute__((used, section(".iop.version")))
const char iop_platform_version[32] = IOP_PLATFORM_VERSION;

struct mod_identity {
    char magic[16];
    uint32_t schema;
    const char *version;
    uint32_t capacity;
};
__attribute__((used, section(".iop.identity")))
const struct mod_identity iop_mod_identity = {
    "IOPOD.MOD.VER1", 1, iop_platform_version, sizeof(iop_platform_version)
};

typedef void (*init_fn)(void *);
typedef void (*set_fn)(void *, uint32_t, uint32_t, const void *, uint32_t);
typedef void (*register_fn)(uint32_t);
typedef void (*string_init_fn)(void *, const char *);
typedef void (*string_destroy_fn)(void *);
typedef uint32_t *(*name_slot_fn)(void *, const void *);

/* Fully overwritten before each use. This workspace occupies reserved RAM only,
 * not OS image bytes, and never relies on native BSS initialization. resource_set
 * makes an owned copy before the next extension reuses it. */
__attribute__((section(".iop.scratch"), aligned(4)))
static unsigned char iop_resource_scratch[IOP_RESOURCE_SCRATCH_BYTES];

__attribute__((used))
void iop_resource_init(void *bank)
{
    ((init_fn)0x08111f00u)(bank);
    /* Apple's resource-name map resolves PushScreen's string arguments.
     * The native std::string is one pointer; its backing storage is owned.
     */
    for (uint32_t i = 0; i < sizeof(iop_menu_names) / sizeof(iop_menu_names[0]); i++) {
        void *name;
        ((string_init_fn)0x083cf82cu)(&name, iop_menu_names[i].name);
        uint32_t *slot = ((name_slot_fn)0x083d242cu)((void *)0x08ae02c4u, &name);
        *slot = iop_menu_names[i].id;
        ((string_destroy_fn)0x083cf7d4u)(&name);
    }
    set_fn set = (set_fn)0x08111e20u;
    set(bank, 0x53747220u, 0x0cf00000u, iop_mod_label, sizeof(iop_mod_label));
    set(bank, 0x53747220u, 0x0cf00001u, iop_platform_version, IOP_VERSION_BYTES);
    set(bank, 0x534f5243u, 0x0cf00002u, iop_label_source, sizeof(iop_label_source));
    set(bank, 0x534f5243u, 0x0cf00003u, iop_version_source, sizeof(iop_version_source));
    set(bank, 0x56696577u, 0x0dad0b2au, iop_about_view, sizeof(iop_about_view));
    for (uint32_t i = 0; i < sizeof(iop_menu_resources) / sizeof(iop_menu_resources[0]); i++) {
        const struct iop_resource *resource = &iop_menu_resources[i];
        set(bank, resource->type, resource->id, resource->data, resource->size);
    }
    for (uint32_t i = 0; i < sizeof(iop_menu_extensions) / sizeof(iop_menu_extensions[0]); i++) {
        const struct iop_extension *extension = &iop_menu_extensions[i];
        for (uint32_t j = 0; j < extension->stock_size; j++)
            iop_resource_scratch[j] = extension->stock[j];
        for (uint32_t j = 0; j < extension->tail_size; j++)
            iop_resource_scratch[extension->stock_size + j] = extension->tail[j];
        for (uint32_t j = 0; j < 4; j++)
            iop_resource_scratch[j] = (unsigned char)(extension->count >> (j * 8));
        set(bank, extension->type, extension->id, iop_resource_scratch,
            extension->stock_size + extension->tail_size);
    }
    /* The stock template ID remains enumerable; its new children need indexing. */
    ((register_fn)0x08194df0u)(0x56696577u);
    /* Re-index the added Extras item after the original ITEM table is overridden. */
    ((register_fn)0x08194df0u)(0x4954454du);
}
