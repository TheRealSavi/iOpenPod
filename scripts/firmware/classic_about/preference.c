/* SPDX-License-Identifier: GPL-3.0-only */
#include "preference.h"

struct preference { uint32_t magic, mode, complement; };

static int transfer(const struct setting_file *file, struct preference *record, int writing)
{
    void *handle;
    uint32_t count = 0;
    typedef int (*open_fn)(const struct setting_path *, uint32_t, uint32_t, void **);
    typedef int (*io_fn)(void *, void *, uint32_t, uint32_t, uint32_t *);
    typedef int (*close_fn)(void *);
    if (((open_fn)0x0804f784u)(&file->path, 0x64617461u, writing ? 2 : 1, &handle))
        return 0;
    int result = ((io_fn)(writing ? 0x0804ff68u : 0x0804f838u))(
        handle, record, sizeof(*record), writing ? 1 : 0, &count);
    ((close_fn)0x0804f6e4u)(handle);
    return !result && count == sizeof(*record);
}

int iop_read_setting(const struct setting_file *file, uint32_t *mode)
{
    struct preference record;
    if (!transfer(file, &record, 0) || record.magic != file->magic || record.mode > file->maximum ||
        record.complement != ~record.mode)
        return 0;
    *mode = record.mode;
    return 1;
}

int iop_save_setting(const struct setting_file *file, uint32_t mode)
{
    struct preference record = {file->magic, mode, ~mode};
    uint32_t confirmed;
    /* Apple discards flush/close error returns. Read-back is an additional
     * consistency check, not a guarantee against a later power loss. */
    return transfer(file, &record, 1) && iop_read_setting(file, &confirmed) && confirmed == mode;
}
