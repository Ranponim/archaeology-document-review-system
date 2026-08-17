import io


class ImageProcessor:
    PREPROCESSOR_VERSION: str = "v1"

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

    @staticmethod
    def is_valid_image(image_bytes: bytes) -> bool:
        """Check if image_bytes represents valid decodable image data."""
        if not image_bytes:
            return False
        try:
            from PIL import Image
            with Image.open(io.BytesIO(image_bytes)) as img:
                img.verify()
            return True
        except Exception:
            return False

    @staticmethod
    def crop_region(
        image_bytes: bytes,
        bbox: tuple[float, float, float, float] | list[float] | None,
        max_dimension: int = 768,
        quality: int = 75,
    ) -> bytes:
        """Crop region from image bytes based on bbox and prepare for VLM.

        Rejects empty or corrupt image bytes gracefully by returning b"".
        bbox convention: (x0, y0, x1, y1) with the PDF top-left origin. When
        every value lies in (0..1] the box is NORMALIZED relative to the image
        dimensions (this is the PlatePanelData.bbox convention — panel photo
        regions on a page render); otherwise it is treated as absolute pixel
        coordinates.
        """
        return ImageProcessor._crop(image_bytes, bbox, max_dimension=max_dimension, quality=quality)

    @staticmethod
    def crop_region_full(
        image_bytes: bytes,
        bbox: tuple[float, float, float, float] | list[float] | None,
    ) -> bytes:
        """Crop region from image bytes based on bbox WITHOUT resizing.

        Serves the actual cropped region at full resolution (Phase P0-D visual
        asset delivery). Same bbox convention and fail-closed b"" behavior as
        crop_region.
        """
        return ImageProcessor._crop(image_bytes, bbox, max_dimension=None, quality=95)

    @staticmethod
    def _crop(
        image_bytes: bytes,
        bbox: tuple[float, float, float, float] | list[float] | None,
        max_dimension: int | None = 768,
        quality: int = 75,
    ) -> bytes:
        if not image_bytes:
            return b""

        try:
            from PIL import Image
        except ImportError:
            return b""

        try:
            with Image.open(io.BytesIO(image_bytes)) as img:
                if img.mode != "RGB":
                    img = img.convert("RGB")

                width, height = img.size
                if width <= 0 or height <= 0:
                    return b""

                if bbox and len(bbox) == 4:
                    x0, y0, x1, y1 = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
                    if x1 <= x0 or y1 <= y0:
                        return b""
                    left, top, right, bottom = x0, y0, x1, y1

                    # Check if normalized coords
                    if 0.0 <= left <= 1.0 and 0.0 <= top <= 1.0 and right <= 1.0 and bottom <= 1.0 and (right > 0.0 or bottom > 0.0) and (width > 1 and height > 1):
                        crop_box = (
                            int(round(left * width)),
                            int(round(top * height)),
                            int(round(right * width)),
                            int(round(bottom * height)),
                        )
                    else:
                        crop_box = (
                            int(round(max(0.0, left))),
                            int(round(max(0.0, top))),
                            int(round(min(float(width), right))),
                            int(round(min(float(height), bottom))),
                        )

                    # Validate crop box dimensions
                    if crop_box[2] <= crop_box[0] or crop_box[3] <= crop_box[1]:
                        return b""

                    img = img.crop(crop_box)

                # Resize maintaining aspect ratio if largest dimension exceeds max_dimension
                if max_dimension is not None:
                    cur_w, cur_h = img.size
                    if max(cur_w, cur_h) > max_dimension:
                        if cur_w >= cur_h:
                            new_width = max_dimension
                            new_height = max(1, int(round(cur_h * (max_dimension / cur_w))))
                        else:
                            new_height = max_dimension
                            new_width = max(1, int(round(cur_w * (max_dimension / cur_h))))

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
            return b""
