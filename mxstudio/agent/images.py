"""Images for the model: verified, downscaled copies (the originals stay in the workspace untouched)."""
from __future__ import annotations

import io

from PIL import Image

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MODEL_LONG_EDGE = 1568  # px; larger images are downscaled by the API anyway and cost more tokens


class ImageRejected(ValueError):
    pass


def verify_upload(data: bytes) -> dict:
    """Facts about an uploaded picture; refuses anything that is not a real PNG/JPEG/WebP/GIF image."""
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise ImageRejected("the image is empty or larger than 20 MB")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            fmt, size = image.format, image.size
    except Exception as exc:  # noqa: BLE001 - any decoder failure is a rejected upload
        raise ImageRejected(f"not a readable image: {exc}") from exc
    if fmt not in {"PNG", "JPEG", "WEBP", "GIF"}:
        raise ImageRejected(f"unsupported image format {fmt}")
    return {"format": fmt, "width": size[0], "height": size[1], "bytes": len(data)}


def for_model(data: bytes) -> bytes:
    """A copy the model can read: long edge <= MODEL_LONG_EDGE, PNG or JPEG."""
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        picture = image.convert("RGBA") if image.mode in ("RGBA", "LA", "P") else image.convert("RGB")
    scale = MODEL_LONG_EDGE / max(picture.size)
    if scale < 1:
        picture = picture.resize((max(1, round(picture.width * scale)), max(1, round(picture.height * scale))),
                                 Image.LANCZOS)
    out = io.BytesIO()
    if picture.mode == "RGBA":
        picture.save(out, "PNG", optimize=True)
    else:
        picture.save(out, "JPEG", quality=88)
    return out.getvalue()
