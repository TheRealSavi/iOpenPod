/* SPDX-License-Identifier: GPL-3.0-only */
#pragma once
#include <stdint.h>

struct setting_path { uint16_t volume; char text[258]; };

struct setting_file {
    uint32_t magic, maximum;
    struct setting_path path;
};

int iop_read_setting(const struct setting_file *file, uint32_t *mode);
int iop_save_setting(const struct setting_file *file, uint32_t mode);
