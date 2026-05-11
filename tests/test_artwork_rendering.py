from PIL import Image

from GUI.artwork_rendering import enhance_artwork_image, nested_artwork_radius


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
