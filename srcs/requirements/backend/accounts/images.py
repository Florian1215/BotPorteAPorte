"""Logo processing: any reasonable photo or image in, a small WebP out (only the pixels the app displays)."""
import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

# Largest logo on screen is 80 CSS px; 256 px covers 3x (Retina) displays with margin.
LOGO_SIZE = 256
# Refuse "decompression bombs" (tiny files that expand to gigantic images): ~40 megapixels is plenty for a photo.
MAX_PIXELS = 40_000_000


class InvalidImage(Exception):
    pass


def process_logo(file) -> bytes:
    """Read an uploaded image, fix its orientation, shrink it to LOGO_SIZE and encode it as WebP."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            image = Image.open(file)
            if image.width * image.height > MAX_PIXELS:
                raise InvalidImage("Cette image est beaucoup trop grande.")
            image.draft("RGB", (LOGO_SIZE * 2, LOGO_SIZE * 2))  # fast JPEG decoding at reduced size
            image.load()
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError, ValueError):
        raise InvalidImage("Ce fichier n'est pas une image lisible (PNG, JPEG, WebP, GIF…).") from None

    image = ImageOps.exif_transpose(image)  # photos taken in portrait
    image = image.convert("RGBA" if image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info else "RGB")
    image.thumbnail((LOGO_SIZE, LOGO_SIZE), Image.Resampling.LANCZOS)

    out = io.BytesIO()
    image.save(out, format="WEBP", quality=88, method=6)
    return out.getvalue()
