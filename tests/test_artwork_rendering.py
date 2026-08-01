from PIL import Image
from PyQt6.QtGui import QImage, QPixmap

from iopenpod.gui.artwork_rendering import (
    dominant_artwork_color_from_pixmap,
    enhance_artwork_image,
    nested_artwork_radius,
)
from iopenpod.gui.imgMaker import getDominantColor


def test_nested_artwork_radius_preserves_parent_shape_language() -> None:
    assert nested_artwork_radius(12, 10) == 8
    assert nested_artwork_radius(6, 4) == 4
    assert nested_artwork_radius(8, 0) == 8


def test_enhance_artwork_image_preserves_size() -> None:
    image = Image.new("RGB", (64, 64), (120, 90, 60))

    enhanced = enhance_artwork_image(image)

    assert enhanced.size == image.size


def test_enhance_artwork_image_can_be_disabled() -> None:
    image = Image.new("RGB", (64, 64), (120, 90, 60))

    enhanced = enhance_artwork_image(image, enabled=False)

    assert enhanced is image


def test_pixmap_dominant_color_uses_the_shared_artwork_algorithm(qtbot) -> None:
    image = Image.new("RGBA", (20, 20), "#1e66f5")
    for x in range(4):
        for y in range(image.height):
            image.putpixel((x, y), (208, 15, 57, 255))
    qimage = QImage(
        image.tobytes("raw", "RGBA"),
        image.width,
        image.height,
        QImage.Format.Format_RGBA8888,
    ).copy()
    pixmap = QPixmap.fromImage(qimage)

    assert dominant_artwork_color_from_pixmap(pixmap) == getDominantColor(image)
