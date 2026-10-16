# SQLite compatibility fixtures

`original-schema.json` records all table columns (including defaults, nullability,
and primary-key positions) and explicit index columns from the five database
writers in Original iOpenPod `v1.68.1`, commit `de300074`. It was extracted using
SQLite `table_info` and `index_info`; it contains schema only, no Track metadata or
device identifiers. The compatibility test checks every generated database against
this independent baseline, including empty Libraries. Original code is not a runtime
or test dependency.

`original-row-compatibility.json` records rows produced by Original iOpenPod
`origin/1.x`, commit `a20242428b93b672d14b37230772dbad75139c69`, using synthetic
Tracks only. Its seven Tracks include reused albums, case-sensitive name variants,
leading/trailing whitespace, and absent artists and composers. Six separate codec
examples include AAC with and without the native purchase flag, ALAC, protected
AAC, M4B, and MP3. The
fixture retains the exact queries, group IDs and references, empty Store records,
ordinary container flags, and Locations classifications from the Original
writers. It contains no captured Library content or device identifiers. Tests
reconstruct those synthetic inputs without importing Original source.

`observed-postprocess-commands.plist` is a minimal, identity-free excerpt of the
`com.apple.mobile.iTunes.SQLMusicLibraryPostProcessCommands` structure documented
from observed device metadata in
[MobileDeviceAccess](https://github.com/cipi1965/MobileDeviceAccess/blob/master/deviceValueForDomain.md).
It retains one observed command and the observed version-8 command-set shape. It is
not a complete `SysInfoExtended` capture and contains no device identifiers.
