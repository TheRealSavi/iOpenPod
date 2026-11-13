"""Native Playlist string import and bounded name-cache view."""

import struct

from iPodDB.library._alarm_name_data import PAIR_COMPOSITIONS


def native_alarm_name(value: str, *, compose: bool) -> str:
    raw = value.encode("utf-16-le", errors="surrogatepass")
    units = struct.unpack("<" + "H" * (len(raw) // 2), raw)
    if compose and units:
        output: list[int] = []
        pending = units[0]
        for following in units[1:]:
            combined = _compose(pending, following)
            if combined is None:
                output.append(pending)
                pending = following
            else:
                pending = combined
        units = (*output, pending)
    return struct.pack("<" + "H" * len(units[:255]), *units[:255]).decode(
        "utf-16-le", errors="surrogatepass"
    )


def _compose(first: int, second: int) -> int | None:
    if 0x1100 <= first <= 0x1112 and 0x1161 <= second <= 0x1175:
        return 0xAC00 + (first - 0x1100) * 588 + (second - 0x1161) * 28
    if (
        0xAC00 <= first <= 0xD7A3
        and (first - 0xAC00) % 28 == 0
        and 0x11A8 <= second <= 0x11C2
    ):
        return first + second - 0x11A7
    return PAIR_COMPOSITIONS.get((first, second))
