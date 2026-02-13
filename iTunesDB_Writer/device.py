"""
iPod device detection and identification.
Based on libgpod's itdb_device.c.

This module handles:
- Reading SysInfo file for device identification
- Detecting which checksum type a device requires
- Getting FireWire GUID for hash computation
"""

import os
import re
from enum import IntEnum
from typing import Optional


class ChecksumType(IntEnum):
    """Checksum types for different iPod generations."""
    NONE = 0           # Pre-2007 iPods: no checksum needed
    HASH58 = 1         # iPod Nano 3G
    HASH72 = 2         # iPod Classic (all), Nano 4G/5G
    UNSUPPORTED = 98   # iPod Nano 6G/7G (HASHAB - not reverse-engineered)
    UNKNOWN = 99       # Unknown device


# Device model patterns and their checksum requirements
# Based on libgpod itdb_device.c itdb_device_get_checksum_type()
#
# HASH58: Nano 3G, Nano 4G, Classic 2G*, Classic 3G*
# HASH72: Nano 5G, Classic 1G (and iPhones/iPod Touches - not supported here)
# HASHAB: Nano 6G/7G - UNSUPPORTED (never reverse-engineered)
#
# *Note: "Classic 2G/3G" in libgpod refers to the 6.5G/7G iPod Video variants,
# NOT the iPod Classic product line. The actual "iPod Classic" (released 2007)
# uses HASH72 according to multiple sources including Clickwheel library.
# However, libgpod's model detection may vary. When in doubt, check HashInfo existence.

DEVICE_CHECKSUMS = {
    # iPod Classic - HASH58 (per libgpod itdb_device.c: CLASSIC_1/2/3 → HASH58)
    # The iPod Classic firmware checks hash58 (scheme=1). iTunes also writes hash72.
    'MB029': ChecksumType.HASH58,  # Classic 1G 80GB (Sept 2007)
    'MB147': ChecksumType.HASH58,  # Classic 1G 160GB (Sept 2007)
    'MB562': ChecksumType.HASH58,  # Classic 2G 120GB
    'MB565': ChecksumType.HASH58,  # Classic 2G 120GB
    'MC293': ChecksumType.HASH58,  # Classic 3G 160GB (Sept 2009)
    'MC297': ChecksumType.HASH58,  # Classic 3G 160GB (Sept 2009)

    # iPod Nano 3G - HASH58 (confirmed in libgpod)
    'MA978': ChecksumType.HASH58,  # Nano 3G 4GB
    'MA980': ChecksumType.HASH58,  # Nano 3G 8GB
    'MB261': ChecksumType.HASH58,  # Nano 3G 4GB
    'MB249': ChecksumType.HASH58,  # Nano 3G 8GB

    # iPod Nano 4G - HASH58 (confirmed in libgpod)
    'MB754': ChecksumType.HASH58,  # Nano 4G 8GB
    'MB903': ChecksumType.HASH58,  # Nano 4G 4GB
    'MB907': ChecksumType.HASH58,  # Nano 4G 8GB
    'MB909': ChecksumType.HASH58,  # Nano 4G 16GB

    # iPod Nano 5G - HASH72 (confirmed in libgpod)
    'MC031': ChecksumType.HASH72,  # Nano 5G 8GB
    'MC040': ChecksumType.HASH72,  # Nano 5G 8GB
    'MC049': ChecksumType.HASH72,  # Nano 5G 16GB
    'MC050': ChecksumType.HASH72,  # Nano 5G 16GB
    'MC060': ChecksumType.HASH72,  # Nano 5G 8GB
    'MC062': ChecksumType.HASH72,  # Nano 5G 16GB

    # iPod Nano 6G/7G - UNSUPPORTED (HASHAB never reverse-engineered)
    'MC525': ChecksumType.UNSUPPORTED,  # Nano 6G 8GB
    'MC526': ChecksumType.UNSUPPORTED,  # Nano 6G 8GB
    'MC688': ChecksumType.UNSUPPORTED,  # Nano 6G 16GB
    'MC689': ChecksumType.UNSUPPORTED,  # Nano 6G 16GB
    'MD476': ChecksumType.UNSUPPORTED,  # Nano 7G 16GB
    'MD477': ChecksumType.UNSUPPORTED,  # Nano 7G 16GB
    'MD481': ChecksumType.UNSUPPORTED,  # Nano 7G 16GB
}

# Older iPods that don't need any checksum
NO_CHECKSUM_MODELS = {
    # iPod 1G-5G, Mini, Photo
    'M8541', 'M8697', 'M8709', 'M8740', 'M8741',  # 1G/2G
    'M8976', 'M9244', 'M9245', 'M9282',            # 3G
    'M9282', 'M9585', 'M9586', 'M9724', 'M9725',  # 4G
    'M9800', 'M9829', 'M9830', 'M9831', 'M9834',  # Photo
    'MA002', 'MA003', 'MA004', 'MA005', 'MA006',  # 5G
    'MA099', 'MA107', 'MA147', 'MA148', 'MA350',  # 5G
    'MA446', 'MA448', 'MA450', 'MA497',            # 5G
    'M9160', 'M9436', 'M9437', 'M9460', 'M9800',  # Mini
    'M9801', 'M9802', 'M9803', 'M9804', 'M9805',  # Mini
    'M9806', 'M9807', 'M9809',                      # Mini
    # Nano 1G-2G
    'MA004', 'MA005', 'MA099', 'MA107', 'MA350',
    'MA477', 'MA487', 'MA497', 'MA725', 'MA726',
    'MA727', 'MA428', 'MA464', 'MA477', 'MA484',
}


# Comprehensive iPod model database
# Maps order number prefixes to (product_line, generation, capacity, color)
#
# Sources:
#   - Universal Compendium iPod Models table (universalcompendium.com)
#   - The Apple Wiki: Models/iPod (theapplewiki.com)
#
# Generation naming conventions:
#   The full-size iPod line has TWO numbering systems. This table uses the
#   product-specific generation (matching what users see in "About" screens),
#   with the overall iPod lineage noted in comments.
#
#   Overall iPod gen │ Product-specific gen │ Years │ Apple Model
#   ─────────────────┼──────────────────────┼───────┼────────────
#   1st gen           │ iPod 1st Gen         │ 2001  │ M8541
#   2nd gen           │ iPod 2nd Gen         │ 2002  │ A1019
#   3rd gen           │ iPod 3rd Gen         │ 2003  │ A1040
#   4th gen           │ iPod 4th Gen         │ 2004  │ A1059
#   4th gen (color)   │ iPod Photo           │ 2004  │ A1099
#   5th gen           │ iPod Video 5th Gen   │ 2005  │ A1136
#   5.5th gen         │ iPod Video 5.5th Gen │ 2006  │ A1136 (Rev B)
#   6th gen           │ iPod Classic 1st Gen │ 2007  │ A1238
#   6.5th gen         │ iPod Classic 2nd Gen │ 2008  │ A1238 (Rev A)
#   7th gen           │ iPod Classic 3rd Gen │ 2009  │ A1238 (Rev B/C)
#
IPOD_MODELS = {
    # ==========================================================================
    # iPod Classic (2007-2009)
    # Community: "6th gen / 6.5th gen / 7th gen iPod"
    # ==========================================================================
    # 1st Gen Classic / 6th gen overall (2007) — Apple Model A1238, Internal N25
    'MB029': ("iPod Classic", "1st Gen", "80GB", "Silver"),
    'MB147': ("iPod Classic", "1st Gen", "80GB", "Black"),
    'MB145': ("iPod Classic", "1st Gen", "160GB", "Silver"),
    'MB150': ("iPod Classic", "1st Gen", "160GB", "Black"),
    # 2nd Gen Classic / 6.5th gen overall (2008) — A1238 Rev A (thin, 120GB)
    'MB562': ("iPod Classic", "2nd Gen", "120GB", "Silver"),
    'MB565': ("iPod Classic", "2nd Gen", "120GB", "Black"),
    # 3rd Gen Classic / 7th gen overall (Late 2009) — A1238 Rev B/C
    'MC293': ("iPod Classic", "3rd Gen", "160GB", "Silver"),
    'MC297': ("iPod Classic", "3rd Gen", "160GB", "Black"),

    # ==========================================================================
    # iPod (Scroll Wheel) — 1st Generation (2001)
    # Apple Model: M8541 — Internal: P68/P68C
    # ==========================================================================
    'M8513': ("iPod", "1st Gen", "5GB", "White"),
    'M8541': ("iPod", "1st Gen", "5GB", "White"),
    'M8697': ("iPod", "1st Gen", "5GB", "White"),
    'M8709': ("iPod", "1st Gen", "10GB", "White"),

    # ==========================================================================
    # iPod (Touch Wheel) — 2nd Generation (2002)
    # Apple Model: A1019 — Internal: P97
    # ==========================================================================
    'M8737': ("iPod", "2nd Gen", "10GB", "White"),
    'M8740': ("iPod", "2nd Gen", "10GB", "White"),
    'M8738': ("iPod", "2nd Gen", "20GB", "White"),
    'M8741': ("iPod", "2nd Gen", "20GB", "White"),

    # ==========================================================================
    # iPod (Dock Connector) — 3rd Generation (2003)
    # Apple Model: A1040 — Internal: Q14
    # ==========================================================================
    'M8976': ("iPod", "3rd Gen", "10GB", "White"),
    'M8946': ("iPod", "3rd Gen", "15GB", "White"),
    'M8948': ("iPod", "3rd Gen", "30GB", "White"),
    'M9244': ("iPod", "3rd Gen", "20GB", "White"),
    'M9245': ("iPod", "3rd Gen", "40GB", "White"),
    'M9460': ("iPod", "3rd Gen", "15GB", "White"),  # Rev B

    # ==========================================================================
    # iPod (Click Wheel) — 4th Generation (2004)
    # Apple Model: A1059 — Internal: Q21
    # ==========================================================================
    'M9268': ("iPod", "4th Gen", "40GB", "White"),
    'M9282': ("iPod", "4th Gen", "20GB", "White"),
    # U2 Special Edition — 4th Gen
    'M9787': ("iPod U2", "4th Gen", "20GB", "Black"),

    # ==========================================================================
    # iPod Photo / iPod with Colour Display — 4th Gen (Color) (2004-2005)
    # Apple Model: A1099 — Internal: P98
    # Community: "4th gen color" or "iPod Photo"
    # ==========================================================================
    'M9585': ("iPod Photo", "4th Gen", "40GB", "White"),
    'M9586': ("iPod Photo", "4th Gen", "60GB", "White"),
    'M9829': ("iPod Photo", "4th Gen", "30GB", "White"),
    'M9830': ("iPod Photo", "4th Gen", "60GB", "White"),
    'MA079': ("iPod Photo", "4th Gen", "20GB", "White"),
    # U2 Special Edition (Colour Display)
    'MA127': ("iPod U2", "4th Gen", "20GB", "Black"),
    # Harry Potter Special Edition
    'MA215': ("iPod Photo", "4th Gen", "20GB", "White"),

    # ==========================================================================
    # iPod Video — 5th Generation (2005)
    # Apple Model: A1136 — Internal: M25
    # Same A1136 for both 5th and 5.5th gen; Rev B = "Enhanced" / 5.5th gen
    # ==========================================================================
    'MA002': ("iPod Video", "5th Gen", "30GB", "White"),
    'MA003': ("iPod Video", "5th Gen", "60GB", "White"),
    'MA146': ("iPod Video", "5th Gen", "30GB", "Black"),
    'MA147': ("iPod Video", "5th Gen", "60GB", "Black"),
    # U2 Special Edition — 5th Gen
    'MA452': ("iPod Video U2", "5th Gen", "30GB", "Black"),

    # ==========================================================================
    # iPod Video — 5.5th Generation / Enhanced (Late 2006)
    # Apple Model: A1136 Rev B — Internal: M25
    # Community: "5.5th gen" — brighter screen, search feature, gapless playback
    # ==========================================================================
    'MA444': ("iPod Video", "5.5th Gen", "30GB", "White"),
    'MA446': ("iPod Video", "5.5th Gen", "30GB", "Black"),
    'MA448': ("iPod Video", "5.5th Gen", "80GB", "White"),
    'MA450': ("iPod Video", "5.5th Gen", "80GB", "Black"),
    # U2 Special Edition — 5.5th Gen
    'MA664': ("iPod Video U2", "5.5th Gen", "30GB", "Black"),

    # ==========================================================================
    # iPod Mini — 1st Generation (2004)
    # Apple Model: A1051 — Internal: Q22
    # ==========================================================================
    'M9160': ("iPod Mini", "1st Gen", "4GB", "Silver"),
    'M9434': ("iPod Mini", "1st Gen", "4GB", "Green"),
    'M9435': ("iPod Mini", "1st Gen", "4GB", "Pink"),
    'M9436': ("iPod Mini", "1st Gen", "4GB", "Blue"),
    'M9437': ("iPod Mini", "1st Gen", "4GB", "Gold"),

    # ==========================================================================
    # iPod Mini — 2nd Generation (2005)
    # Apple Model: A1051 — Internal: Q22B
    # ==========================================================================
    'M9800': ("iPod Mini", "2nd Gen", "4GB", "Silver"),
    'M9801': ("iPod Mini", "2nd Gen", "6GB", "Silver"),
    'M9802': ("iPod Mini", "2nd Gen", "4GB", "Blue"),
    'M9803': ("iPod Mini", "2nd Gen", "6GB", "Blue"),
    'M9804': ("iPod Mini", "2nd Gen", "4GB", "Pink"),
    'M9805': ("iPod Mini", "2nd Gen", "6GB", "Pink"),
    'M9806': ("iPod Mini", "2nd Gen", "4GB", "Green"),
    'M9807': ("iPod Mini", "2nd Gen", "6GB", "Green"),

    # ==========================================================================
    # iPod Nano — 1st Generation (2005)
    # Apple Model: A1137 — Internal: M26
    # ==========================================================================
    'MA004': ("iPod Nano", "1st Gen", "2GB", "White"),
    'MA005': ("iPod Nano", "1st Gen", "4GB", "White"),
    'MA099': ("iPod Nano", "1st Gen", "2GB", "Black"),
    'MA107': ("iPod Nano", "1st Gen", "4GB", "Black"),
    'MA350': ("iPod Nano", "1st Gen", "1GB", "White"),
    'MA352': ("iPod Nano", "1st Gen", "1GB", "Black"),

    # ==========================================================================
    # iPod Nano — 2nd Generation (2006)
    # Apple Model: A1199 — Internal: N36
    # ==========================================================================
    'MA426': ("iPod Nano", "2nd Gen", "4GB", "Silver"),
    'MA428': ("iPod Nano", "2nd Gen", "4GB", "Blue"),
    'MA477': ("iPod Nano", "2nd Gen", "2GB", "Silver"),
    'MA487': ("iPod Nano", "2nd Gen", "4GB", "Green"),
    'MA489': ("iPod Nano", "2nd Gen", "4GB", "Pink"),
    'MA497': ("iPod Nano", "2nd Gen", "8GB", "Black"),
    'MA725': ("iPod Nano", "2nd Gen", "4GB", "Red"),
    'MA726': ("iPod Nano", "2nd Gen", "8GB", "Red"),
    'MA899': ("iPod Nano", "2nd Gen", "8GB", "Red"),

    # ==========================================================================
    # iPod Nano — 3rd Generation (2007, "Fat" Nano with video)
    # Apple Model: A1236 — Internal: N46
    # ==========================================================================
    'MA978': ("iPod Nano", "3rd Gen", "4GB", "Silver"),
    'MA980': ("iPod Nano", "3rd Gen", "8GB", "Silver"),
    'MB249': ("iPod Nano", "3rd Gen", "8GB", "Blue"),
    'MB253': ("iPod Nano", "3rd Gen", "8GB", "Green"),
    'MB257': ("iPod Nano", "3rd Gen", "8GB", "Red"),
    'MB261': ("iPod Nano", "3rd Gen", "8GB", "Black"),
    'MB453': ("iPod Nano", "3rd Gen", "8GB", "Pink"),

    # ==========================================================================
    # iPod Nano — 4th Generation (2008)
    # Apple Model: A1285 — Internal: N58
    # ==========================================================================
    # 4GB
    'MB480': ("iPod Nano", "4th Gen", "4GB", "Silver"),
    'MB651': ("iPod Nano", "4th Gen", "4GB", "Blue"),
    'MB654': ("iPod Nano", "4th Gen", "4GB", "Pink"),
    'MB657': ("iPod Nano", "4th Gen", "4GB", "Purple"),
    'MB660': ("iPod Nano", "4th Gen", "4GB", "Orange"),
    'MB663': ("iPod Nano", "4th Gen", "4GB", "Green"),
    'MB666': ("iPod Nano", "4th Gen", "4GB", "Yellow"),
    # 8GB
    'MB598': ("iPod Nano", "4th Gen", "8GB", "Silver"),
    'MB732': ("iPod Nano", "4th Gen", "8GB", "Blue"),
    'MB735': ("iPod Nano", "4th Gen", "8GB", "Pink"),
    'MB739': ("iPod Nano", "4th Gen", "8GB", "Purple"),
    'MB742': ("iPod Nano", "4th Gen", "8GB", "Orange"),
    'MB745': ("iPod Nano", "4th Gen", "8GB", "Green"),
    'MB748': ("iPod Nano", "4th Gen", "8GB", "Yellow"),
    'MB751': ("iPod Nano", "4th Gen", "8GB", "Red"),
    'MB754': ("iPod Nano", "4th Gen", "8GB", "Black"),
    # 16GB
    'MB903': ("iPod Nano", "4th Gen", "16GB", "Silver"),
    'MB905': ("iPod Nano", "4th Gen", "16GB", "Blue"),
    'MB907': ("iPod Nano", "4th Gen", "16GB", "Pink"),
    'MB909': ("iPod Nano", "4th Gen", "16GB", "Purple"),
    'MB911': ("iPod Nano", "4th Gen", "16GB", "Orange"),
    'MB913': ("iPod Nano", "4th Gen", "16GB", "Green"),
    'MB915': ("iPod Nano", "4th Gen", "16GB", "Yellow"),
    'MB917': ("iPod Nano", "4th Gen", "16GB", "Red"),
    'MB918': ("iPod Nano", "4th Gen", "16GB", "Black"),

    # ==========================================================================
    # iPod Nano — 5th Generation (2009, Camera Nano)
    # Apple Model: A1320 — Internal: N33
    # ==========================================================================
    # 8GB
    'MC027': ("iPod Nano", "5th Gen", "8GB", "Silver"),
    'MC031': ("iPod Nano", "5th Gen", "8GB", "Black"),
    'MC034': ("iPod Nano", "5th Gen", "8GB", "Purple"),
    'MC037': ("iPod Nano", "5th Gen", "8GB", "Blue"),
    'MC040': ("iPod Nano", "5th Gen", "8GB", "Green"),
    'MC043': ("iPod Nano", "5th Gen", "8GB", "Yellow"),
    'MC046': ("iPod Nano", "5th Gen", "8GB", "Orange"),
    'MC049': ("iPod Nano", "5th Gen", "8GB", "Red"),
    'MC050': ("iPod Nano", "5th Gen", "8GB", "Pink"),
    # 16GB
    'MC060': ("iPod Nano", "5th Gen", "16GB", "Silver"),
    'MC062': ("iPod Nano", "5th Gen", "16GB", "Black"),
    'MC064': ("iPod Nano", "5th Gen", "16GB", "Purple"),
    'MC066': ("iPod Nano", "5th Gen", "16GB", "Blue"),
    'MC068': ("iPod Nano", "5th Gen", "16GB", "Green"),
    'MC070': ("iPod Nano", "5th Gen", "16GB", "Yellow"),
    'MC072': ("iPod Nano", "5th Gen", "16GB", "Orange"),
    'MC074': ("iPod Nano", "5th Gen", "16GB", "Red"),
    'MC075': ("iPod Nano", "5th Gen", "16GB", "Pink"),

    # ==========================================================================
    # iPod Nano — 6th Generation (2010, Square Touchscreen)
    # Apple Model: A1366 — Internal: N20
    # ==========================================================================
    # 8GB
    'MC525': ("iPod Nano", "6th Gen", "8GB", "Silver"),
    'MC688': ("iPod Nano", "6th Gen", "8GB", "Graphite"),
    'MC689': ("iPod Nano", "6th Gen", "8GB", "Blue"),
    'MC690': ("iPod Nano", "6th Gen", "8GB", "Green"),
    'MC691': ("iPod Nano", "6th Gen", "8GB", "Orange"),
    'MC692': ("iPod Nano", "6th Gen", "8GB", "Pink"),
    'MC693': ("iPod Nano", "6th Gen", "8GB", "Red"),
    # 16GB
    'MC526': ("iPod Nano", "6th Gen", "16GB", "Silver"),
    'MC694': ("iPod Nano", "6th Gen", "16GB", "Graphite"),
    'MC695': ("iPod Nano", "6th Gen", "16GB", "Blue"),
    'MC696': ("iPod Nano", "6th Gen", "16GB", "Green"),
    'MC697': ("iPod Nano", "6th Gen", "16GB", "Orange"),
    'MC698': ("iPod Nano", "6th Gen", "16GB", "Pink"),
    'MC699': ("iPod Nano", "6th Gen", "16GB", "Red"),

    # ==========================================================================
    # iPod Nano — 7th Generation (2012, Tall Touchscreen)
    # Apple Model: A1446 — Internal: N31
    # ==========================================================================
    'MD475': ("iPod Nano", "7th Gen", "16GB", "Pink"),
    'MD476': ("iPod Nano", "7th Gen", "16GB", "Yellow"),
    'MD477': ("iPod Nano", "7th Gen", "16GB", "Blue"),
    'MD478': ("iPod Nano", "7th Gen", "16GB", "Green"),
    'MD479': ("iPod Nano", "7th Gen", "16GB", "Purple"),
    'MD480': ("iPod Nano", "7th Gen", "16GB", "Silver"),
    'MD481': ("iPod Nano", "7th Gen", "16GB", "Slate"),
    'MD744': ("iPod Nano", "7th Gen", "16GB", "Red"),
    'ME971': ("iPod Nano", "7th Gen", "16GB", "Space Gray"),
    # Mid 2015 refresh (Rev A) — same A1446
    'MKMV2': ("iPod Nano", "7th Gen", "16GB", "Pink"),
    'MKMX2': ("iPod Nano", "7th Gen", "16GB", "Gold"),
    'MKN02': ("iPod Nano", "7th Gen", "16GB", "Blue"),
    'MKN22': ("iPod Nano", "7th Gen", "16GB", "Silver"),
    'MKN52': ("iPod Nano", "7th Gen", "16GB", "Space Gray"),
    'MKN72': ("iPod Nano", "7th Gen", "16GB", "Red"),

    # ==========================================================================
    # iPod Shuffle — 1st Generation (2005)
    # Apple Model: A1112 — Internal: Q98
    # ==========================================================================
    'M9724': ("iPod Shuffle", "1st Gen", "512MB", "White"),
    'M9725': ("iPod Shuffle", "1st Gen", "1GB", "White"),

    # ==========================================================================
    # iPod Shuffle — 2nd Generation (2006-2008)
    # Apple Model: A1204 — Internal: N98
    # Multiple color refreshes within same generation
    # ==========================================================================
    # Initial (2006)
    'MA564': ("iPod Shuffle", "2nd Gen", "1GB", "Silver"),
    # Jan 2007 colors
    'MA947': ("iPod Shuffle", "2nd Gen", "1GB", "Pink"),
    'MA949': ("iPod Shuffle", "2nd Gen", "1GB", "Blue"),
    'MA951': ("iPod Shuffle", "2nd Gen", "1GB", "Green"),
    'MA953': ("iPod Shuffle", "2nd Gen", "1GB", "Orange"),
    # Sept 2007 (Rev A) — 1GB
    'MB225': ("iPod Shuffle", "2nd Gen", "1GB", "Silver"),
    'MB227': ("iPod Shuffle", "2nd Gen", "1GB", "Blue"),
    'MB228': ("iPod Shuffle", "2nd Gen", "1GB", "Blue"),
    'MB229': ("iPod Shuffle", "2nd Gen", "1GB", "Green"),
    'MB231': ("iPod Shuffle", "2nd Gen", "1GB", "Red"),
    'MB233': ("iPod Shuffle", "2nd Gen", "1GB", "Purple"),
    # Sept 2007 (Rev A) — 2GB
    'MB518': ("iPod Shuffle", "2nd Gen", "2GB", "Silver"),
    'MB520': ("iPod Shuffle", "2nd Gen", "2GB", "Blue"),
    'MB522': ("iPod Shuffle", "2nd Gen", "2GB", "Green"),
    'MB524': ("iPod Shuffle", "2nd Gen", "2GB", "Red"),
    'MB526': ("iPod Shuffle", "2nd Gen", "2GB", "Purple"),
    # 2008 (Rev B) — 1GB
    'MB811': ("iPod Shuffle", "2nd Gen", "1GB", "Pink"),
    'MB813': ("iPod Shuffle", "2nd Gen", "1GB", "Blue"),
    'MB815': ("iPod Shuffle", "2nd Gen", "1GB", "Green"),
    'MB817': ("iPod Shuffle", "2nd Gen", "1GB", "Red"),
    # 2008 (Rev B) — 2GB
    'MB681': ("iPod Shuffle", "2nd Gen", "2GB", "Pink"),
    'MB683': ("iPod Shuffle", "2nd Gen", "2GB", "Blue"),
    'MB685': ("iPod Shuffle", "2nd Gen", "2GB", "Green"),
    'MB779': ("iPod Shuffle", "2nd Gen", "2GB", "Red"),
    # Special Edition
    'MC167': ("iPod Shuffle", "2nd Gen", "1GB", "Gold"),

    # ==========================================================================
    # iPod Shuffle — 3rd Generation (2009, Buttonless/VoiceOver)
    # Apple Model: A1271 — Internal: D98
    # ==========================================================================
    'MB867': ("iPod Shuffle", "3rd Gen", "4GB", "Silver"),
    'MC164': ("iPod Shuffle", "3rd Gen", "4GB", "Black"),
    # Sept 2009 refresh — 2GB
    'MC306': ("iPod Shuffle", "3rd Gen", "2GB", "Silver"),
    'MC323': ("iPod Shuffle", "3rd Gen", "2GB", "Black"),
    'MC381': ("iPod Shuffle", "3rd Gen", "2GB", "Green"),
    'MC384': ("iPod Shuffle", "3rd Gen", "2GB", "Blue"),
    'MC387': ("iPod Shuffle", "3rd Gen", "2GB", "Pink"),
    # Sept 2009 refresh — 4GB
    'MC303': ("iPod Shuffle", "3rd Gen", "4GB", "Stainless Steel"),
    'MC307': ("iPod Shuffle", "3rd Gen", "4GB", "Green"),
    'MC328': ("iPod Shuffle", "3rd Gen", "4GB", "Blue"),
    'MC331': ("iPod Shuffle", "3rd Gen", "4GB", "Pink"),

    # ==========================================================================
    # iPod Shuffle — 4th Generation (2010-2015)
    # Apple Model: A1373 — Internal: N12
    # ==========================================================================
    # Initial (Sept 2010)
    'MC584': ("iPod Shuffle", "4th Gen", "2GB", "Silver"),
    'MC585': ("iPod Shuffle", "4th Gen", "2GB", "Pink"),
    'MC749': ("iPod Shuffle", "4th Gen", "2GB", "Orange"),
    'MC750': ("iPod Shuffle", "4th Gen", "2GB", "Green"),
    'MC751': ("iPod Shuffle", "4th Gen", "2GB", "Blue"),
    # Late 2012 (Rev A)
    'MD773': ("iPod Shuffle", "4th Gen", "2GB", "Pink"),
    'MD774': ("iPod Shuffle", "4th Gen", "2GB", "Yellow"),
    'MD775': ("iPod Shuffle", "4th Gen", "2GB", "Blue"),
    'MD776': ("iPod Shuffle", "4th Gen", "2GB", "Green"),
    'MD777': ("iPod Shuffle", "4th Gen", "2GB", "Purple"),
    'MD778': ("iPod Shuffle", "4th Gen", "2GB", "Silver"),
    'MD779': ("iPod Shuffle", "4th Gen", "2GB", "Slate"),
    'MD780': ("iPod Shuffle", "4th Gen", "2GB", "Red"),
    'ME949': ("iPod Shuffle", "4th Gen", "2GB", "Space Gray"),
    # Mid 2015 (Rev B)
    'MKM72': ("iPod Shuffle", "4th Gen", "2GB", "Pink"),
    'MKM92': ("iPod Shuffle", "4th Gen", "2GB", "Gold"),
    'MKME2': ("iPod Shuffle", "4th Gen", "2GB", "Blue"),
    'MKMG2': ("iPod Shuffle", "4th Gen", "2GB", "Silver"),
    'MKMJ2': ("iPod Shuffle", "4th Gen", "2GB", "Space Gray"),
    'MKML2': ("iPod Shuffle", "4th Gen", "2GB", "Red"),
}


def read_sysinfo(ipod_path: str) -> dict:
    """
    Parse SysInfo file from iPod.

    The SysInfo file contains device identification info:
    - ModelNumStr: Device model (e.g., "xA623")
    - FirewireGuid: Device GUID for hash computation
    - pszSerialNumber: Serial number
    - BoardHwName: Hardware identifier
    - visibleBuildID: Firmware version

    Args:
        ipod_path: Mount point of iPod

    Returns:
        Dictionary of SysInfo key-value pairs

    Raises:
        FileNotFoundError: If SysInfo doesn't exist
    """
    sysinfo_path = os.path.join(ipod_path, "iPod_Control", "Device", "SysInfo")

    if not os.path.exists(sysinfo_path):
        raise FileNotFoundError(f"SysInfo not found at {sysinfo_path}")

    sysinfo = {}
    with open(sysinfo_path, 'r', errors='ignore') as f:
        for line in f:
            line = line.strip()
            if ':' in line:
                key, value = line.split(':', 1)
                sysinfo[key.strip()] = value.strip()

    return sysinfo


def _extract_model_number(model_str: str) -> Optional[str]:
    """
    Extract model number from ModelNumStr.

    ModelNumStr format varies:
    - "xA623" -> "MA623"
    - "MC293" -> "MC293"
    - "M9282" -> "M9282"
    """
    if not model_str:
        return None

    # Remove leading 'x' if present (some devices use xANNN format)
    if model_str.startswith('x'):
        model_str = 'M' + model_str[1:]

    # Extract model number (typically 5 characters: MXXXX or MAXXXX)
    match = re.match(r'^(M[A-Z]?\d{3,4})', model_str.upper())
    if match:
        return match.group(1)

    return model_str.upper()[:5] if len(model_str) >= 5 else model_str.upper()


def _read_firewire_id_from_registry() -> Optional[bytes]:
    """
    Read iPod FireWire GUID from Windows registry USB device entries.

    When an iPod is connected to Windows, its USB serial number is stored in:
      HKLM\\SYSTEM\\CurrentControlSet\\Enum\\USBSTOR\\Disk&Ven_Apple&Prod_iPod&Rev_*\\<SERIAL>&0

    The USB serial number for iPod Classic IS the FireWire GUID (16 hex chars = 8 bytes).
    This persists in the registry even after the iPod is disconnected.

    Returns:
        FireWire GUID as bytes, or None if not found
    """
    import sys
    if sys.platform != 'win32':
        return None

    try:
        import winreg
    except ImportError:
        return None

    try:
        usbstor_key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Enum\USBSTOR"
        )
    except OSError:
        return None

    try:
        # Find Apple iPod entries
        i = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(usbstor_key, i)
                i += 1
            except OSError:
                break

            if 'Apple' not in subkey_name or 'iPod' not in subkey_name:
                continue

            # Found an iPod entry — look at instance IDs for the serial
            try:
                device_key = winreg.OpenKey(usbstor_key, subkey_name)
                j = 0
                while True:
                    try:
                        instance_id = winreg.EnumKey(device_key, j)
                        j += 1
                    except OSError:
                        break

                    # Instance ID format: "<SERIAL>&0" or "8&xxx&0&<SERIAL>&0"
                    # The serial is a 16-char hex string (FireWire GUID)
                    # Try extracting from the instance ID
                    parts = instance_id.split('&')
                    for part in parts:
                        part = part.strip()
                        if len(part) == 16:
                            try:
                                guid = bytes.fromhex(part)
                                if guid != b'\x00' * 8:
                                    winreg.CloseKey(device_key)
                                    winreg.CloseKey(usbstor_key)
                                    return guid
                            except ValueError:
                                pass

                winreg.CloseKey(device_key)
            except OSError:
                continue

    finally:
        winreg.CloseKey(usbstor_key)

    return None


def _read_firewire_id_from_sysinfo_extended(ipod_path: str) -> Optional[bytes]:
    """
    Read FireWire GUID from iPod's SysInfoExtended XML plist file.

    SysInfoExtended is an XML plist located at:
      /iPod_Control/Device/SysInfoExtended

    It contains a FireWireGUID key with the device's GUID as a string.

    Returns:
        FireWire GUID as bytes, or None if not found
    """
    sysinfo_ex_path = os.path.join(ipod_path, "iPod_Control", "Device", "SysInfoExtended")
    if not os.path.exists(sysinfo_ex_path):
        return None

    try:
        with open(sysinfo_ex_path, 'r', errors='ignore') as f:
            content = f.read()

        # Simple XML parsing for FireWireGUID
        import re as _re
        match = _re.search(
            r'<key>FireWireGUID</key>\s*<string>([0-9A-Fa-f]+)</string>',
            content
        )
        if match:
            guid_hex = match.group(1)
            if guid_hex.startswith('0x') or guid_hex.startswith('0X'):
                guid_hex = guid_hex[2:]
            return bytes.fromhex(guid_hex)
    except Exception:
        pass

    return None


def get_firewire_id(
    ipod_path: str,
    *,
    known_guid: Optional[str] = None,
    drive_letter: Optional[str] = None,
) -> bytes:
    """
    Get FireWire GUID for an iPod, trying multiple sources.

    Sources tried in priority order:
    0. Pre-discovered GUID (``known_guid``) from the device scanner
    1. PnP device tree walk (most authoritative — tied to this drive letter)
    2. SysInfo file on the iPod (/iPod_Control/Device/SysInfo)
    3. SysInfoExtended XML plist on the iPod
    4. Windows registry (persists from previous USB connections)

    The FireWire GUID is required for HASH58 computation on iPod Classic
    and Nano 3G/4G. Despite the name, it's also used on USB-only iPods
    where it equals the USB device serial number.

    Args:
        ipod_path: Mount point / root path of iPod filesystem
        known_guid: Pre-discovered GUID hex string (e.g. from DiscoveredIPod).
                    If provided and valid, skips all probing.
        drive_letter: Drive letter (e.g. "D") for device tree walk.
                      If omitted, extracted from ``ipod_path`` if possible.

    Returns:
        FireWire GUID as bytes (typically 8 bytes)

    Raises:
        RuntimeError: If FireWire GUID cannot be found from any source
    """
    # Source 0: Pre-discovered GUID (from device scanner pipeline)
    if known_guid:
        try:
            guid_bytes = bytes.fromhex(known_guid)
            if guid_bytes != b'\x00' * len(guid_bytes):
                return guid_bytes
        except ValueError:
            pass

    # Determine drive letter for device tree walk
    if not drive_letter and ipod_path:
        # Extract from path like "D:\\" or "D:"
        clean = ipod_path.rstrip("\\/")
        if len(clean) >= 1 and clean[0].isalpha():
            drive_letter = clean[0]

    # Source 1: PnP device tree walk (most authoritative for connected device)
    if drive_letter:
        try:
            from GUI.device_scanner import _walk_device_tree, _setup_win32_prototypes
            _setup_win32_prototypes()
            tree_info = _walk_device_tree(drive_letter)
            if tree_info and tree_info.get("firewire_guid"):
                guid_hex = tree_info["firewire_guid"]
                result = bytes.fromhex(guid_hex)
                if result != b'\x00' * len(result):
                    return result
        except (ImportError, Exception):
            pass

    # Source 2: SysInfo file
    try:
        sysinfo = read_sysinfo(ipod_path)
        guid = sysinfo.get('FirewireGuid')
        if guid:
            if guid.startswith('0x') or guid.startswith('0X'):
                guid = guid[2:]
            result = bytes.fromhex(guid)
            if result != b'\x00' * len(result):
                return result
    except (FileNotFoundError, ValueError):
        pass

    # Source 3: SysInfoExtended plist
    result = _read_firewire_id_from_sysinfo_extended(ipod_path)
    if result:
        return result

    # Source 4: Windows registry (USB serial from previous connection)
    result = _read_firewire_id_from_registry()
    if result:
        return result

    raise RuntimeError(
        "Could not find iPod FireWire GUID. Tried:\n"
        "  1. Device tree walk (device not connected or no USB parent?)\n"
        "  2. SysInfo file (empty or missing)\n"
        "  3. SysInfoExtended file (not found)\n"
        "  4. Windows registry (no iPod USB history found)\n"
        "\n"
        "To fix this, connect the iPod and try again, or manually provide\n"
        "the FireWire GUID via the known_guid parameter."
    )


def detect_checksum_type(ipod_path: str) -> ChecksumType:
    """
    Detect which checksum type an iPod requires.

    Detection order:
    1. Check for model number in SysInfo
    2. Match against known device database
    3. Check for HashInfo file (indicates HASH72)
    4. Default to UNKNOWN

    Args:
        ipod_path: Mount point of iPod

    Returns:
        ChecksumType enum value
    """
    try:
        sysinfo = read_sysinfo(ipod_path)
    except FileNotFoundError:
        # No SysInfo = probably not an iPod or very old
        return ChecksumType.NONE

    # Try to get model number
    model_str = sysinfo.get('ModelNumStr', '')
    model_num = _extract_model_number(model_str)

    if model_num:
        # Check no-checksum models first
        for prefix in NO_CHECKSUM_MODELS:
            if model_num.startswith(prefix):
                return ChecksumType.NONE

        # Check known devices with checksums
        for prefix, checksum in DEVICE_CHECKSUMS.items():
            if model_num.startswith(prefix):
                return checksum

    # Check for HashInfo file (indicates HASH72-capable device that was synced)
    hash_info_path = os.path.join(ipod_path, "iPod_Control", "Device", "HashInfo")
    if os.path.exists(hash_info_path):
        return ChecksumType.HASH72

    # Check firmware version for hints
    firmware = sysinfo.get('visibleBuildID', '')
    if firmware:
        # Later firmware versions require checksums
        try:
            version = int(firmware.split('.')[0])
            if version >= 2:
                return ChecksumType.UNKNOWN  # Needs investigation
        except (ValueError, IndexError):
            pass

    # If we have a FireWire ID, it's probably a post-2007 device
    if 'FirewireGuid' in sysinfo:
        # Conservative: return UNKNOWN so user knows to investigate
        return ChecksumType.UNKNOWN

    # Older iPods without FireWire ID don't need checksums
    return ChecksumType.NONE


def get_model_info(model_number: Optional[str]) -> tuple[str, str, str, str] | None:
    """
    Get detailed model information from model number.

    Args:
        model_number: 5-char model number (e.g., 'MC293')

    Returns:
        Tuple of (name, generation, capacity, color) or None if not found
    """
    if not model_number:
        return None

    # Exact match first
    if model_number in IPOD_MODELS:
        return IPOD_MODELS[model_number]

    # Try prefix matching (some models share prefixes)
    for prefix, info in IPOD_MODELS.items():
        if model_number.startswith(prefix[:4]):
            return info

    return None


def get_friendly_model_name(model_number: Optional[str]) -> str:
    """
    Get a user-friendly model name string.

    Args:
        model_number: 5-char model number (e.g., 'MC293')

    Returns:
        Friendly name like "iPod Classic 160GB Silver (2nd Gen)"
    """
    info = get_model_info(model_number)
    if info:
        name, gen, capacity, color = info
        return f"{name} {capacity} {color} ({gen})"
    return f"Unknown iPod ({model_number})" if model_number else "Unknown iPod"


def get_device_info(ipod_path: str) -> dict:
    """
    Get comprehensive device information using multiple sources.

    Delegates to the unified scanner pipeline when available, falling back
    to local SysInfo parsing if the GUI module is not importable.

    Args:
        ipod_path: Mount point of iPod

    Returns:
        Dictionary with device details including:
        - model: Model number
        - serial: Serial number
        - firmware: Firmware version
        - firewire_id: FireWire GUID
        - checksum_type: Required checksum type
        - checksum_name: Human-readable checksum name
    """
    checksum_names = {
        ChecksumType.NONE: 'None (no checksum required)',
        ChecksumType.HASH58: 'HASH58 (Nano 3G - fully supported)',
        ChecksumType.HASH72: 'HASH72 (Classic/Nano 4G-5G - requires HashInfo)',
        ChecksumType.UNSUPPORTED: 'UNSUPPORTED (Nano 6G/7G - HASHAB not reverse-engineered)',
        ChecksumType.UNKNOWN: 'Unknown (device not in database)',
    }

    # Try the unified scanner pipeline first (uses all sources)
    model_num = None
    model_info = None
    serial = ""
    firmware = ""
    firewire_id = ""
    board = ""

    try:
        from GUI.app import DeviceManager

        # Use cached scanner result from DeviceManager (avoids re-scanning)
        dm = DeviceManager.get_instance()
        ipod = dm.discovered_ipod
        if ipod is not None and os.path.normpath(ipod.path) == os.path.normpath(ipod_path):
            if True:  # indent block preserved for minimal diff
                model_num = ipod.model_number or None
                if model_num:
                    model_info = IPOD_MODELS.get(model_num)
                if not model_info and ipod.model_family != "iPod":
                    model_info = (
                        ipod.model_family,
                        ipod.generation,
                        ipod.capacity,
                        ipod.color,
                    )
                serial = ipod.serial
                firmware = ipod.firmware
                firewire_id = ipod.firewire_guid
    except ImportError:
        pass  # GUI module not available (e.g., headless use)

    # Fallback: use local SysInfo parsing if scanner didn't find it
    sysinfo = {}
    try:
        sysinfo = read_sysinfo(ipod_path)
    except FileNotFoundError:
        pass

    if not model_info:
        model_str = sysinfo.get('ModelNumStr', '')
        model_num = _extract_model_number(model_str) if model_str else model_num
        model_info = get_model_info(model_num) if model_num else None

    if not serial:
        serial = sysinfo.get('pszSerialNumber', '')
    if not firmware:
        firmware = sysinfo.get('visibleBuildID', '')
    if not firewire_id:
        firewire_id = sysinfo.get('FirewireGuid', '')
    board = sysinfo.get('BoardHwName', '')

    # Serial → model lookup as one more fallback
    if not model_info and serial:
        last3 = serial[-3:] if len(serial) >= 3 else ""
        from GUI.device_scanner import SERIAL_LAST3_TO_MODEL
        mn = SERIAL_LAST3_TO_MODEL.get(last3)
        if mn:
            model_num = mn
            model_info = IPOD_MODELS.get(mn)

    checksum_type = detect_checksum_type(ipod_path)

    result = {
        'model': model_num,
        'model_raw': sysinfo.get('ModelNumStr', ''),
        'model_name': model_info[0] if model_info else 'Unknown',
        'model_generation': model_info[1] if model_info else '',
        'model_capacity': model_info[2] if model_info else '',
        'model_color': model_info[3] if model_info else '',
        'friendly_name': get_friendly_model_name(model_num) if model_num else (
            f"{model_info[0]} {model_info[2]} {model_info[3]} ({model_info[1]})".strip()
            if model_info else "iPod"
        ),
        'serial': serial,
        'firmware': firmware,
        'board': board,
        'firewire_id': firewire_id,
        'checksum_type': checksum_type,
        'checksum_name': checksum_names.get(checksum_type, 'Unknown'),
    }

    return result


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python device.py <ipod_path>")
        print("Example: python device.py E:")
        sys.exit(1)

    ipod_path = sys.argv[1]

    info = get_device_info(ipod_path)

    print("iPod Device Information")
    print("=" * 40)
    for key, value in info.items():
        print(f"{key:15}: {value}")
