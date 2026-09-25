"""ArtworkDB structural definition shared by parsing and writing."""

from iPodDB.ArtworkDB.shared.chunk_defs.mhaf import DEFINITION as MHAF_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhba import DEFINITION as MHBA_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import DEFINITION as MHFD_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhfd import MhfdHeader
from iPodDB.ArtworkDB.shared.chunk_defs.mhia import DEFINITION as MHIA_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhif import DEFINITION as MHIF_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhii import DEFINITION as MHII_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhla import DEFINITION as MHLA_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhlf import DEFINITION as MHLF_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhli import DEFINITION as MHLI_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhni import DEFINITION as MHNI_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhod import DEFINITION as MHOD_DEFINITION
from iPodDB.ArtworkDB.shared.chunk_defs.mhsd import DATASET_DEFINITIONS
from iPodDB.ArtworkDB.shared.chunk_defs.mhsd import DEFINITION as MHSD_DEFINITION
from iPodDB.shared.types import DatabaseDefinition

DATABASE_DEFINITION: DatabaseDefinition[MhfdHeader] = DatabaseDefinition(
    root_chunk=MHFD_DEFINITION,
    chunk_definitions=(
        MHFD_DEFINITION,
        MHAF_DEFINITION,
        MHBA_DEFINITION,
        MHIA_DEFINITION,
        MHIF_DEFINITION,
        MHII_DEFINITION,
        MHLA_DEFINITION,
        MHLF_DEFINITION,
        MHLI_DEFINITION,
        MHNI_DEFINITION,
        MHOD_DEFINITION,
        MHSD_DEFINITION,
    ),
    mhsd_dataset_definitions=DATASET_DEFINITIONS,
)
