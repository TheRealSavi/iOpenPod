from . import field_base as _fb
from .constants import *  # noqa: F401, F403
from .extraction import *  # noqa: F401, F403
from .field_base import *  # noqa: F401, F403
from .mhbd_defs import *  # noqa: F401, F403
from .mhbd_defs import MHBD_FIELDS as _mhbd
from .mhia_defs import *  # noqa: F401, F403
from .mhia_defs import MHIA_FIELDS as _mhia
from .mhii_defs import *  # noqa: F401, F403
from .mhii_defs import MHII_FIELDS as _mhii
from .mhip_defs import *  # noqa: F401, F403
from .mhip_defs import MHIP_FIELDS as _mhip
from .mhit_defs import *  # noqa: F401, F403
from .mhit_defs import MHIT_FIELDS as _mhit
from .mhod_defs import *  # noqa: F401, F403
from .mhod_defs import MHOD_FIELDS as _mhod
from .mhsd_defs import *  # noqa: F401, F403
from .mhsd_defs import MHSD_FIELDS as _mhsd
from .mhyp_defs import *  # noqa: F401, F403
from .mhyp_defs import MHYP_FIELDS as _mhyp

# ── Build FIELD_REGISTRY from per-chunk defs ────────────────────────
_fb.FIELD_REGISTRY.update({
    "mhbd": _mhbd,
    "mhit": _mhit,
    "mhsd": _mhsd,
    "mhia": _mhia,
    "mhii": _mhii,
    "mhip": _mhip,
    "mhyp": _mhyp,
    "mhod": _mhod,
})
