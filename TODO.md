# TODO List

## Implement Sync Engine and Transcoder

Remaining work begins after Review: validate the selected Sync Plan, transcode
incompatible media into iPod Device compatible media, following the users desired transcoding settings. Stage and verify device changes to a library draft, commit everything through Storage, only Storage should have read write access to host and ipod filesystems. Update the Library Sync Helper json only after success, and expose recoverable failure and
cancellation behavior. Cover edge cases and have sensible description warnings and errors with proper mitigation when possible and propigation of those to the user so they know what happened. Avoid orphaning things on the iPod. A partially successful sync is better than nothing, and if it cant be made partial, be sure to clean up. Playlist reconciliation and Sync execution are not yet
implemented. Be sure to check for FFMPEG, FFPROBE, and FPCALC. be sure to propogate an error when the tool is missing. Have perfomance at the front of everything. Utilize the full system hardware when you can utilizing conccurent conpute and threads. Rememember that all iPods are USB 2.0 so very limited in bus speed.

The Transcoder shoud have these Settings:\
Lossy encoder: The encoder to use when encoding a lossy format. Has an Auto setting. When this is set we will pick the highest quality available one for the job. \
Transcode Lossless into Lossy: Does what it says on the tin. All lossless formats get put through the selected lossy encoder.

Retranscode Lossy into Lossy: Does wheat it says on the tin. If a file is already an iPod compatible lossy file, instead of just letting it through, it gets put through the selected Lossy encoder.

Transcode WAV and AIFF to ALAC: Yep, even though those are compatible, when this is on, they get encoded into ALAC. (Unless Transcode Lossless into Lossy is on)

Normalize to 44.1khz: Some iPods support up to 48khz but this can sometimes cause lag and larger files for not much better quality. When this is on anything over 44.1khz is made 44.1khz.

Smart quality by Content Type: When this is on Podcasts and Audiobooks are encoded with a differnt set of settings called Spoken Word. Spoken Word is always lossy.

Spoken Word Mono: When on makes Spoken word tracks mono.

Spoken Word Bitrate: 32, 48, 64, 80, 96 kbps

If Lossy encoder is set to anything not Auto we get actual settings for that encoder as well. If its set to auto we get:\
Quality: Compact, Balanced, High Quality

Actual encoder settings include:

Bitrate Mode, CBR, VBR, ABR, CVBR (where encoder appropriate)

Bitrate (when set to a CBR setting): the bitrate.

VBR Qualitty: (When set to a VBR setting): the quality preset for the vbr. (different selection per encoder)

Encoder settings: Specific settings exposed per Encoder:

Bandwidth cutoff, Afterburner, TNS, PNS, Mid/Side Stereo, Intensity Stereo

We will also have these Sync setting selection from iOp 1\
Compute Sound Check

Normalize Tags After Sync

Rotate Tall Photos on Device

Fit thumbnails

Rockbox Metadata Support: Sometimes we write all the metadata to the file at the option of the user, this is for rockboxOS compatibility, since that uses file metadata entirely, but is useless waste of space for iPodOS.

## Future work

* Packaging and update checker/updater

* iPod Shuffle 1,2,3,4 support

* iPod Touch (possibly all and would cover all or at least a lot iPhones and iPads too) support through pymobiledevice3

* Add intelligent music understanding features like live djing and dj playlists

## The never ending hole

* Continue Implement and design of the iPodDB writers, and the library api. heavy focus on edge cases, errors and warnings, proper error and warning propogation and display to the user. Graceful handling of errors and warnings. Edits are pretty slow to make on large (20mb iTunesDB) Consider moments where the iPod runs out of space, the database runs out space, etc.

## Needs more testing

* Backups system, specifically restoring.

* i18n still being maintained everywhere.

* Sync Engine
