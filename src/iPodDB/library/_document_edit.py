"""Pure retained-tree replacement, shared by the reconciliation passes."""

from dataclasses import replace

from iPodDB.shared.chunk import ChunkHeader, ParsedChunk


def rebuild[H: ChunkHeader](
    chunk: ParsedChunk[H], replacements: dict[int, ParsedChunk[ChunkHeader] | None]
) -> ParsedChunk[H]:
    children: list[ParsedChunk[ChunkHeader]] = []
    for child in chunk.children:
        if id(child) in replacements:
            replacement = replacements[id(child)]
            if replacement is not None:
                children.append(replacement)
        else:
            children.append(rebuild(child, replacements))
    return (
        chunk
        if tuple(children) == chunk.children
        else replace(chunk, children=tuple(children))
    )
