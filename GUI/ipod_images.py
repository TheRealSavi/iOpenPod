"""
iPod product image resolver.

Maps iPod model families, generations, and colors to official Apple device
icons stored in assets/ipod_images/.  Icons extracted from macOS
AMPDevices.framework — the same images Finder/iTunes use.

Apple's icon filenames use an internal "iPodNN" numbering that corresponds
to Apple's FamilyID system.  The mapping below was confirmed empirically
(iPod Nano 2G → FamilyID 9 → iPod9-*.png, iPod Classic → FamilyID 11 →
iPod11-*.png).

Icon numbering reference:
  iPod1          iPod 1st Gen (2001, scroll wheel)
  iPod2          iPod 2nd Gen (2002, touch wheel) / 3rd Gen (dock connector)
  iPod3          iPod Mini 1st Gen (2004)
  iPod3B         iPod Mini 2nd Gen (2005)
  iPod4          iPod 4th Gen (click wheel) + U2 edition
  iPod5          iPod Photo / 4th Gen Color + U2 edition
  iPod6          iPod Video 5th Gen + U2 edition
  iPod7          iPod Video 5.5th Gen (Enhanced)
  iPod9          iPod Nano 2nd Gen (confirmed FamilyID=9)
  iPod11/11B     iPod Classic (confirmed FamilyID=11)
  iPod12         iPod Nano 3rd Gen
  iPod15         iPod Nano 4th Gen
  iPod16         iPod Nano 5th Gen
  iPod17         iPod Nano 6th Gen
  iPod18/18A     iPod Nano 7th Gen (2012 / 2015 refresh)
  SidebariPod*   Sidebar-only icons (64×64) for Nano 1G and Shuffles
"""

from functools import lru_cache
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_IMAGE_DIR = _PROJECT_ROOT / "assets" / "ipod_images"

# ---------------------------------------------------------------------------
# Colour-specific image map
# Key: (model_family_lower, generation_lower, colour_lower) → filename
# ---------------------------------------------------------------------------
_COLOR_MAP: dict[tuple[str, str, str], str] = {
    # ── iPod Classic ──────────────────────────────────────────────────
    ("ipod classic", "1st gen", "silver"): "iPod11-Silver.png",
    ("ipod classic", "1st gen", "black"): "iPod11-Black.png",
    ("ipod classic", "2nd gen", "silver"): "iPod11-Silver.png",
    ("ipod classic", "2nd gen", "black"): "iPod11-Black.png",
    ("ipod classic", "3rd gen", "silver"): "iPod11-Silver.png",
    ("ipod classic", "3rd gen", "black"): "iPod11B-Black.png",

    # ── iPod (full-size 1G–4G) ────────────────────────────────────────
    ("ipod", "1st gen", "white"): "iPod1.png",
    ("ipod", "2nd gen", "white"): "iPod2.png",
    ("ipod", "3rd gen", "white"): "iPod2.png",
    ("ipod", "4th gen", "white"): "iPod4-White.png",

    # ── iPod U2 ───────────────────────────────────────────────────────
    ("ipod u2", "4th gen", "black"): "iPod4-BlackRed.png",

    # ── iPod Photo ────────────────────────────────────────────────────
    ("ipod photo", "4th gen", "white"): "iPod5-White.png",
    ("ipod photo", "4th gen (photo)", "white"): "iPod5-White.png",

    # ── iPod Video 5th Gen ────────────────────────────────────────────
    ("ipod video", "5th gen", "white"): "iPod6-White.png",
    ("ipod video", "5th gen", "black"): "iPod6-Black.png",
    ("ipod video u2", "5th gen", "black"): "iPod6-BlackRed.png",

    # ── iPod Video 5.5th Gen ──────────────────────────────────────────
    ("ipod video", "5.5th gen", "white"): "iPod7-White.png",
    ("ipod video", "5.5th gen", "black"): "iPod7-Black.png",
    ("ipod video u2", "5.5th gen", "black"): "iPod6-BlackRed.png",

    # ── iPod Mini 1st Gen (Blue, Gold, Green, Pink, Silver) ───────────
    ("ipod mini", "1st gen", "silver"): "iPod3-Silver.png",
    ("ipod mini", "1st gen", "blue"): "iPod3-Blue.png",
    ("ipod mini", "1st gen", "gold"): "iPod3-Gold.png",
    ("ipod mini", "1st gen", "green"): "iPod3-Green.png",
    ("ipod mini", "1st gen", "pink"): "iPod3-Pink.png",

    # ── iPod Mini 2nd Gen (Blue, Green, Pink, Silver) ─────────────────
    ("ipod mini", "2nd gen", "silver"): "iPod3-Silver.png",  # reuse 1G silver
    ("ipod mini", "2nd gen", "blue"): "iPod3B-Blue.png",
    ("ipod mini", "2nd gen", "green"): "iPod3B-Green.png",
    ("ipod mini", "2nd gen", "pink"): "iPod3B-Pink.png",

    # ── iPod Nano 1st Gen (Black, White — sidebar icon only) ──────────
    ("ipod nano", "1st gen", "white"): "SidebariPodNano1.png",
    ("ipod nano", "1st gen", "black"): "SidebariPodNano1.png",

    # ── iPod Nano 2nd Gen (Black, Blue, Green, Pink, Red, Silver) ─────
    ("ipod nano", "2nd gen", "silver"): "iPod9-Silver.png",
    ("ipod nano", "2nd gen", "black"): "iPod9-Black.png",
    ("ipod nano", "2nd gen", "blue"): "iPod9-Blue.png",
    ("ipod nano", "2nd gen", "green"): "iPod9-Green.png",
    ("ipod nano", "2nd gen", "pink"): "iPod9-Pink.png",
    ("ipod nano", "2nd gen", "red"): "iPod9-Red.png",

    # ── iPod Nano 3rd Gen (Black, Blue, Green, Pink, Red, Silver) ─────
    ("ipod nano", "3rd gen", "silver"): "iPod12-Silver.png",
    ("ipod nano", "3rd gen", "black"): "iPod12-Black.png",
    ("ipod nano", "3rd gen", "blue"): "iPod12-Blue.png",
    ("ipod nano", "3rd gen", "green"): "iPod12-Green.png",
    ("ipod nano", "3rd gen", "pink"): "iPod12-Pink.png",
    ("ipod nano", "3rd gen", "red"): "iPod12-Red.png",

    # ── iPod Nano 4th Gen (9 colours) ─────────────────────────────────
    ("ipod nano", "4th gen", "silver"): "iPod15-Silver.png",
    ("ipod nano", "4th gen", "black"): "iPod15-Black.png",
    ("ipod nano", "4th gen", "blue"): "iPod15-Blue.png",
    ("ipod nano", "4th gen", "green"): "iPod15-Green.png",
    ("ipod nano", "4th gen", "orange"): "iPod15-Orange.png",
    ("ipod nano", "4th gen", "pink"): "iPod15-Pink.png",
    ("ipod nano", "4th gen", "purple"): "iPod15-Purple.png",
    ("ipod nano", "4th gen", "red"): "iPod15-Red.png",
    ("ipod nano", "4th gen", "yellow"): "iPod15-Yellow.png",

    # ── iPod Nano 5th Gen (9 colours) ─────────────────────────────────
    ("ipod nano", "5th gen", "silver"): "iPod16-Silver.png",
    ("ipod nano", "5th gen", "black"): "iPod16-Black.png",
    ("ipod nano", "5th gen", "blue"): "iPod16-Blue.png",
    ("ipod nano", "5th gen", "green"): "iPod16-Green.png",
    ("ipod nano", "5th gen", "orange"): "iPod16-Orange.png",
    ("ipod nano", "5th gen", "pink"): "iPod16-Pink.png",
    ("ipod nano", "5th gen", "purple"): "iPod16-Purple.png",
    ("ipod nano", "5th gen", "red"): "iPod16-Red.png",
    ("ipod nano", "5th gen", "yellow"): "iPod16-Yellow.png",

    # ── iPod Nano 6th Gen (7 colours) ─────────────────────────────────
    ("ipod nano", "6th gen", "silver"): "iPod17-Silver.png",
    ("ipod nano", "6th gen", "graphite"): "iPod17-DarkGray.png",
    ("ipod nano", "6th gen", "blue"): "iPod17-Blue.png",
    ("ipod nano", "6th gen", "green"): "iPod17-Green.png",
    ("ipod nano", "6th gen", "orange"): "iPod17-Orange.png",
    ("ipod nano", "6th gen", "pink"): "iPod17-Pink.png",
    ("ipod nano", "6th gen", "red"): "iPod17-Red.png",

    # ── iPod Nano 7th Gen — original 2012 release ─────────────────────
    ("ipod nano", "7th gen", "silver"): "iPod18-Silver.png",
    ("ipod nano", "7th gen", "slate"): "iPod18-DarkGray.png",
    ("ipod nano", "7th gen", "space gray"): "iPod18-SpaceGray.png",
    ("ipod nano", "7th gen", "blue"): "iPod18-Blue.png",
    ("ipod nano", "7th gen", "green"): "iPod18-Green.png",
    ("ipod nano", "7th gen", "pink"): "iPod18-Pink.png",
    ("ipod nano", "7th gen", "purple"): "iPod18-Purple.png",
    ("ipod nano", "7th gen", "red"): "iPod18-Red.png",
    ("ipod nano", "7th gen", "yellow"): "iPod18-Yellow.png",
    # 2015 refresh colours
    ("ipod nano", "7th gen", "gold"): "iPod18A-Gold.png",

    # ── iPod Shuffle (sidebar icons only — 64×64) ────────────────────
    ("ipod shuffle", "1st gen", "white"): "SidebariPodShuffle1.png",
    ("ipod shuffle", "2nd gen", "silver"): "SidebariPodShuffle2.png",
    ("ipod shuffle", "3rd gen", "silver"): "SidebariPodShuffle3.png",
    ("ipod shuffle", "4th gen", "silver"): "SidebariPodShuffle4.png",
}

# ---------------------------------------------------------------------------
# Default image per (family, generation) — used when colour is unknown.
# Uses the most recognisable variant (usually Silver or White).
# ---------------------------------------------------------------------------
_DEFAULT_MAP: dict[tuple[str, str], str] = {
    # iPod (full-size)
    ("ipod", "1st gen"): "iPod1.png",
    ("ipod", "2nd gen"): "iPod2.png",
    ("ipod", "3rd gen"): "iPod2.png",
    ("ipod", "4th gen"): "iPod4-White.png",
    ("ipod", "4th gen (photo)"): "iPod5-White.png",
    ("ipod", "5th gen"): "iPod6-White.png",
    ("ipod", "5th gen enhanced"): "iPod7-White.png",

    # iPod U2
    ("ipod u2", "4th gen"): "iPod4-BlackRed.png",

    # iPod Photo
    ("ipod photo", "4th gen"): "iPod5-White.png",

    # iPod Video
    ("ipod video", "5th gen"): "iPod6-White.png",
    ("ipod video", "5.5th gen"): "iPod7-White.png",
    ("ipod video u2", "5th gen"): "iPod6-BlackRed.png",
    ("ipod video u2", "5.5th gen"): "iPod6-BlackRed.png",

    # iPod Classic
    ("ipod classic", "1st gen"): "iPod11-Silver.png",
    ("ipod classic", "2nd gen"): "iPod11-Silver.png",
    ("ipod classic", "3rd gen"): "iPod11-Silver.png",

    # iPod Mini
    ("ipod mini", "1st gen"): "iPod3-Silver.png",
    ("ipod mini", "2nd gen"): "iPod3B-Blue.png",

    # iPod Nano
    ("ipod nano", "1st gen"): "SidebariPodNano1.png",
    ("ipod nano", "2nd gen"): "iPod9-Silver.png",
    ("ipod nano", "3rd gen"): "iPod12-Silver.png",
    ("ipod nano", "4th gen"): "iPod15-Silver.png",
    ("ipod nano", "5th gen"): "iPod16-Silver.png",
    ("ipod nano", "6th gen"): "iPod17-Silver.png",
    ("ipod nano", "7th gen"): "iPod18-Silver.png",

    # iPod Shuffle
    ("ipod shuffle", "1st gen"): "SidebariPodShuffle1.png",
    ("ipod shuffle", "2nd gen"): "SidebariPodShuffle2.png",
    ("ipod shuffle", "3rd gen"): "SidebariPodShuffle3.png",
    ("ipod shuffle", "4th gen"): "SidebariPodShuffle4.png",
}

# ---------------------------------------------------------------------------
# Family-level fallback (when generation is unknown or doesn't match)
# ---------------------------------------------------------------------------
_FAMILY_FALLBACK: dict[str, str] = {
    "ipod": "iPod4-White.png",
    "ipod u2": "iPod4-BlackRed.png",
    "ipod photo": "iPod5-White.png",
    "ipod video": "iPod7-White.png",
    "ipod video u2": "iPod6-BlackRed.png",
    "ipod classic": "iPod11-Silver.png",
    "ipod mini": "iPod3-Silver.png",
    "ipod nano": "iPod15-Silver.png",
    "ipod shuffle": "SidebariPodShuffle4.png",
}


def _resolve_filename(
    family: str,
    generation: str,
    color: str = "",
) -> str | None:
    """Resolve an image filename through the three-tier lookup.

    1. Exact (family, generation, color)
    2. Default (family, generation)
    3. Family-level fallback
    """
    fam = family.lower()
    gen = generation.lower()
    col = color.lower().strip()

    # 1. Colour-specific
    if col:
        filename = _COLOR_MAP.get((fam, gen, col))
        if filename:
            return filename

    # 2. Default for this (family, generation)
    filename = _DEFAULT_MAP.get((fam, gen))
    if filename:
        return filename

    # 3. Family-level fallback
    return _FAMILY_FALLBACK.get(fam)


@lru_cache(maxsize=128)
def get_ipod_image(
    family: str,
    generation: str,
    size: int = 80,
    color: str = "",
) -> QPixmap | None:
    """
    Return a scaled QPixmap of the iPod product image.

    Lookup priority:
      1. Exact (family, generation, color) match
      2. Default (family, generation) match (silver/white representative)
      3. Family-level fallback
      4. None

    Args:
        family:     Product line, e.g. "iPod Classic", "iPod Nano"
        generation: e.g. "2nd Gen", "5.5th Gen"
        size:       Maximum dimension (keeps aspect ratio)
        color:      e.g. "Black", "Silver", "Blue" (optional)

    Returns:
        QPixmap scaled to fit within size×size, or None if no image found.
    """
    filename = _resolve_filename(family, generation, color)
    if not filename:
        return None

    path = _IMAGE_DIR / filename
    if not path.exists():
        return None

    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return None

    return pixmap.scaled(
        size, size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def get_ipod_image_path(
    family: str,
    generation: str,
    color: str = "",
) -> str | None:
    """
    Return the filesystem path to the iPod product image, or None.

    Useful when you need the path rather than a QPixmap (e.g. for QSS).
    """
    filename = _resolve_filename(family, generation, color)
    if not filename:
        return None
    path = _IMAGE_DIR / filename
    return str(path) if path.exists() else None
