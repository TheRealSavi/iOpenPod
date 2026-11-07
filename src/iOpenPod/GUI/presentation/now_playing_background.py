"""Bounded, heavily blurred artwork and flowing Now Playing backgrounds."""

from math import cos, sin

from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from PySide6.QtGui import QColor, QImage

from iOpenPod.GUI.presentation.theme.dynamic import now_playing_scrim_opacity
from iOpenPod.GUI.presentation.theme.tokens import ThemeTokens

_BACKDROP_SIZE = 96
_ZOOM_CROP = 0.18
_BLUR_RADIUS = 16
_SATURATION = 2.5
_FADE_SECONDS = 1.2
_MESH_STEP = 8


def now_playing_background(image: QImage, tokens: ThemeTokens) -> QImage:
    """Retain the cover's spatial colors, with a theme-owned readability scrim.

    Processing always uses a tiny raster, independent of the source or window
    size. The returned image owns its bytes and can be stretched while resizing.
    """

    if image.isNull():
        return QImage()
    small = image.scaled(_BACKDROP_SIZE, _BACKDROP_SIZE).convertToFormat(
        QImage.Format.Format_RGB888
    )
    source = Image.frombytes(
        "RGB",
        (small.width(), small.height()),
        bytes(small.constBits()),
        "raw",
        "RGB",
        small.bytesPerLine(),
    )
    width, height = source.size
    cropped = source.crop(
        (
            round(width * _ZOOM_CROP),
            round(height * _ZOOM_CROP),
            round(width * (1 - _ZOOM_CROP)),
            round(height * (1 - _ZOOM_CROP)),
        )
    )
    enlarged = ImageOps.fit(cropped, (_BACKDROP_SIZE, _BACKDROP_SIZE))
    # Boost the blended color fields; boosting individual source pixels first
    # still lets the heavy blur average them back toward gray.
    blurred = (
        ImageEnhance.Color(enlarged.filter(ImageFilter.GaussianBlur(_BLUR_RADIUS)))
        .enhance(_SATURATION)
        # Strong saturation clips some channels; soften those contours while
        # retaining the color inside each broad field.
        .filter(ImageFilter.GaussianBlur(_BLUR_RADIUS / 4))
    )
    # RGB bytes avoid Pillow's mode-dependent getextrema return type.
    pixels = blurred.tobytes()
    opacity = now_playing_scrim_opacity(
        (min(pixels[0::3]), min(pixels[1::3]), min(pixels[2::3])),
        (max(pixels[0::3]), max(pixels[1::3]), max(pixels[2::3])),
        tokens,
    )
    canvas = QColor(tokens.window)
    muted = Image.blend(
        blurred,
        Image.new("RGB", blurred.size, (canvas.red(), canvas.green(), canvas.blue())),
        opacity,
    )
    return _to_qimage(muted)


def _to_qimage(image: Image.Image) -> QImage:
    return QImage(
        image.tobytes(),
        image.width,
        image.height,
        image.width * 3,
        QImage.Format.Format_RGB888,
    ).copy()


def _flow(image: Image.Image, seconds: float) -> Image.Image:
    """Bend the retained color fields with independent, slow spatial waves.

    Adjacent quads share their source vertices. Coordinates stay inside the
    source, so even the window edges remain filled without wrapping seams.
    Bilinear sampling cannot introduce colors outside the readable source range.
    """

    def sample(x: int, y: int) -> tuple[float, float]:
        u, v = 2 * x / _BACKDROP_SIZE - 1, 2 * y / _BACKDROP_SIZE - 1
        sx = 0.38 * u + 0.36 * sin(2.4 * v + seconds * 0.27)
        sx += 0.26 * cos(2.0 * u - seconds * 0.19)
        sy = 0.38 * v + 0.36 * sin(2.3 * u - seconds * 0.23)
        sy += 0.26 * cos(2.0 * v + seconds * 0.17)
        half_span = (_BACKDROP_SIZE - 2) / 2
        return (1 + (sx + 1) * half_span, 1 + (sy + 1) * half_span)

    mesh: list[
        tuple[
            tuple[int, int, int, int],
            tuple[float, float, float, float, float, float, float, float],
        ]
    ] = []
    for y in range(0, _BACKDROP_SIZE, _MESH_STEP):
        for x in range(0, _BACKDROP_SIZE, _MESH_STEP):
            right, bottom = x + _MESH_STEP, y + _MESH_STEP
            quad = (
                *sample(x, y),
                *sample(x, bottom),
                *sample(right, bottom),
                *sample(right, y),
            )
            mesh.append(((x, y, right, bottom), quad))
    return image.transform(
        image.size, Image.Transform.MESH, mesh, Image.Resampling.BILINEAR
    )


class ArtworkBackgroundAnimation:
    """A tiny raster timeline, independent of playback position and window size.

    A replacement fades from the last displayed frame, including an interrupted
    fade. Only that snapshot, the target and the current frame are retained.
    Callers advance visible time; hidden time must not advance this timeline.
    """

    def __init__(self, canvas: QColor) -> None:
        self._target = Image.new(
            "RGB",
            (_BACKDROP_SIZE, _BACKDROP_SIZE),
            (canvas.red(), canvas.green(), canvas.blue()),
        )
        self._frame = self._target
        self._previous: Image.Image | None = None
        self._has_artwork = False
        self._seconds = 0.0
        self._fade_elapsed = 0.0
        self.image = _to_qimage(self._frame)

    @property
    def active(self) -> bool:
        return self._has_artwork or self._previous is not None

    def set_image(self, image: QImage, canvas: QColor, *, animate: bool) -> None:
        self._has_artwork = not image.isNull()
        if self._has_artwork:
            small = image.scaled(_BACKDROP_SIZE, _BACKDROP_SIZE).convertToFormat(
                QImage.Format.Format_RGB888
            )
            self._target = Image.frombytes(
                "RGB",
                (_BACKDROP_SIZE, _BACKDROP_SIZE),
                bytes(small.constBits()),
                "raw",
                "RGB",
                small.bytesPerLine(),
            )
        else:
            self._target = Image.new(
                "RGB",
                (_BACKDROP_SIZE, _BACKDROP_SIZE),
                (canvas.red(), canvas.green(), canvas.blue()),
            )
        self._previous = self._frame if animate else None
        self._fade_elapsed = 0.0
        self.advance(0)

    def settle(self) -> None:
        """Finish a transition immediately when the Host disables animation."""

        self._previous = None
        self.advance(0)

    def advance(self, seconds: float) -> None:
        self._seconds += max(0.0, seconds)
        self._fade_elapsed += max(0.0, seconds)
        target = (
            _flow(self._target, self._seconds) if self._has_artwork else self._target
        )
        if self._previous is not None and self._fade_elapsed < _FADE_SECONDS:
            progress = self._fade_elapsed / _FADE_SECONDS
            eased = progress * progress * (3 - 2 * progress)
            self._frame = Image.blend(self._previous, target, eased)
        else:
            self._previous = None
            self._frame = target
        self.image = _to_qimage(self._frame)
