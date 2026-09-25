from __future__ import annotations

import shlex
import tkinter as tk
from collections.abc import Hashable, Mapping
from dataclasses import Field, dataclass, fields, is_dataclass
from enum import Enum
from functools import cache
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING, Any, NamedTuple, Protocol, cast

from iPodDB.ArtworkDB.parser.parse_ArtworkDB import parse_ArtworkDB
from iPodDB.ArtworkDB.shared.database_definition import (
    DATABASE_DEFINITION as ARTWORK_DATABASE_DEFINITION,
)
from iPodDB.iTunesDB.cdb import decompress_iTunesCDB, is_iTunesCDB
from iPodDB.iTunesDB.parser.parse_iTunesDB import parse_iTunesDB
from iPodDB.iTunesDB.shared.database_definition import (
    DATABASE_DEFINITION as ITUNES_DATABASE_DEFINITION,
)
from iPodDB.shared.chunk import (
    ChunkHeader,
    MhodChunkHeader,
    MhsdChunkHeader,
    ParsedChunk,
)
from iPodDB.shared.errors import UnexpectedHeaderMarkerError, iPodDBParseError

if TYPE_CHECKING:
    from collections.abc import Iterator

type ChunkNode = ParsedChunk[ChunkHeader]


class DatabaseFamily(Enum):
    ITUNES_DB = "iTunesDB"
    ARTWORK_DB = "ArtworkDB"


@dataclass(frozen=True, slots=True)
class BrowsableDatabase:
    family: DatabaseFamily
    document: ChunkNode


def parse_browsable_database(data: bytes | bytearray) -> BrowsableDatabase:
    """Parse bytes through the one database family declared by their root marker."""

    root_marker = bytes(data[:4])

    if root_marker == ITUNES_DATABASE_DEFINITION.root_chunk.marker:
        return BrowsableDatabase(
            family=DatabaseFamily.ITUNES_DB,
            document=parse_iTunesDB(
                decompress_iTunesCDB(data).logical_bytes if is_iTunesCDB(data) else data
            ),
        )

    if root_marker == ARTWORK_DATABASE_DEFINITION.root_chunk.marker:
        return BrowsableDatabase(
            family=DatabaseFamily.ARTWORK_DB,
            document=parse_ArtworkDB(data),
        )

    raise UnexpectedHeaderMarkerError(
        "Chunk Browser requires an iTunesDB or ArtworkDB root Header Marker; "
        f"got {root_marker!r}"
    )


class _WeightedPanedWindow(Protocol):
    def add(self, child: tk.Widget, *, weight: int) -> None: ...


class SearchEntry(NamedTuple):
    path: str
    field_name: str
    type_name: str
    value: str


class SearchTerm(NamedTuple):
    field_name: str | None
    value: str


@cache
def cached_fields(cls: type[object]) -> tuple[Field[object], ...]:
    return cast(
        "tuple[Field[object], ...]",
        fields(cast("Any", cls)),
    )


def marker_text(marker: bytes) -> str:
    try:
        text = marker.decode("ascii")
    except UnicodeDecodeError:
        return marker.hex()

    if text.isprintable():
        return text

    return marker.hex()


def named_tuple_field_names(
    value: tuple[object, ...],
) -> tuple[str, ...] | None:
    raw_fields = getattr(type(value), "_fields", None)

    if not isinstance(raw_fields, tuple):
        return None

    field_names = cast("tuple[object, ...]", raw_fields)

    if not all(isinstance(item, str) for item in field_names):
        return None

    return cast("tuple[str, ...]", field_names)


def parse_search_query(query: str) -> tuple[SearchTerm, ...]:
    """
    Parse a search query.

    Examples:
        mhod
        total_tracks
        "The Rolling Stones"
        mhod "The Rolling Stones"
        total_tracks=19
        mhod_type=17
        name="The Rolling Stones"
        type=MhodChapterDataPayload

    Bare terms use case-insensitive substring matching across type names,
    field names, field paths, and values.

    field=value terms require an exact value match for the named field.
    """

    tokens = shlex.split(query)

    terms: list[SearchTerm] = []

    for token in tokens:
        if "=" in token:
            field_name, expected_value = token.split("=", 1)

            field_name = field_name.strip()
            expected_value = expected_value.strip()

            if field_name and expected_value:
                terms.append(
                    SearchTerm(
                        field_name=field_name.casefold(),
                        value=expected_value.casefold(),
                    )
                )
                continue

        token = token.strip()

        if token:
            terms.append(
                SearchTerm(
                    field_name=None,
                    value=token.casefold(),
                )
            )

    return tuple(terms)


def search_value_text(value: object) -> str:
    if isinstance(value, bytes):
        if not value:
            return ""

        try:
            text = value.decode("utf-8")
        except UnicodeDecodeError:
            return value.hex()

        if text.isprintable():
            return text

        return value.hex()

    if isinstance(value, Enum):
        return str(value.value)

    return str(value)


def is_search_container(value: object) -> bool:
    return is_dataclass(value) or isinstance(
        value, (Mapping, list, tuple, set, frozenset)
    )


class ObjectInspector(ttk.Treeview):
    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(
            parent,
            columns=("type", "value"),
            show="tree headings",
        )

        self.cache: dict[str, object] = {}

        self.heading("#0", text="Property")
        self.heading("type", text="Type")
        self.heading("value", text="Value")

        self.column("#0", width=250)
        self.column("type", width=200)
        self.column("value", width=600)

        self.bind(
            "<<TreeviewOpen>>",
            self.expand,
        )

    def inspect(self, value: object) -> None:
        self.delete(*self.get_children())
        self.cache.clear()

        self.add(
            "",
            value,
            type(value).__name__,
        )

    def add(
        self,
        parent: str,
        value: object,
        name: str,
    ) -> None:
        children = list(self.fields_for(value))

        node = self.insert(
            parent,
            "end",
            text=name,
            values=(
                type(value).__name__,
                "" if children else self.display(value),
            ),
        )

        self.cache[node] = value

        if children:
            self.insert(
                node,
                "end",
                text="loading",
            )

    def expand(self, _event: object) -> None:
        node = self.focus()

        if node not in self.cache:
            return

        children = self.get_children(node)

        if len(children) != 1:
            return

        if self.item(children[0], "text") != "loading":
            return

        self.delete(children[0])

        for name, value in self.fields_for(
            self.cache[node],
        ):
            self.add(
                node,
                value,
                name,
            )

    def fields_for(
        self,
        value: object,
    ) -> Iterator[tuple[str, object]]:
        if is_dataclass(value):
            for dataclass_field in cached_fields(cast("Hashable", type(value))):
                yield (
                    dataclass_field.name,
                    getattr(
                        value,
                        dataclass_field.name,
                    ),
                )

            return

        if isinstance(value, Mapping):
            mapping = cast("Mapping[object, object]", value)

            for key, item in mapping.items():
                yield str(key), item

            return

        if isinstance(value, tuple):
            tuple_items = cast("tuple[object, ...]", value)
            named_fields = named_tuple_field_names(tuple_items)

            if named_fields is not None:
                for index, field_name in enumerate(named_fields):
                    yield field_name, tuple_items[index]

                return

            for index, item in enumerate(tuple_items):
                yield f"[{index}]", item

            return

        if isinstance(value, list):
            list_items = cast("list[object]", value)

            for index, item in enumerate(list_items):
                yield f"[{index}]", item

            return

        if isinstance(value, (set, frozenset)):
            set_items = cast("set[object] | frozenset[object]", value)

            for index, item in enumerate(set_items):
                yield f"[{index}]", item

    def display(self, value: object) -> str:
        if isinstance(value, bytes):
            if len(value) == 0:
                return "b''"

            preview = value[:64]

            try:
                text = preview.decode("ascii")

                if text.isprintable():
                    return repr(text)

            except UnicodeDecodeError:
                pass

            suffix = "" if len(value) <= 64 else f" ... ({len(value)} bytes)"

            return "0x" + preview.hex(" ") + suffix

        return str(value)


class ChunkTree(ttk.Treeview):
    def __init__(self, parent: tk.Widget) -> None:
        super().__init__(
            parent,
            show="tree",
        )

        self.cache: dict[str, ChunkNode] = {}
        self.node_order: list[str] = []

    @property
    def chunk_count(self) -> int:
        return len(self.node_order)

    def load[H: ChunkHeader](self, root: ParsedChunk[H]) -> None:
        self.delete(*self.get_children())
        self.cache.clear()
        self.node_order.clear()

        self.insert_chunk(
            "",
            root,
            "Root",
        )

    def insert_chunk[H: ChunkHeader](
        self,
        parent: str,
        chunk: ParsedChunk[H],
        prefix: str,
    ) -> None:
        node = self.insert(
            parent,
            "end",
            text=f"{prefix}: {self.chunk_description(chunk)}",
        )

        self.cache[node] = cast("ChunkNode", chunk)
        self.node_order.append(node)

        for index, child in enumerate(chunk.children):
            self.insert_chunk(
                node,
                child,
                str(index),
            )

    def chunk_description[H: ChunkHeader](
        self,
        chunk: ParsedChunk[H],
    ) -> str:
        header = chunk.header
        marker = marker_text(chunk.generic_header.header_marker)

        if isinstance(header, MhodChunkHeader):
            return f"{marker} type={header.mhod_type} ({type(header).__name__})"

        if isinstance(header, MhsdChunkHeader):
            return (
                f"{marker} dataset_type={header.dataset_type} ({type(header).__name__})"
            )

        return f"{marker} ({type(header).__name__})"

    def iter_search_entries(
        self,
        value: object,
        *,
        path: str,
        field_name: str,
        seen: set[int],
    ) -> Iterator[SearchEntry]:
        value_id = id(value)

        if is_search_container(value):
            if value_id in seen:
                return

            seen.add(value_id)

        type_name = type(value).__name__

        yield SearchEntry(
            path=path,
            field_name=field_name,
            type_name=type_name,
            value="" if is_search_container(value) else search_value_text(value),
        )

        if is_dataclass(value):
            for dataclass_field in cached_fields(cast("Hashable", type(value))):
                child = getattr(
                    value,
                    dataclass_field.name,
                )

                child_path = (
                    f"{path}.{dataclass_field.name}" if path else dataclass_field.name
                )

                yield from self.iter_search_entries(
                    child,
                    path=child_path,
                    field_name=dataclass_field.name,
                    seen=seen,
                )

            return

        if isinstance(value, Mapping):
            mapping = cast("Mapping[object, object]", value)

            for key, child in mapping.items():
                key_text = str(key)

                child_path = f"{path}.{key_text}" if path else key_text

                yield from self.iter_search_entries(
                    child,
                    path=child_path,
                    field_name=key_text,
                    seen=seen,
                )

            return

        if isinstance(value, tuple):
            tuple_items = cast("tuple[object, ...]", value)
            named_fields = named_tuple_field_names(tuple_items)

            if named_fields is not None:
                for index, name in enumerate(named_fields):
                    child = tuple_items[index]

                    child_path = f"{path}.{name}" if path else name

                    yield from self.iter_search_entries(
                        child,
                        path=child_path,
                        field_name=name,
                        seen=seen,
                    )

                return

            for index, child in enumerate(tuple_items):
                name = f"[{index}]"

                yield from self.iter_search_entries(
                    child,
                    path=f"{path}{name}",
                    field_name=name,
                    seen=seen,
                )

            return

        if isinstance(value, list):
            list_items = cast("list[object]", value)

            for index, child in enumerate(list_items):
                name = f"[{index}]"

                yield from self.iter_search_entries(
                    child,
                    path=f"{path}{name}",
                    field_name=name,
                    seen=seen,
                )

            return

        if isinstance(value, (set, frozenset)):
            set_items = cast("set[object] | frozenset[object]", value)

            for index, child in enumerate(set_items):
                name = f"[{index}]"

                yield from self.iter_search_entries(
                    child,
                    path=f"{path}{name}",
                    field_name=name,
                    seen=seen,
                )

    def chunk_search_entries(
        self,
        chunk: ChunkNode,
    ) -> Iterator[SearchEntry]:
        """
        Yield searchable data belonging directly to a chunk.

        Child ParsedChunks are deliberately excluded. Each child is searched
        independently so a parent does not match merely because a descendant
        contains the requested field or value.
        """

        yield SearchEntry(
            path="marker",
            field_name="marker",
            type_name="bytes",
            value=marker_text(
                chunk.generic_header.header_marker,
            ),
        )

        yield SearchEntry(
            path="offset",
            field_name="offset",
            type_name="int",
            value=f"{chunk.offset:#x}",
        )

        seen: set[int] = set()

        yield from self.iter_search_entries(
            chunk.generic_header,
            path="generic_header",
            field_name="generic_header",
            seen=seen,
        )

        yield from self.iter_search_entries(
            chunk.header,
            path="header",
            field_name="header",
            seen=seen,
        )

        if chunk.payload is not None:
            yield from self.iter_search_entries(
                chunk.payload,
                path="payload",
                field_name="payload",
                seen=seen,
            )

    def entry_matches_general_term(
        self,
        entry: SearchEntry,
        term: str,
    ) -> bool:
        return any(
            term in candidate.casefold()
            for candidate in (
                entry.path,
                entry.field_name,
                entry.type_name,
                entry.value,
            )
        )

    def entry_matches_field_term(
        self,
        entry: SearchEntry,
        field_name: str,
        expected_value: str,
    ) -> bool:
        if field_name in {"type", "class"}:
            return entry.type_name.casefold() == expected_value

        entry_field = entry.field_name.casefold()
        entry_path = entry.path.casefold()

        field_matches = (
            entry_field == field_name
            or entry_path == field_name
            or entry_path.endswith(f".{field_name}")
        )

        if not field_matches:
            return False

        return entry.value.casefold() == expected_value

    def chunk_matches(
        self,
        chunk: ChunkNode,
        terms: tuple[SearchTerm, ...],
    ) -> bool:
        entries = tuple(self.chunk_search_entries(chunk))

        for term in terms:
            if term.field_name is None:
                if not any(
                    self.entry_matches_general_term(
                        entry,
                        term.value,
                    )
                    for entry in entries
                ):
                    return False

                continue

            if not any(
                self.entry_matches_field_term(
                    entry,
                    term.field_name,
                    term.value,
                )
                for entry in entries
            ):
                return False

        return True

    def search(
        self,
        query: str,
    ) -> tuple[str, ...]:
        terms = parse_search_query(query)

        if not terms:
            return ()

        matches: list[str] = []

        for node in self.node_order:
            chunk = self.cache[node]

            if self.chunk_matches(
                chunk,
                terms,
            ):
                matches.append(node)

        return tuple(matches)

    def reveal(
        self,
        node: str,
    ) -> None:
        parent = self.parent(node)

        while parent:
            self.item(
                parent,
                open=True,
            )
            parent = self.parent(parent)

        self.selection_set(node)
        self.focus(node)
        self.see(node)


class ChunkBrowser(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        self.title("iPodDB Chunk Browser")
        self.geometry("1400x800")

        self.search_var = tk.StringVar()
        self.search_status_var = tk.StringVar()

        self.search_results: tuple[str, ...] = ()
        self.search_index = -1
        self.active_search_query = ""

        self.build_ui()

        self.bind(
            "<Control-f>",
            self.focus_search,
        )
        self.bind(
            "<Command-f>",
            self.focus_search,
        )
        self.bind(
            "<F3>",
            self.next_match,
        )
        self.bind(
            "<Shift-F3>",
            self.previous_match,
        )

    def build_ui(self) -> None:
        toolbar = ttk.Frame(self)

        toolbar.pack(
            fill="x",
            padx=6,
            pady=6,
        )

        open_button = ttk.Button(
            toolbar,
            text="Open iTunesDB / ArtworkDB",
            command=self.open_file,
        )

        open_button.pack(
            side="left",
        )

        ttk.Separator(
            toolbar,
            orient="vertical",
        ).pack(
            side="left",
            fill="y",
            padx=8,
        )

        ttk.Label(
            toolbar,
            text="Search:",
        ).pack(
            side="left",
        )

        self.search_entry = ttk.Entry(
            toolbar,
            textvariable=self.search_var,
        )

        self.search_entry.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(6, 6),
        )

        self.search_entry.bind(
            "<Return>",
            self.run_search,
        )

        search_button = ttk.Button(
            toolbar,
            text="Search",
            command=self.run_search,
        )

        search_button.pack(
            side="left",
            padx=(0, 4),
        )

        previous_button = ttk.Button(
            toolbar,
            text="Previous",
            command=self.previous_match,
        )

        previous_button.pack(
            side="left",
            padx=(0, 4),
        )

        next_button = ttk.Button(
            toolbar,
            text="Next",
            command=self.next_match,
        )

        next_button.pack(
            side="left",
            padx=(0, 4),
        )

        clear_button = ttk.Button(
            toolbar,
            text="Clear",
            command=self.clear_search,
        )

        clear_button.pack(
            side="left",
        )

        ttk.Label(
            toolbar,
            textvariable=self.search_status_var,
            width=18,
            anchor="e",
        ).pack(
            side="left",
            padx=(8, 0),
        )

        panes = ttk.PanedWindow(
            self,
            orient="horizontal",
        )

        panes.pack(
            fill="both",
            expand=True,
        )

        left = ttk.Frame(panes)
        right = ttk.Frame(panes)

        weighted_panes = cast("_WeightedPanedWindow", panes)
        weighted_panes.add(left, weight=1)
        weighted_panes.add(right, weight=3)

        self.tree = ChunkTree(left)
        self.tree.pack(
            fill="both",
            expand=True,
        )

        self.inspector = ObjectInspector(right)
        self.inspector.pack(
            fill="both",
            expand=True,
        )

        self.tree.bind(
            "<<TreeviewSelect>>",
            self.selected,
        )

    def open_file(self) -> None:
        filename = filedialog.askopenfilename(
            title="Open iPod Database",
            filetypes=(
                ("iPod databases", ("iTunesDB", "ArtworkDB")),
                ("All files", "*"),
            ),
        )

        if not filename:
            return

        try:
            data = Path(filename).read_bytes()
            database = parse_browsable_database(data)
        except (OSError, iPodDBParseError) as error:
            messagebox.showerror(
                title="Cannot open iPod database",
                message=str(error),
                parent=self,
            )
            return

        self.tree.load(
            database.document,
        )

        self.title(f"{database.family.value} Chunk Browser — {Path(filename).name}")

        self.reset_search_state()

        self.search_status_var.set(
            f"{self.tree.chunk_count} chunks",
        )

    def run_search(
        self,
        _event: object | None = None,
    ) -> None:
        query = self.search_var.get().strip()

        if not query:
            self.clear_search()
            return

        try:
            results = self.tree.search(query)
        except ValueError:
            self.search_results = ()
            self.search_index = -1
            self.active_search_query = ""
            self.search_status_var.set("Invalid query")
            return

        self.active_search_query = query
        self.search_results = results

        if not self.search_results:
            self.search_index = -1
            self.search_status_var.set("No matches")
            return

        self.search_index = 0
        self.show_search_result()

    def next_match(
        self,
        _event: object | None = None,
    ) -> None:
        query = self.search_var.get().strip()

        if not query:
            return

        if query != self.active_search_query or not self.search_results:
            self.run_search()

            if not self.search_results:
                return

            return

        self.search_index = (self.search_index + 1) % len(self.search_results)

        self.show_search_result()

    def previous_match(
        self,
        _event: object | None = None,
    ) -> None:
        query = self.search_var.get().strip()

        if not query:
            return

        if query != self.active_search_query or not self.search_results:
            self.run_search()

            if not self.search_results:
                return

            self.search_index = len(self.search_results) - 1
            self.show_search_result()
            return

        self.search_index = (self.search_index - 1) % len(self.search_results)

        self.show_search_result()

    def show_search_result(self) -> None:
        if not self.search_results:
            return

        node = self.search_results[self.search_index]

        self.tree.reveal(node)

        self.search_status_var.set(
            f"{self.search_index + 1}/{len(self.search_results)}",
        )

    def clear_search(self) -> None:
        self.search_var.set("")
        self.reset_search_state()

        if self.tree.chunk_count:
            self.search_status_var.set(
                f"{self.tree.chunk_count} chunks",
            )
        else:
            self.search_status_var.set("")

    def reset_search_state(self) -> None:
        self.search_results = ()
        self.search_index = -1
        self.active_search_query = ""

    def focus_search(
        self,
        _event: object,
    ) -> str:
        self.search_entry.focus_set()
        self.search_entry.selection_range(
            0,
            "end",
        )

        return "break"

    def selected(self, _event: object) -> None:
        selection = self.tree.selection()

        if not selection:
            return

        chunk = self.tree.cache[selection[0]]

        self.inspector.inspect(
            chunk,
        )


def main() -> None:
    ChunkBrowser().mainloop()


if __name__ == "__main__":
    main()
