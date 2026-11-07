"""Keep Whenever's lazy imports and timezone resources in frozen applications."""

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_submodules,
    copy_metadata,
)

# Whenever 0.11 exposes its public API through dynamic imports in __getattr__.
# Include both the native extension and its supported pure-Python fallback.
hiddenimports = collect_submodules("whenever") + collect_submodules("tzdata")
datas = copy_metadata("whenever") + collect_data_files("tzdata")
