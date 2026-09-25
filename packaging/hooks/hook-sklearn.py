"""Keep scikit-learn runtime data without shipping unused sample/test datasets."""

from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("sklearn", excludes=["datasets/**", "**/tests/**"])
