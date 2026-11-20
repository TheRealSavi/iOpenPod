#include <stdint.h>

/* Bds calls this with the real SysInfo hardware and directory image version.
 * Retain the older family-24 stock path during migration to the common image.
 */
uint32_t shared_version_check(void *self, uint32_t hardware, uint32_t image)
{
    (void)self;
    if (hardware < 0x130000u || hardware > 0x130300u || (hardware & 255u))
        return 0x80000003u;
    if ((image - 0x15000u) < 0x1000u ||
        (hardware == 0x130000u && (image - 0x13000u) < 0x1000u))
        return 0;
    return 0x80000003u;
}
