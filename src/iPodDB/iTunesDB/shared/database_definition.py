"""iTunesDB structural definition shared by parsing and writing."""

from iPodDB.iTunesDB.shared.chunk_defs.mhbd import DEFINITION as MHBD_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhbd import MhbdHeader
from iPodDB.iTunesDB.shared.chunk_defs.mhia import DEFINITION as MHIA_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhii import DEFINITION as MHII_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhip import DEFINITION as MHIP_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhit import DEFINITION as MHIT_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhla import DEFINITION as MHLA_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhli import DEFINITION as MHLI_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhlp import DEFINITION as MHLP_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhlt import DEFINITION as MHLT_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhod import DEFINITION as MHOD_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import DATASET_DEFINITIONS
from iPodDB.iTunesDB.shared.chunk_defs.mhsd import DEFINITION as MHSD_DEFINITION
from iPodDB.iTunesDB.shared.chunk_defs.mhyp import DEFINITION as MHYP_DEFINITION
from iPodDB.shared.types import DatabaseDefinition

DATABASE_DEFINITION: DatabaseDefinition[MhbdHeader] = DatabaseDefinition(
    root_chunk=MHBD_DEFINITION,
    chunk_definitions=(
        MHBD_DEFINITION,
        MHSD_DEFINITION,
        MHLT_DEFINITION,
        MHIT_DEFINITION,
        MHLP_DEFINITION,
        MHYP_DEFINITION,
        MHIP_DEFINITION,
        MHLA_DEFINITION,
        MHIA_DEFINITION,
        MHLI_DEFINITION,
        MHII_DEFINITION,
        MHOD_DEFINITION,
    ),
    mhsd_dataset_definitions=DATASET_DEFINITIONS,
)
