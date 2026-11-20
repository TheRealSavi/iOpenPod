"""Encode reversible artwork changes for allocation-free native application."""


def encode_xor_delta(original: bytes, changed: bytes) -> bytes:
    """Pack literal bytes, repeated bytes, and repeated RGB565-sized words.

    Opcodes 0..127 carry 1..128 literal bytes; 128..191 repeat the next byte
    3..66 times; 192..255 repeat the next two bytes 2..65 times. A two-byte
    pattern works at any address, so trimmed native ranges need no alignment.
    """
    data = bytes(a ^ b for a, b in zip(original, changed, strict=True))

    def run(start: int) -> tuple[bytes, int] | None:
        end = start + 1
        while end < len(data) and end - start < 66 and data[end] == data[start]:
            end += 1
        if end - start >= 3:
            return bytes((128 + end - start - 3, data[start])), end - start
        end = start + 2
        while (
            end + 2 <= len(data)
            and (end - start) // 2 < 65
            and data[end : end + 2] == data[start : start + 2]
        ):
            end += 2
        if end - start >= 4:
            return (
                bytes((192 + (end - start) // 2 - 2,)) + data[start : start + 2],
                end - start,
            )
        return None

    encoded = bytearray()
    position = 0
    while position < len(data):
        if repeated := run(position):
            packet, count = repeated
            encoded.extend(packet)
            position += count
        else:
            end = position + 1
            while end < len(data) and end - position < 128 and run(end) is None:
                end += 1
            encoded.append(end - position - 1)
            encoded.extend(data[position:end])
            position = end
    return bytes(encoded)
