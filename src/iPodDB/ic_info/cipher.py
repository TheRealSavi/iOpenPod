"""Table-described 128-bit block transform recovered from the Classic firmware.

Only substitution/mixing data is required; this module contains no firmware
execution, filesystem access, or native-code loading.
"""

from dataclasses import dataclass

_MASK = 0xFFFFFFFF
_SHIFT = tuple((column * 4 + row * 5) % 16 for column in range(4) for row in range(4))


def _rotate(value: int, count: int) -> int:
    return ((value >> count) | (value << (32 - count))) & _MASK


def _inverse(table: bytes) -> bytes:
    if len(table) != 256 or len(set(table)) != 256:
        raise ValueError("Invalid cipher permutation")
    result = bytearray(256)
    for source, destination in enumerate(table):
        result[destination] = source
    return bytes(result)


@dataclass(frozen=True)
class CipherTables:
    """Small static substitution and mixing tables for one native cipher profile."""

    key_input: bytes
    key_substitution: bytes
    key_round_substitution: bytes
    input: bytes
    output: bytes
    final_substitution: bytes
    rounds: tuple[int, ...]
    shift: tuple[int, ...] = _SHIFT
    key_mixing: tuple[int, ...] | None = None
    reverse_schedule: bool = False


class TableCipher:
    """Forward and inverse block transformations using a verified mixing matrix."""

    def __init__(self, tables: CipherTables, key: bytes) -> None:
        if len(key) != 16 or len(tables.key_round_substitution) != 2560:
            raise ValueError("Invalid cipher key or round tables")
        self._tables = tables
        if tuple(sorted(tables.shift)) != tuple(range(16)):
            raise ValueError("Invalid cipher state permutation")
        self._input_inverse = _inverse(tables.input)
        self._output_inverse = _inverse(tables.output)
        self._final_inverse = _inverse(tables.final_substitution)
        if len(tables.rounds) != 256:
            raise ValueError("Invalid cipher mixing table")
        self._round_sub_inverse = _inverse(
            bytes(value >> 24 for value in tables.rounds)
        )
        self._mix_inverse, self._mix_origin = self._inverse_matrix()
        expanded = bytearray(tables.key_input[value] for value in key)
        for round_index in range(10):
            previous = expanded[-16:]
            current = bytearray(
                [
                    previous[0]
                    ^ tables.key_round_substitution[round_index * 256 + previous[13]]
                ]
            )
            for index in range(1, 4):
                current.append(
                    previous[index]
                    ^ tables.key_substitution[previous[12 + (index + 1) % 4]]
                )
            for index in range(4, 16):
                current.append(previous[index] ^ current[index - 4])
            expanded.extend(current)
        if tables.key_mixing is not None:
            if len(tables.key_mixing) != 256:
                raise ValueError("Invalid cipher key mixing table")
            for offset in range(16, 160, 4):
                value = 0
                for row in range(4):
                    value ^= _rotate(tables.key_mixing[expanded[offset + row]], row * 8)
                expanded[offset : offset + 4] = value.to_bytes(4, "big")
        keys = tuple(
            bytes(expanded[offset : offset + 16]) for offset in range(0, 176, 16)
        )
        self._keys = keys[::-1] if tables.reverse_schedule else keys

    def _inverse_matrix(self) -> tuple[tuple[int, ...], int]:
        table = self._tables.rounds
        inverse = self._round_sub_inverse
        origin = table[inverse[0]]
        affine = origin ^ _rotate(origin, 8) ^ _rotate(origin, 16) ^ _rotate(origin, 24)
        columns = tuple(
            _rotate(table[inverse[1 << bit]] ^ origin, row * 8)
            for row in range(4)
            for bit in range(8)
        )
        for value in range(256):
            linear = 0
            for bit in range(8):
                if value & (1 << bit):
                    linear ^= columns[bit]
            if linear != table[inverse[value]] ^ origin:
                raise ValueError("Cipher mixing table is not linear")
        rows = [
            sum(((column >> bit) & 1) << index for index, column in enumerate(columns))
            | (1 << (32 + bit))
            for bit in range(32)
        ]
        for bit in range(32):
            pivot = next(
                (index for index in range(bit, 32) if rows[index] & (1 << bit)), None
            )
            if pivot is None:
                raise ValueError("Cipher mixing matrix is singular")
            rows[bit], rows[pivot] = rows[pivot], rows[bit]
            for index in range(32):
                if index != bit and rows[index] & (1 << bit):
                    rows[index] ^= rows[bit]
        return tuple(row >> 32 for row in rows), affine

    def encode_input(self, data: bytes) -> bytes:
        """Convert one external block to the native cipher's internal bytes."""
        return data.translate(self._tables.input)

    def decode_input(self, data: bytes) -> bytes:
        """Undo the external input representation."""
        return data.translate(self._input_inverse)

    def encode_output(self, data: bytes) -> bytes:
        """Convert an internal encrypted block to its stored representation."""
        return data.translate(self._tables.output)

    def decode_output(self, data: bytes) -> bytes:
        """Undo the stored output representation."""
        return data.translate(self._output_inverse)

    def encrypt_internal(self, data: bytes) -> bytes:
        """Transform one already-normalized block, without outer byte mappings."""
        if len(data) != 16:
            raise ValueError("A cipher block must contain sixteen bytes")
        state = bytes(a ^ b for a, b in zip(data, self._keys[0], strict=True))
        for round_index in range(1, 10):
            result = bytearray()
            for column in range(4):
                value = int.from_bytes(
                    self._keys[round_index][column * 4 : column * 4 + 4], "big"
                )
                for row in range(4):
                    value ^= _rotate(
                        self._tables.rounds[
                            state[self._tables.shift[column * 4 + row]]
                        ],
                        row * 8,
                    )
                result.extend(value.to_bytes(4, "big"))
            state = bytes(result)
        return bytes(
            self._tables.final_substitution[state[index]] ^ key
            for index, key in zip(self._tables.shift, self._keys[10], strict=True)
        )

    def decrypt_internal(self, data: bytes) -> bytes:
        """Invert the block through an exact GF(2) matrix, with no search oracle."""
        if len(data) != 16:
            raise ValueError("A cipher block must contain sixteen bytes")
        state = bytearray(16)
        for output, source in enumerate(self._tables.shift):
            state[source] = self._final_inverse[data[output] ^ self._keys[10][output]]
        for round_index in range(9, 0, -1):
            previous = bytearray(16)
            for column in range(4):
                offset = column * 4
                value = (
                    int.from_bytes(state[offset : offset + 4], "big")
                    ^ int.from_bytes(
                        self._keys[round_index][offset : offset + 4], "big"
                    )
                    ^ self._mix_origin
                )
                decoded = sum(
                    ((row & value).bit_count() & 1) << bit
                    for bit, row in enumerate(self._mix_inverse)
                )
                for row in range(4):
                    previous[self._tables.shift[offset + row]] = (
                        self._round_sub_inverse[(decoded >> (row * 8)) & 255]
                    )
            state = previous
        return bytes(a ^ b for a, b in zip(state, self._keys[0], strict=True))

    def encrypt(self, data: bytes) -> bytes:
        """Encrypt one block in the profile's external representation."""
        return self.encode_output(self.encrypt_internal(self.encode_input(data)))

    def decrypt(self, data: bytes) -> bytes:
        """Decrypt one block in the profile's external representation."""
        return self.decode_input(self.decrypt_internal(self.decode_output(data)))
