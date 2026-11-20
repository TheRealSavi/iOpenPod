/* SPDX-License-Identifier: GPL-3.0-only */
/* Classic 2.0.5 MP4 audio seek.
 *
 * Reader offsets and chunk-jump idea: kayboll/osos-lab PR 63, commit
 * bd573eb656c5af62572bfa7e5e8e8bf84a36bb6f (GPL-3.0-only).
 * Independently checked against the native setters, seek and packet getter.
 * Unlike that proposal, this hook runs AFTER native validation/video seeking,
 * plans without mutation, walks tables linearly, and never resets/retries an
 * unsupported seek or hides a failed file read. See the long-audio research note.
 */
#include <stdint.h>

enum {
    SIZES = 0x0c, OFFSETS = 0x10, RUNS = 0x14, DURATIONS = 0x18, EDITS = 0x1c,
    NEXT = 0x68, RUN = 0x6c, CHUNK = 0x70, IN_CHUNK = 0x74, BYTE_OFFSET = 0x78,
    SCALE = 0x7c, DURATION_POSITION = 0x84, PRESENTED = 0x88, MEDIA = 0x90,
    MEDIA_END = 0x98, DURATION_INDEX = 0xa0, EDIT_INDEX = 0xa4,
    EDIT_START = 0xa8, EDIT_END = 0xb0, EDIT_DURATION = 0xb8,
    WINDOW = 0x8000, MAX_ENTRIES = 0x8000, MIN_SKIP = 256
};
typedef int (*audio_seek_fn)(void *, uint32_t);
typedef uint64_t (*divide_fn)(uint64_t, uint64_t);
typedef int (*file_seek_fn)(void *, uint32_t, uint64_t, uint32_t);
typedef uint32_t (*file_read_fn)(void *, void *, uint32_t, uint32_t);

static uint32_t word(const void *p, uint32_t offset)
{
    return *(const uint32_t *)((const uint8_t *)p + offset);
}
static void *pointer(const void *p, uint32_t offset)
{
    return (void *)word(p, offset);
}
static uint64_t wide(const void *p, uint32_t offset)
{
    return word(p, offset) | (uint64_t)word(p, offset + 4) << 32;
}
static void put(void *p, uint32_t offset, uint32_t value)
{
    *(uint32_t *)((uint8_t *)p + offset) = value;
}
static void put_wide(void *p, uint32_t offset, uint64_t value)
{
    put(p, offset, (uint32_t)value);
    put(p, offset + 4, (uint32_t)(value >> 32));
}
static uint64_t divide(uint64_t value, uint64_t by)
{
    return ((divide_fn)0x08024024)(value, by);
}

struct duration { uint32_t count, delta; };
struct run { uint32_t first, samples, description; };
struct plan {
    uint32_t sample, chunk, run, duration_index, duration_position;
    uint64_t media, presented, edit_start, edit_duration;
    int has_edit;
};

/* Everything is checked before modifying cursors or doing file I/O. The caps
 * bound work and keep the stsc look-ahead inside the native resident window. */
static int plan_seek(void *reader, void *track, uint32_t ms, struct plan *p)
{
    const void *sz = pointer(track, SIZES), *sc = pointer(track, RUNS);
    const void *ts = pointer(track, DURATIONS), *co = pointer(track, OFFSETS);
    if (!ms || ms > INT32_MAX || !sz || !sc || !ts || !co ||
        wide(track, 0x48) == UINT64_MAX)
        return 0;
    uint32_t total = word(sz, 4), scale = word(track, SCALE);
    uint32_t nr = word(sc, 0), nt = word(ts, 0), chunks = word(co, 0);
    const struct run *runs = pointer(sc, 8);
    const struct duration *durations = pointer(ts, 8);
    if (total <= MIN_SKIP || total > INT32_MAX || !scale || scale > INT32_MAX ||
        !runs || !durations || !nr || nr >= WINDOW || word(sc, 4) ||
        !nt || nt > MAX_ENTRIES || !chunks || chunks > INT32_MAX)
        return 0;
    uint64_t length = 0;
    uint32_t seen = 0;
    for (uint32_t i = 0; i < nt; i++) {
        uint32_t count = durations[i].count, delta = durations[i].delta;
        if (!count || count > total - seen || !delta || delta > INT32_MAX)
            return 0;
        seen += count;
        length += (uint64_t)count * delta;
    }
    if (seen != total || length != wide(track, MEDIA_END) || length > UINT64_MAX / 1000)
        return 0;

    const void *edits = pointer(track, EDITS);
    uint64_t start = 0, end = length;
    p->has_edit = edits != 0;
    p->edit_duration = length;
    if (edits) {
        const void *edit = pointer(edits, 4);
        uint32_t movie_scale = word(reader, 0x64);
        if (word(edits, 0) != 1 || !edit || !movie_scale ||
            word(edit, 12) & 0x80000000u ||
            wide(edit, 0) > divide(INT64_MAX, scale))
            return 0;
        start = wide(edit, 8);
        p->edit_duration = divide(wide(edit, 0) * scale, movie_scale);
        if (start >= length || p->edit_duration > INT64_MAX - start)
            return 0;
        end = start + p->edit_duration;
        if (end <= start || end > length)
            return 0;
    }
    p->edit_start = start;

    /* The native walker counts a sample only when its START is in the edit.
     * Round the trim up to that first presented sample, including priming. */
    uint64_t time = 0, presented_base = 0;
    uint32_t first_presented = 0;
    seen = 0;
    for (uint32_t i = 0; i < nt; i++) {
        uint64_t span = (uint64_t)durations[i].count * durations[i].delta;
        if (start < time + span) {
            uint32_t skip = (uint32_t)divide(start - time + durations[i].delta - 1,
                                            durations[i].delta);
            first_presented = seen + skip + 1;
            presented_base = time + (uint64_t)skip * durations[i].delta;
            break;
        }
        time += span;
        seen += durations[i].count;
    }
    if (!first_presented || first_presented > total)
        return 0;
    uint64_t target = divide((uint64_t)ms * scale, 1000);
    if (target >= wide(track, PRESENTED) &&
        divide(wide(track, PRESENTED) * 1000, scale) &&
        (wide(track, MEDIA) >= length || word(track, EDIT_INDEX)))
        return 0; /* Preserve native terminal/error-state continuation. */
    uint64_t limit = target + presented_base;
    if (limit > end)
        limit = end;
    /* Strictly before target/edit end: leave the terminal transition, rounding
     * and return status to Apple's walker. No edit-end comparison is skipped. */
    time = 0;
    uint32_t last = 0;
    for (uint32_t i = 0; i < nt && time < limit; i++) {
        uint64_t span = (uint64_t)durations[i].count * durations[i].delta;
        if (time + span >= limit) {
            last += (uint32_t)divide(limit - time - 1, durations[i].delta);
            break;
        }
        last += durations[i].count;
        time += span;
    }
    if (last < first_presented || runs[0].first != 1)
        return 0;
    p->sample = 0;
    uint64_t first = 1;
    for (uint32_t i = 0; i < nr; i++) {
        uint32_t next = i + 1 < nr ? runs[i + 1].first : chunks + 1;
        uint32_t per = runs[i].samples;
        if (!per || per > total || runs[i].first >= next || next > chunks + 1 ||
            first > total)
            return 0;
        if (first <= last) {
            uint32_t skip = (uint32_t)divide(last - first, per);
            if (skip >= next - runs[i].first)
                skip = next - runs[i].first - 1;
            p->sample = (uint32_t)(first + (uint64_t)skip * per);
            p->chunk = runs[i].first + skip;
            p->run = i;
        }
        first += (uint64_t)(next - runs[i].first) * per;
        if (i + 1 == nr && (first <= total || first - per > total))
            return 0; /* Missing samples, or an entirely empty final chunk. */
    }
    if (p->sample < first_presented || p->sample <= MIN_SKIP)
        return 0;
    /* Keep cheap forward/repeated seeks in the original current-state path. */
    if (target >= wide(track, PRESENTED) &&
        divide(wide(track, PRESENTED) * 1000, scale) &&
        (uint64_t)p->sample < (uint64_t)word(track, NEXT) + MIN_SKIP)
        return 0;
    time = 0;
    seen = 0;
    for (uint32_t i = 0; i < nt; i++) {
        if (p->sample <= seen + durations[i].count) {
            p->duration_index = i;
            p->duration_position = p->sample - seen;
            p->media = time + (uint64_t)p->duration_position * durations[i].delta;
            p->presented = p->media - presented_base;
            /* Native seek resets if the current presented time rounds to 0ms. */
            return divide(p->presented * 1000, scale) != 0;
        }
        time += (uint64_t)durations[i].count * durations[i].delta;
        seen += durations[i].count;
    }
    return 0;
}

/* Native 0x081bac44 uses a table reader that accepts ANY nonzero byte count.
 * For our new direct jump, demand the complete window before publishing its
 * base or any cursor. A short read invalidates the overwritten cache and fails. */
static int sample_size(void *reader, void *track, uint32_t sample, uint32_t *out)
{
    void *sz = pointer(track, SIZES);
    *out = word(sz, 0);
    if (*out)
        return 0;
    uint32_t index = sample - 1, base = word(sz, 8), total = word(sz, 4);
    uint32_t *data = pointer(sz, 12);
    if (!data)
        return 3;
    if (index < base || index - base >= WINDOW) {
        uint32_t count = total - index;
        if (count > WINDOW)
            count = WINDOW;
        void *file = pointer(reader, 8);
        if (!file || !pointer(file, 0))
            return 3;
        const void *vtable = pointer(file, 0);
        uint64_t position = wide(track, 0x58);
        uint64_t delta = 20 + (uint64_t)index * 4;
        if (position > UINT64_MAX - delta)
            return 3;
        file_seek_fn seek = (file_seek_fn)word(vtable, 0x14);
        file_read_fn read = (file_read_fn)word(vtable, 0x10);
        if (!seek || !read || seek(file, 0, position + delta, 0))
            return 3;
        if (read(file, data, count * 4, 2) != count * 4) {
            put(sz, 8, total); /* Force a reload on the next valid native seek. */
            return 3;
        }
        for (uint32_t i = 0; i < count; i++)
            data[i] = ((uint32_t (*)(const void *))0x0806957c)(&data[i]);
        base = index;
        put(sz, 8, base);
    }
    *out = data[index - base];
    return 0;
}

int iop_audio_seek(void *reader, uint32_t ms)
{
    audio_seek_fn native = (audio_seek_fn)0x081bb188;
    void *track = pointer(reader, 0x1b8);
    struct plan p;
    if (!track || !plan_seek(reader, track, ms, &p))
        return native(reader, ms);
    uint64_t previous = wide(track, PRESENTED);
    uint32_t scale = word(track, SCALE);
    uint32_t failure_next =
        divide((uint64_t)ms * scale, 1000) < previous ||
        !divide(previous * 1000, scale) ? 1 : word(track, NEXT);
    uint32_t bytes;
    int error = sample_size(reader, track, p.sample, &bytes);
    if (error)
        return error;
    /* Same state as native consumption of the first sample of this chunk.
     * No retained allocation, file-data write, global cache or new timer. */
    put(track, NEXT, p.sample + 1);
    put(track, RUN, p.run);
    put(track, CHUNK, p.chunk);
    put(track, IN_CHUNK, 1);
    put(track, BYTE_OFFSET, bytes);
    put(track, DURATION_INDEX, p.duration_index);
    put(track, DURATION_POSITION, p.duration_position);
    put_wide(track, MEDIA, p.media);
    put_wide(track, PRESENTED, p.presented);
    put(track, EDIT_INDEX, 0);
    if (p.has_edit) {
        put_wide(track, EDIT_START, p.edit_start);
        put_wide(track, EDIT_END, p.edit_start + p.edit_duration);
        put_wide(track, EDIT_DURATION, p.edit_duration);
    }
    error = native(reader, ms);
    /* The native walker keeps NEXT in a register and publishes it only on
     * success. Preserve that convention on edit-end and tail-read failures. */
    if (error)
        put(track, NEXT, failure_next);
    return error;
}
