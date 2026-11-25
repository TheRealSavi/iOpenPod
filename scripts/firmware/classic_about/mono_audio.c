/* SPDX-License-Identifier: GPL-3.0-only */
#include "mono_resources.h"
#include "preference.h"

/* The UI publishes one aligned word. The mixer samples it once per block. */
volatile uint32_t iop_mono_enabled;
static uint32_t save_error;
static const struct setting_file preference = {
    0x314e4f4du, 1, {0, "iPod_Control\\Device\\iOPMonoAudio"}
};

#ifdef IOP_DARK_MODE
extern uint32_t iop_preferences_hook(void *prefs);
extern int iop_appearance_action(void *, const char *, uint32_t);
extern int iop_appearance_property(void *, uint32_t, uint32_t, uintptr_t *);
#define load_other_preferences iop_preferences_hook
#define other_action iop_appearance_action
#define other_property iop_appearance_property
#else
#define load_other_preferences ((uint32_t (*)(void *))0x0809c69cu)
#define other_action ((int (*)(void *, const char *, uint32_t))0x0821daf4u)
#define other_property ((int (*)(void *, uint32_t, uint32_t, uintptr_t *))0x081e11f4u)
#endif

uint32_t iop_mono_preferences(void *prefs)
{
    uint32_t result = load_other_preferences(prefs);
    uint32_t mode = 0;
    iop_read_setting(&preference, &mode);
    iop_mono_enabled = mode;
    save_error = 0;
    return result;
}

int iop_mono_action(void *controller, const char *action, uint32_t argument)
{
    const char *given = action, *wanted = MONO_ACTION;
    while (*given && *given == *wanted) { given++; wanted++; }
    if (*given || *wanted)
        return other_action(controller, action, argument);
    if (argument == 0xdeadbeefu) return 1;

    uint32_t next = !iop_mono_enabled;
    save_error = !iop_save_setting(&preference, next);
    if (!save_error) iop_mono_enabled = next;
    void *model = *(void **)((unsigned char *)controller + 0xb0);
    if (model) {
        uintptr_t *vtable = *(uintptr_t **)model;
        typedef void (*notify_fn)(void *, uint32_t, uint32_t);
        ((notify_fn)vtable[0x58 / 4])(model, 0x2a2a2a2au, MONO_VALUE);
    }
    return 1;
}

int iop_mono_property(void *model, uint32_t type, uint32_t property, uintptr_t *out)
{
    if (type != 0x53747220u || property != MONO_VALUE)
        return other_property(model, type, property, out);
    uint32_t id = save_error ? MONO_SAVE_ERROR : iop_mono_enabled ? MONO_ON : MONO_OFF;
    typedef void *(*resources_fn)(void);
    typedef uintptr_t (*string_fn)(void *, uint32_t);
    *out = ((string_fn)0x08268d94u)(((resources_fn)0x08268d34u)(), id);
    return 1;
}
