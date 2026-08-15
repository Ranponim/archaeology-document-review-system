import io


class ImageProcessor:
    @staticmethod
    def prepare_for_vlm(
        image_bytes: bytes, max_dimension: int = 768, quality: int = 75
    ) -> bytes:
        """Prepare image bytes for VLM consumption by resizing and compressing.

        1. If PIL (Pillow) is unavailable or image bytes cannot be decoded, gracefully
           returns the original bytes unchanged.
        2. If PIL is available: opens the image, converts to RGB if needed,
           resizes maintaining aspect ratio so the largest dimension is max_dimension,
           and saves as JPEG with the specified quality compression.
        """
        if not image_bytes:
            return image_bytes

        try:
            from PIL import Image
        except ImportError:
            return image_bytes

        try:
            with Image.open(io.BytesIO(image_bytes)) as img:
                # Convert to RGB mode if not already RGB (handles RGBA, P, L, CMYK, etc.)
                if img.mode != "RGB":
                    img = img.convert("RGB")

                # Resize maintaining aspect ratio if largest dimension exceeds max_dimension
                width, height = img.size
                if max(width, height) > max_dimension:
                    if width >= height:
                        new_width = max_dimension
                        new_height = max(1, int(round(height * (max_dimension / width))))
                    else:
                        new_height = max_dimension
                        new_width = max(1, int(round(width * (max_dimension / height))))

                    resample_filter = getattr(
                        getattr(Image, "Resampling", Image),
                        "LANCZOS",
                        getattr(Image, "LANCZOS", 1),
                    )
                    img = img.resize((new_width, new_height), resample=resample_filter)

                output_buffer = io.BytesIO()
                img.save(output_buffer, format="JPEG", quality=quality)
                return output_buffer.getvalue()
        except Exception:
            return image_bytes
