import os
import json
import struct
import numpy as np
from PIL import Image, ImageTk
import tkinter as tk

JSON_FILE_PATH = r"C:\Users\JohnG\Documents\Coding Projects\iOpenPod\iOpenPod\artdb.json" 
ITHMB_FOLDER_PATH = r"C:\Users\JohnG\Documents\Coding Projects\iOpenPod\iOpenPod\testData\Artwork"

def rgb565_to_rgb888(pixel):
    r = (pixel >> 11) & 0x1F
    g = (pixel >> 5) & 0x3F
    b = pixel & 0x1F
    return (int((r * 255) / 31), int((g * 255) / 63), int((b * 255) / 31))

def generate_image(ithmb_filename, image_info):
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
        # Get current image dimensions
        num_pixels = image_info["imgSize"] // 2
        current_height = num_pixels // target_height
        current_width =  target_width
        
        pixels = np.frombuffer(img_data, dtype=np.uint16)
        rgb_pixels = [rgb565_to_rgb888(pixel) for pixel in pixels]
        rgb_array = np.array(rgb_pixels, dtype=np.uint8)
      
        # Reshape the array to 2D with 3 color channels
        rgb_array = rgb_array.reshape((current_height, current_width, 3))
        
        # If the image size doesn't match, the target, resize it
        if rgb_array.size != target_height * target_width * 3:
            img_pil = Image.fromarray(rgb_array)
            img_pil = img_pil.resize((target_width, target_height),  Image.Resampling.LANCZOS) 
            rgb_array = np.array(img_pil)
            
        try:
            return Image.fromarray(rgb_array, mode="RGB")
        except Exception as e:
            print(f"Error creating image from array: {e}")
            return None

    
    print(f"Unsupported image format: {fmt}")
    return None

def load_images_from_json(json_path):
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
        ithmb_filename = file_info.get("File Name")
        if ithmb_filename:
            ithmb_filename = ithmb_filename.lstrip(":")
        else:
            correlationID = thumb_result.get("correlationID")
            ithmb_filename = f"F{correlationID}_1.ithmb"

        ithmb_path = os.path.join(ITHMB_FOLDER_PATH, ithmb_filename)
        print(f"Processing image from file: {ithmb_path}")

        required_keys = ["ithmbOffset", "imgSize", "image_format"]
        if not all(key in thumb_result for key in required_keys):
            print("Missing required image info; skipping this entry.")
            continue

        img = generate_image(ithmb_path, thumb_result)
        if img is not None:
            img_id = entry.get("imgId", "unknown")
            images.append((img_id, img))
    return images

def display_images(images):
    root = tk.Tk()
    root.title("Image Viewer")

    canvas = tk.Canvas(root)
    scrollbar = tk.Scrollbar(root, orient="vertical", command=canvas.yview)
    scrollable_frame = tk.Frame(canvas)

    scrollable_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )

    canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)

    photo_images = []
    for img_id, img in images:
        photo = ImageTk.PhotoImage(img)
        photo_images.append(photo)
        frame = tk.Frame(scrollable_frame, pady=10)
        frame.pack(fill="x", padx=10)
        label = tk.Label(frame, image=photo)
        label.pack(side="left")
        id_label = tk.Label(frame, text=f"Image ID: {img_id}")
        id_label.pack(side="left", padx=10)

    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")
    root.mainloop()

if __name__ == "__main__":
    imgs = load_images_from_json(JSON_FILE_PATH)
    if imgs:
        display_images(imgs)
    else:
        print("No images loaded.")
