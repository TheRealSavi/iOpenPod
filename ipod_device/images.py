"""iPod product image mapping and accent color extraction.

Maps iPod model families, generations, and colors to official Apple device
icons stored in assets/ipod_images/.  Also maps each icon to an (R,G,B)
accent color for the "Match iPod" theme setting.
"""

from .models import IPOD_MODELS, canonicalize_model_identity

# Key: (model_family_lower, generation_lower, color_lower) → filename
COLOR_MAP: dict[tuple[str, str, str], str] = {
    # ── iPod (1G–4G mono) ───────────────────────────────────
    ("ipod", "1st gen", "white"): "iPod1.png",
    ("ipod", "2nd gen", "white"): "iPod1.png",
    ("ipod", "3rd gen", "white"): "iPod2.png",
    ("ipod", "4th gen (mono)", "white"): "iPod4-White.png",
    ("ipod", "4th gen (mono)", "u2"): "iPod4-BlackRed.png",

    # ── iPod 4G photo/color ─────────────────────────────────
    ("ipod", "4th gen (photo)", "white"): "iPod5-White.png",
    ("ipod", "4th gen (color)", "white"): "iPod5-White.png",
    ("ipod", "4th gen (color)", "u2"): "iPod5-BlackRed.png",

    # ── iPod 5th Gen / 5.5th Gen ───────────────────────────
    ("ipod", "5th gen", "white"): "iPod6-White.png",
    ("ipod", "5th gen", "black"): "iPod6-Black.png",
    ("ipod", "5th gen", "u2"): "iPod6-BlackRed.png",
    ("ipod", "5.5th gen", "white"): "iPod6-White.png",
    ("ipod", "5.5th gen", "black"): "iPod6-Black.png",
    ("ipod", "5.5th gen", "u2"): "iPod6-BlackRed.png",

    # ── iPod Classic (6th–7th Gen) ─────────────────────────
    ("ipod classic", "6th gen", "silver"): "iPod11-Silver.png",
    ("ipod classic", "6th gen", "black"): "iPod11-Black.png",
    ("ipod classic", "6.5th gen", "silver"): "iPod11-Silver.png",
    ("ipod classic", "6.5th gen", "black"): "iPod11B-Black.png",
    ("ipod classic", "7th gen", "silver"): "iPod11-Silver.png",
    ("ipod classic", "7th gen", "black"): "iPod11B-Black.png",

    # ── iPod Mini 1st Gen ────────────
    ("ipod mini", "1st gen", "silver"): "iPod3-Silver.png",
    ("ipod mini", "1st gen", "blue"): "iPod3-Blue.png",
    ("ipod mini", "1st gen", "gold"): "iPod3-Gold.png",
    ("ipod mini", "1st gen", "green"): "iPod3-Green.png",
    ("ipod mini", "1st gen", "pink"): "iPod3-Pink.png",

    # ── iPod Mini 2nd Gen ───
    ("ipod mini", "2nd gen", "silver"): "iPod3-Silver.png",
    ("ipod mini", "2nd gen", "blue"): "iPod3B-Blue.png",
    ("ipod mini", "2nd gen", "green"): "iPod3B-Green.png",
    ("ipod mini", "2nd gen", "pink"): "iPod3B-Pink.png",

    # ── iPod Nano 1st Gen ──────────────────────────────
    ("ipod nano", "1st gen", "white"): "iPod7-White.png",
    ("ipod nano", "1st gen", "black"): "iPod7-Black.png",

    # ── iPod Nano 2nd Gen ─────
    ("ipod nano", "2nd gen", "silver"): "iPod9-Silver.png",
    ("ipod nano", "2nd gen", "black"): "iPod9-Black.png",
    ("ipod nano", "2nd gen", "blue"): "iPod9-Blue.png",
    ("ipod nano", "2nd gen", "green"): "iPod9-Green.png",
    ("ipod nano", "2nd gen", "pink"): "iPod9-Pink.png",
    ("ipod nano", "2nd gen", "red"): "iPod9-Red.png",

    # ── iPod Nano 3rd Gen ─────
    ("ipod nano", "3rd gen", "silver"): "iPod12-Silver.png",
    ("ipod nano", "3rd gen", "black"): "iPod12-Black.png",
    ("ipod nano", "3rd gen", "blue"): "iPod12-Blue.png",
    ("ipod nano", "3rd gen", "green"): "iPod12-Green.png",
    ("ipod nano", "3rd gen", "pink"): "iPod12-Pink.png",
    ("ipod nano", "3rd gen", "red"): "iPod12-Red.png",

    # ── iPod Nano 4th Gen ─────────────────────────────────
    ("ipod nano", "4th gen", "silver"): "iPod15-Silver.png",
    ("ipod nano", "4th gen", "black"): "iPod15-Black.png",
    ("ipod nano", "4th gen", "blue"): "iPod15-Blue.png",
    ("ipod nano", "4th gen", "green"): "iPod15-Green.png",
    ("ipod nano", "4th gen", "orange"): "iPod15-Orange.png",
    ("ipod nano", "4th gen", "pink"): "iPod15-Pink.png",
    ("ipod nano", "4th gen", "purple"): "iPod15-Purple.png",
    ("ipod nano", "4th gen", "red"): "iPod15-Red.png",
    ("ipod nano", "4th gen", "yellow"): "iPod15-Yellow.png",

    # ── iPod Nano 5th Gen ─────────────────────────────────
    ("ipod nano", "5th gen", "silver"): "iPod16-Silver.png",
    ("ipod nano", "5th gen", "black"): "iPod16-Black.png",
    ("ipod nano", "5th gen", "blue"): "iPod16-Blue.png",
    ("ipod nano", "5th gen", "green"): "iPod16-Green.png",
    ("ipod nano", "5th gen", "orange"): "iPod16-Orange.png",
    ("ipod nano", "5th gen", "pink"): "iPod16-Pink.png",
    ("ipod nano", "5th gen", "purple"): "iPod16-Purple.png",
    ("ipod nano", "5th gen", "red"): "iPod16-Red.png",
    ("ipod nano", "5th gen", "yellow"): "iPod16-Yellow.png",

    # ── iPod Nano 6th Gen ─────────────────────────────────
    ("ipod nano", "6th gen", "silver"): "iPod17-Silver.png",
    ("ipod nano", "6th gen", "graphite"): "iPod17-DarkGray.png",
    ("ipod nano", "6th gen", "blue"): "iPod17-Blue.png",
    ("ipod nano", "6th gen", "green"): "iPod17-Green.png",
    ("ipod nano", "6th gen", "orange"): "iPod17-Orange.png",
    ("ipod nano", "6th gen", "pink"): "iPod17-Pink.png",
    ("ipod nano", "6th gen", "red"): "iPod17-Red.png",

    # ── iPod Nano 7th Gen ─────────────────────────────────────────────
    ("ipod nano", "7th gen", "silver"): "iPod18A-Silver.png",
    ("ipod nano", "7th gen", "space gray"): "iPod18A-SpaceGray.png",
    ("ipod nano", "7th gen", "blue"): "iPod18A-Blue.png",
    ("ipod nano", "7th gen", "pink"): "iPod18A-Pink.png",
    ("ipod nano", "7th gen", "red"): "iPod18A-Red.png",
    ("ipod nano", "7th gen", "gold"): "iPod18A-Gold.png",
    ("ipod nano", "7th gen", "slate"): "iPod18-DarkGray.png",
    ("ipod nano", "7th gen", "green"): "iPod18-Green.png",
    ("ipod nano", "7th gen", "purple"): "iPod18-Purple.png",
    ("ipod nano", "7th gen", "yellow"): "iPod18-Yellow.png",

    # ── iPod Shuffle 1st Gen ───────────────────────
    ("ipod shuffle", "1st gen", "white"): "iPod128.png",

    # ── iPod Shuffle 2nd Gen ──────────────────────────────────────────
    ("ipod shuffle", "2nd gen", "silver"): "iPod130-Silver.png",
    ("ipod shuffle", "2nd gen", "blue"): "iPod130-Blue.png",
    ("ipod shuffle", "2nd gen", "green"): "iPod130-Green.png",
    ("ipod shuffle", "2nd gen", "pink"): "iPod130-Pink.png",
    ("ipod shuffle", "2nd gen", "orange"): "iPod130-Orange.png",
    ("ipod shuffle", "2nd gen", "purple"): "iPod130C-Purple.png",
    ("ipod shuffle", "2nd gen", "red"): "iPod130C-Red.png",
    ("ipod shuffle", "2nd gen", "gold"): "iPod130F-Gold.png",

    # ── iPod Shuffle 3rd Gen ───────────────────────────────────
    ("ipod shuffle", "3rd gen", "silver"): "iPod132-Silver.png",
    ("ipod shuffle", "3rd gen", "black"): "iPod132-DarkGray.png",
    ("ipod shuffle", "3rd gen", "blue"): "iPod132-Blue.png",
    ("ipod shuffle", "3rd gen", "green"): "iPod132-Green.png",
    ("ipod shuffle", "3rd gen", "pink"): "iPod132-Pink.png",
    ("ipod shuffle", "3rd gen", "stainless steel"): "iPod132B-Silver.png",

    # ── iPod Shuffle 4th Gen (2010–2017) ───────────────────────────────
    ("ipod shuffle", "4th gen", "silver"): "iPod133D-Silver.png",
    ("ipod shuffle", "4th gen", "space gray"): "iPod133D-SpaceGray.png",
    ("ipod shuffle", "4th gen", "blue"): "iPod133D-Blue.png",
    ("ipod shuffle", "4th gen", "pink"): "iPod133D-Pink.png",
    ("ipod shuffle", "4th gen", "red"): "iPod133D-Red.png",
    ("ipod shuffle", "4th gen", "gold"): "iPod133D-Gold.png",
    ("ipod shuffle", "4th gen", "slate"): "iPod133B-DarkGray.png",
    ("ipod shuffle", "4th gen", "green"): "iPod133B-Green.png",
    ("ipod shuffle", "4th gen", "purple"): "iPod133B-Purple.png",
    ("ipod shuffle", "4th gen", "yellow"): "iPod133B-Yellow.png",
    ("ipod shuffle", "4th gen", "orange"): "iPod133-Orange.png",
}

MODEL_IMAGE: dict[str, str] = {
    # ── iPod Nano 7th Gen (2012 original → iPod18) ─────────────────────
    'MD475': 'iPod18-Pink.png',
    'MD476': 'iPod18-Yellow.png',
    'MD477': 'iPod18-Blue.png',
    'MD478': 'iPod18-Green.png',
    'MD479': 'iPod18-Purple.png',
    'MD480': 'iPod18-Silver.png',
    'MD481': 'iPod18-DarkGray.png',
    'MD744': 'iPod18-Red.png',
    'ME971': 'iPod18-SpaceGray.png',
    # ── iPod Nano 7th Gen (2015 refresh → iPod18A) ─────────────────────
    'MKMV2': 'iPod18A-Pink.png',
    'MKMX2': 'iPod18A-Gold.png',
    'MKN02': 'iPod18A-Blue.png',
    'MKN22': 'iPod18A-Silver.png',
    'MKN52': 'iPod18A-SpaceGray.png',
    'MKN72': 'iPod18A-Red.png',
    # ── iPod Shuffle 2nd Gen — Sept 2007 Rev A (iPod130C) ─────────────
    'MB227': 'iPod130C-Blue.png',
    'MB228': 'iPod130C-Blue.png',
    'MB229': 'iPod130C-Green.png',
    'MB520': 'iPod130C-Blue.png',
    'MB522': 'iPod130C-Green.png',
    # ── iPod Shuffle 2nd Gen — 2008 Rev B (iPod130F) ──────────────────
    'MB811': 'iPod130F-Pink.png',
    'MB813': 'iPod130F-Blue.png',
    'MB815': 'iPod130F-Green.png',
    'MB817': 'iPod130F-Red.png',
    'MB681': 'iPod130F-Pink.png',
    'MB683': 'iPod130F-Blue.png',
    'MB685': 'iPod130F-Green.png',
    'MB779': 'iPod130F-Red.png',
    # ── iPod Shuffle 4th Gen — 2010 original (iPod133) ────────────────
    'MC584': 'iPod133-Silver.png',
    'MC585': 'iPod133-Pink.png',
    'MC750': 'iPod133-Green.png',
    'MC751': 'iPod133-Blue.png',
    # ── iPod Shuffle 4th Gen — Late 2012 Rev A (iPod133B) ─────────────
    'MD773': 'iPod133B-Pink.png',
    'MD775': 'iPod133B-Blue.png',
    'MD778': 'iPod133B-Silver.png',
    'MD780': 'iPod133B-Red.png',
    'ME949': 'iPod133B-SpaceGray.png',
}

FAMILY_FALLBACK: dict[str, str] = {
    "ipod": "iPod4-White.png",
    "ipod classic": "iPod11-Silver.png",
    "ipod mini": "iPod3-Silver.png",
    "ipod nano": "iPod15-Silver.png",
    "ipod shuffle": "iPod133D-Silver.png",
}

GENERIC_IMAGE = "iPodGeneric.png"


# ── Image → accent color (R, G, B) ───────────────────────────────────────────
# Maps image filename (case-insensitive, without extension) to the dominant
# body color of that iPod model.  Used by the "Match iPod" accent color
# setting.  White/silver models use a generic silver; black/gray use a
# generic dark gray; colorful models use their actual body tint.
_SILVER = (223, 224, 223)
_GRAY = (44, 44, 49)

IMAGE_COLORS: dict[str, tuple[int, int, int]] = {
    # ── iPod full-size / Classic ──────────────────────────────────────
    "ipod1": _SILVER,
    "ipod2": _SILVER,
    "ipod4-white": _SILVER,
    "ipod4-blackred": (163, 36, 24),
    "ipod5-white": _SILVER,
    "ipod5-blackred": (163, 36, 24),
    "ipod6-white": _SILVER,
    "ipod6-black": _GRAY,
    "ipod6-blackred": (233, 51, 35),
    "ipod11-silver": _SILVER,
    "ipod11-black": _GRAY,
    "ipod11b-black": _GRAY,
    # ── iPod Mini 1st Gen ─────────────────────────────────────────────
    "ipod3-silver": _SILVER,
    "ipod3-blue": (137, 178, 204),
    "ipod3-gold": (217, 201, 140),
    "ipod3-green": (196, 208, 139),
    "ipod3-pink": (216, 173, 201),
    # ── iPod Mini 2nd Gen ─────────────────────────────────────────────
    "ipod3b-blue": (121, 184, 229),
    "ipod3b-green": (211, 230, 120),
    "ipod3b-pink": (225, 156, 203),
    # ── iPod Nano 1st Gen ─────────────────────────────────────────────
    "ipod7-white": _SILVER,
    "ipod7-black": _GRAY,
    # ── iPod Nano 2nd Gen ─────────────────────────────────────────────
    "ipod9-silver": _SILVER,
    "ipod9-black": _GRAY,
    "ipod9-blue": (94, 194, 210),
    "ipod9-green": (172, 199, 84),
    "ipod9-pink": (209, 61, 139),
    "ipod9-red": (206, 67, 66),
    # ── iPod Nano 3rd Gen ─────────────────────────────────────────────
    "ipod12-silver": _SILVER,
    "ipod12-black": _GRAY,
    "ipod12-blue": (206, 67, 66),
    "ipod12-green": (170, 220, 168),
    "ipod12-pink": (200, 80, 146),
    "ipod12-red": (154, 63, 81),
    # ── iPod Nano 4th Gen ─────────────────────────────────────────────
    "ipod15-silver": _SILVER,
    "ipod15-black": _GRAY,
    "ipod15-blue": (62, 127, 180),
    "ipod15-green": (131, 173, 68),
    "ipod15-orange": (208, 131, 57),
    "ipod15-pink": (227, 67, 133),
    "ipod15-purple": (126, 45, 199),
    "ipod15-red": (209, 62, 66),
    "ipod15-yellow": (239, 230, 109),
    # ── iPod Nano 5th Gen ─────────────────────────────────────────────
    "ipod16-silver": _SILVER,
    "ipod16-black": _GRAY,
    "ipod16-blue": (26, 67, 145),
    "ipod16-green": (52, 119, 61),
    "ipod16-orange": (215, 102, 43),
    "ipod16-pink": (217, 49, 103),
    "ipod16-purple": (65, 9, 127),
    "ipod16-red": (146, 28, 45),
    "ipod16-yellow": (236, 209, 78),
    # ── iPod Nano 6th Gen ─────────────────────────────────────────────
    "ipod17-silver": _SILVER,
    "ipod17-darkgray": _GRAY,
    "ipod17-blue": (105, 128, 168),
    "ipod17-green": (135, 151, 69),
    "ipod17-orange": (178, 131, 57),
    "ipod17-pink": (182, 91, 125),
    "ipod17-red": (186, 50, 48),
    # ── iPod Nano 7th Gen (2012 iPod18) ───────────────────────────────
    "ipod18-silver": _SILVER,
    "ipod18-darkgray": _GRAY,
    "ipod18-blue": (91, 187, 212),
    "ipod18-green": (146, 224, 163),
    "ipod18-pink": (222, 132, 128),
    "ipod18-purple": (222, 152, 208),
    "ipod18-red": (216, 68, 61),
    "ipod18-yellow": (217, 218, 91),
    "ipod18-spacegray": _GRAY,
    # ── iPod Nano 7th Gen (2015 iPod18A) ──────────────────────────────
    "ipod18a-silver": _SILVER,
    "ipod18a-spacegray": _GRAY,
    "ipod18a-blue": (109, 165, 229),
    "ipod18a-gold": (216, 204, 185),
    "ipod18a-pink": (236, 115, 167),
    "ipod18a-red": (232, 105, 97),
    # ── iPod Shuffle 1st Gen ──────────────────────────────────────────
    "ipod128": _SILVER,
    # ── iPod Shuffle 2nd Gen (iPod130) ────────────────────────────────
    "ipod130-silver": _SILVER,
    "ipod130-blue": (81, 169, 195),
    "ipod130-green": (165, 198, 75),
    "ipod130-orange": (230, 107, 44),
    "ipod130-pink": (198, 52, 129),
    # ── iPod Shuffle 2nd Gen Rev A (iPod130C) ─────────────────────────
    "ipod130c-blue": (152, 205, 206),
    "ipod130c-green": (167, 217, 164),
    "ipod130c-purple": (131, 131, 201),
    "ipod130c-red": (150, 59, 77),
    # ── iPod Shuffle 2nd Gen Rev B (iPod130F) ─────────────────────────
    "ipod130f-blue": (50, 110, 179),
    "ipod130f-gold": (208, 189, 129),
    "ipod130f-green": (128, 178, 63),
    "ipod130f-pink": (205, 58, 115),
    "ipod130f-red": (179, 42, 40),
    # ── iPod Shuffle 3rd Gen (iPod132) ────────────────────────────────
    "ipod132-silver": _SILVER,
    "ipod132-darkgray": _GRAY,
    "ipod132-blue": (73, 156, 177),
    "ipod132-green": (147, 189, 77),
    "ipod132-pink": (204, 75, 117),
    "ipod132b-silver": _SILVER,
    # ── iPod Shuffle 4th Gen (2010 iPod133) ───────────────────────────
    "ipod133-silver": _SILVER,
    "ipod133-blue": (139, 175, 212),
    "ipod133-green": (181, 221, 105),
    "ipod133-orange": (224, 186, 109),
    "ipod133-pink": (220, 134, 179),
    # ── iPod Shuffle 4th Gen (2012 iPod133B) ──────────────────────────
    "ipod133b-silver": _SILVER,
    "ipod133b-darkgray": _GRAY,
    "ipod133b-blue": (89, 194, 217),
    "ipod133b-green": (146, 219, 162),
    "ipod133b-pink": (219, 122, 118),
    "ipod133b-purple": (212, 143, 199),
    "ipod133b-red": (216, 69, 62),
    "ipod133b-yellow": (213, 213, 89),
    # ── iPod Shuffle 4th Gen (2015 iPod133D) ──────────────────────────
    "ipod133d-silver": _SILVER,
    "ipod133d-spacegray": _GRAY,
    "ipod133d-blue": (67, 129, 202),
    "ipod133d-gold": (244, 233, 215),
    "ipod133d-pink": (237, 115, 167),
    "ipod133d-red": (223, 85, 76),
}


def color_for_image(image_filename: str) -> tuple[int, int, int] | None:
    """Return the (R, G, B) accent color for an iPod image filename.

    Returns None if the image is not in the mapping (e.g. iPodGeneric).
    """
    key = image_filename.rsplit(".", 1)[0].lower()
    return IMAGE_COLORS.get(key)


_DEFAULT_COLOR_PREFERENCE = ("silver", "white")


def resolve_image_filename(
    family: str,
    generation: str,
    color: str = "",
) -> str:
    """Resolve an image filename through a tiered lookup.

    1. Exact (family, generation, color)
    2. Inferred default — try "silver" then "white" for (family, generation)
    3. Family-level fallback
    4. ``iPodGeneric.png``
    """
    family, generation, color = canonicalize_model_identity(
        family,
        generation,
        color=color,
    )
    fam = family.lower()
    gen = generation.lower()
    col = color.lower().strip()

    if col:
        filename = COLOR_MAP.get((fam, gen, col))
        if filename:
            return filename

    for default_col in _DEFAULT_COLOR_PREFERENCE:
        filename = COLOR_MAP.get((fam, gen, default_col))
        if filename:
            return filename

    return FAMILY_FALLBACK.get(fam, GENERIC_IMAGE)


def image_for_model(model_number: str) -> str:
    """Return the exact image filename for a known model number."""
    override = MODEL_IMAGE.get(model_number)
    if override:
        return override

    info = IPOD_MODELS.get(model_number)
    if info:
        return resolve_image_filename(info[0], info[1], info[3])

    return GENERIC_IMAGE
