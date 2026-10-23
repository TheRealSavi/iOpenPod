# SPDX-License-Identifier: LGPL-3.0-only
# Backported Qt declarations; see ../README.md for upstream provenance.
class QRhiDriverInfo:
    deviceName: PySide6.QtCore.QByteArray
    deviceId: int
    vendorId: int
    deviceType: int

class QRhiGraphicsPipeline:
    class TargetBlend:
        colorWrite: int
        enable: bool
        srcColor: int
        dstColor: int
        opColor: int
        srcAlpha: int
        dstAlpha: int
        opAlpha: int
