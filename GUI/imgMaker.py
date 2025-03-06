import os
import json
import struct
import numpy as np
from PIL import Image
from PyQt6.QtGui import QPixmap

def rgb565_to_rgb888(pixel):
    """Convert RGB565 to RGB888 format."""
    r = (pixel >> 11) & 0x1F
    g = (pixel >> 5) & 0x3F
    b = pixel & 0x1F
    return (int((r * 255) / 31), int((g * 255) / 63), int((b * 255) / 31))

def generate_image(ithmb_filename, image_info):
    """Generate image from the ithmb file based on image_info."""
    try:
        with open(ithmb_filename, "rb") as f:
            f.seek(image_info["ithmbOffset"])
            img_data = f.read(image_info["imgSize"])
    except Exception as e:
        print(f"Error reading {ithmb_filename}: {e}")
        return None

    fmt = image_info["image_format"]["format"]
    target_height = image_info["image_format"]["height"]
    target_width = image_info["image_format"]["width"]

    if fmt == "RGB565_LE":
        num_pixels = image_info["imgSize"] // 2
        current_height = num_pixels // target_height
        current_width = target_width
        
        pixels = np.frombuffer(img_data, dtype=np.uint16)
        rgb_pixels = [rgb565_to_rgb888(pixel) for pixel in pixels]
        rgb_array = np.array(rgb_pixels, dtype=np.uint8)
        
        # Reshape and resize image
        rgb_array = rgb_array.reshape((current_height, current_width, 3))
        img_pil = Image.fromarray(rgb_array)
        img_pil = img_pil.resize((target_width, target_height), Image.Resampling.LANCZOS)
        return img_pil

    print(f"Unsupported image format: {fmt}")
    return None

def load_images_from_json(json_path, ithmb_folder_path):
    """Load images from the JSON file and the ithmb folder."""
    with open(json_path, "r") as f:
        data = json.load(f)

    images = []
    for entry in data.get("mhli", []):
        try:
            thumb_result = entry["Thumbnail Image"]["Thumbnail Image"]["result"]
        except KeyError:
            print("Thumbnail image data not found for an entry; skipping.")
            continue

        file_info = thumb_result.get("3", {})
        ithmb_filename = file_info.get("File Name", f"F{thumb_result.get('correlationID')}_1.ithmb")
        ithmb_path = os.path.join(ithmb_folder_path, ithmb_filename)

        required_keys = ["ithmbOffset", "imgSize", "image_format"]
        if not all(key in thumb_result for key in required_keys):
            print("Missing required image info; skipping this entry.")
            continue

        img = generate_image(ithmb_path, thumb_result)
        if img is not None:
            img_id = entry.get("imgId", "unknown")
            images.append((img_id, img))
    return images


def find_image_by_imgId(json_path, ithmb_folder_path, imgId):
    """Find and return image for the given imgID."""
    with open(json_path, "r") as f:
        data = json.load(f)

    for entry in data.get("mhli", []):
        try:
            thumb_result = entry["Thumbnail Image"]["Thumbnail Image"]["result"]
        except KeyError:
            print("Thumbnail image data not found for an entry; skipping.")
            continue

        entry_imgId = entry.get("imgId", None)
        if entry_imgId != imgId:
            continue  # Skip entries that don't match the songID
        
        file_info = thumb_result.get("3", {})
        ithmb_filename = file_info.get("File Name", f"F{thumb_result.get('correlationID')}_1.ithmb")
        if ithmb_filename.startswith(":"):
            ithmb_filename = ithmb_filename[1:]
        ithmb_path = os.path.join(ithmb_folder_path, ithmb_filename)

        required_keys = ["ithmbOffset", "imgSize", "image_format"]
        if not all(key in thumb_result for key in required_keys):
            print("Missing required image info; skipping this entry.")
            continue

        img = generate_image(ithmb_path, thumb_result)
        if img is not None:
            return img
    print(f"No image found for imgId: {imgId}")
    return None