/* SPDX-License-Identifier: GPL-3.0-only
 * Read-only boot-time NOR measurement. SPI sequencing derives from the pinned
 * Rockbox implementation used by scripts/bootloader/native/helper.c.
 * Runs before Apple's OS entry, with interrupts masked and no OS/heap calls.
 * USB serialization only reads the retained result; it never touches hardware.
 */
#include <stdint.h>
#include "../../bootloader/native/vendor/sha256.h"
#include "boot_report_resources.h"

#define REG(a) (*(volatile uint32_t *)(a))
#define SPI(a) REG(0x3c300000u + (a))
#define NOR_BYTES 0x100000u
#define BOOT_OFFSET 0x8000u
#define BODY_OFFSET 0x8800u
#define BODY_BYTES 0x1f800u

enum report_status { READ_ERROR = 1, UNSUPPORTED = 2, ENCRYPTED = 3, MEASURED = 4 };
struct boot_report {
    uint32_t status, hardware;
    char serial[16], model[16];
    uint8_t marker[64], digest[32];
};
static struct boot_report report;
static uint32_t poll_budget;

/* SHA-256 runs before libc or Apple's runtime is initialized. */
void *memcpy(void *dest, const void *source, size_t bytes)
{
    uint8_t *out = dest;
    const uint8_t *in = source;
    for (size_t i = 0; i < bytes; i++) out[i] = in[i];
    return dest;
}

void *memset(void *dest, int value, size_t bytes)
{
    uint8_t *out = dest;
    for (size_t i = 0; i < bytes; i++) out[i] = (uint8_t)value;
    return dest;
}

static uint32_t word(const uint8_t *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static int equal(const uint8_t *a, const uint8_t *b, unsigned bytes)
{
    for (unsigned i = 0; i < bytes; i++)
        if (a[i] != b[i]) return 0;
    return 1;
}

static void select_nor(int selected)
{
    REG(0x3cf00200u) = selected ? 0x0e : 0x0f;
}

/* One shared budget bounds all polling, including failed or absent hardware. */
static int transfer(uint8_t tx, uint8_t *rx)
{
    if (!poll_budget) return 0;
    SPI(0x34) = 1;
    do { if (!--poll_budget) return 0; } while ((SPI(8) & 0x1f0) == 0x100);
    SPI(0x10) = tx;
    do { if (!--poll_budget) return 0; } while (!(SPI(8) & 0x3e00));
    *rx = (uint8_t)SPI(0x20);
    return 1;
}

static int send(uint8_t tx)
{
    uint8_t ignored;
    return transfer(tx, &ignored);
}

static int read_nor(uint32_t offset, uint8_t *out, uint32_t bytes)
{
    if (offset > NOR_BYTES || bytes > NOR_BYTES - offset) return 0;
    select_nor(1);
    int ok = send(3) && send(offset >> 16) && send(offset >> 8) && send(offset);
    for (uint32_t i = 0; ok && i < bytes; i++) ok = transfer(0xff, out + i);
    select_nor(0);
    return ok;
}

static int text(char out[16], const uint8_t *in)
{
    unsigned end = 0;
    while (end < 16 && in[end]) {
        if (!((in[end] >= 'A' && in[end] <= 'Z') ||
              (in[end] >= '0' && in[end] <= '9'))) return 0;
        end++;
    }
    if (!end || end == 16) return 0;
    for (unsigned i = end; i < 16; i++) if (in[i]) return 0;
    for (unsigned i = 0; i < 16; i++) out[i] = (char)in[i];
    return 1;
}

static int read_identity(void)
{
    uint8_t data[24];
    if (!read_nor(0, data, sizeof(data))) return 0;
    uint32_t count = word(data + 20), size = word(data + 4);
    if (word(data) != 0x53436667 || word(data + 8) != 0x2000 ||
        word(data + 12) != 0x10001 || word(data + 16) || count > 408 ||
        size != 24 + count * 20 || size > 8192) return 0;
    unsigned found = 0;
    for (uint32_t i = 0; i < count; i++) {
        if (!read_nor(24 + i * 20, data, 20)) return 0;
        uint32_t key = word(data);
        if (key == 0x53724e6d) { /* SrNm */
            if ((found & 1) || !text(report.serial, data + 4)) return 0;
            found |= 1;
        } else if (key == 0x4d6f6423) { /* Mod# */
            if ((found & 2) || !text(report.model, data + 4)) return 0;
            found |= 2;
        } else if (key == 0x48775672) { /* HwVr */
            if (found & 4) return 0;
            report.hardware = word(data + 8);
            found |= 4;
        }
    }
    return found == 7;
}

static void measure(void)
{
    uint8_t buffer[256];
    if (!read_identity() || !read_nor(BOOT_OFFSET, buffer, 16)) return;
    report.status = UNSUPPORTED;
    if (!equal(buffer, (const uint8_t *)"87021.0", 7) ||
        word(buffer + 12) != BODY_BYTES) return;
    if (buffer[7] == 1) { report.status = ENCRYPTED; return; }
    if (buffer[7] != 2) return;
    report.status = READ_ERROR;
    struct sha256 hash;
    sha256_init(&hash);
    for (uint32_t offset = 0; offset < BODY_BYTES; offset += sizeof(buffer)) {
        if (!read_nor(BODY_OFFSET + offset, buffer, sizeof(buffer))) return;
        sha256_update(&hash, buffer, sizeof(buffer));
    }
    sha256_final(&hash, report.digest);
    unsigned markers = 0;
    for (unsigned i = 0; i < sizeof(iop_marker_offsets) / sizeof(iop_marker_offsets[0]); i++) {
        if (!read_nor(BODY_OFFSET + iop_marker_offsets[i], buffer, 64)) return;
        if (equal(buffer, (const uint8_t *)"iOpenPod-Bootloader-v1",
                  sizeof("iOpenPod-Bootloader-v1") - 1)) {
            for (unsigned j = 0; j < 64; j++) report.marker[j] = buffer[j];
            markers++;
        }
    }
    if (markers > 1) { report.status = UNSUPPORTED; return; }
    report.status = MEASURED;
}

void iop_boot_report_capture(void)
{
    uint32_t cpsr;
    __asm__ volatile("mrs %0, cpsr\n\torr r12, %0, #0xc0\n\tmsr cpsr_c, r12"
                     : "=r"(cpsr) : : "r12", "memory", "cc");
    report.status = READ_ERROR;
    uint32_t gpio = REG(0x3cf00000u), power = REG(0x3c50004cu);
    REG(0x3c50004cu) = power & ~((1u << 2) | (1u << 12));
    static const unsigned offsets[] = {0, 4, 0xc, 0x30, 0x34, 0x38};
    uint32_t saved[6];
    for (unsigned i = 0; i < 6; i++) saved[i] = SPI(offsets[i]);
    REG(0x3cf00000u) = (gpio & ~0xffffu) | 0x2222;
    select_nor(0);
    SPI(8) = 15; SPI(0) |= 12; SPI(0x30) = 4; SPI(0xc) = 6;
    SPI(4) = 0x10618; SPI(0) |= 12; SPI(0) = 1;
    poll_budget = 8000000;
    uint8_t status;
    select_nor(1);
    int ready = send(5) && transfer(0xff, &status) && !(status & 0x41);
    select_nor(0);
    if (ready) measure();
    select_nor(0);
    for (unsigned i = 0; i < 6; i++) SPI(offsets[i]) = saved[i];
    REG(0x3cf00000u) = gpio;
    REG(0x3c50004cu) = power;
    __asm__ volatile("msr cpsr_c, %0" : : "r"(cpsr) : "memory", "cc");
}

static void hex(char *out, const uint8_t *data, unsigned bytes)
{
    static const char digits[] = "0123456789abcdef";
    for (unsigned i = 0; i < bytes; i++) {
        out[2*i] = digits[data[i] >> 4];
        out[2*i+1] = digits[data[i] & 15];
    }
    out[2*bytes] = 0;
}

typedef void (*integer_fn)(void *, const char *, uint32_t, unsigned);
typedef void (*string_fn)(void *, const char *, const char *, unsigned);
typedef void (*dict_fn)(void *, const char *, unsigned);
typedef void (*close_fn)(void *, unsigned);
extern const char iop_platform_version[32];
#ifdef IOP_ARTWORK_DIAGNOSTICS
void iop_artwork_trace_xml(void *);
#endif

/* Replaces only SysInfo's root-dict close. Native writers count missing buffer
 * space on pass one; the caller grows its allocation and serializes again. */
void iop_boot_report_xml(void *writer, unsigned depth)
{
    integer_fn integer = (integer_fn)0x0811891cu;
    string_fn string = (string_fn)0x08118b50u;
    close_fn close = (close_fn)0x08118cf0u;
    ((dict_fn)0x08118a14u)(writer, "iOpenPodBootReport", 1);
    integer(writer, "Schema", 1, 2);
    integer(writer, "Status", report.status, 2);
    string(writer, "ModVersion", iop_platform_version, 2);
    if (report.status == MEASURED || report.status == ENCRYPTED) {
        string(writer, "DeviceSerial", report.serial, 2);
        string(writer, "DeviceModel", report.model, 2);
        integer(writer, "HardwareRevision", report.hardware, 2);
    }
    if (report.status == MEASURED) {
        char encoded[129];
        hex(encoded, report.digest, 32);
        string(writer, "BodySHA256", encoded, 2);
        hex(encoded, report.marker, 64);
        string(writer, "Marker", encoded, 2);
    }
    close(writer, 1);
#ifdef IOP_ARTWORK_DIAGNOSTICS
    iop_artwork_trace_xml(writer);
#endif
    close(writer, depth);
}
