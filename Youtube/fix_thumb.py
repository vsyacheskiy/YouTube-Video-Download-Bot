import os
from PIL import Image


async def fix_thumb(thumb_path: str):
    width = 0
    height = 0
    try:
        if thumb_path and os.path.exists(thumb_path):
            with Image.open(thumb_path) as img:
                width, height = img.size
                img = img.convert("RGB")
                aspect_ratio = height / width if width else 1
                new_height = int(320 * aspect_ratio)
                resized_img = img.resize((320, new_height))
                resized_img.save(thumb_path, "JPEG")
    except Exception as e:
        print(f"[fix_thumb] Error: {e}")
        thumb_path = None

    return width, height, thumb_path
