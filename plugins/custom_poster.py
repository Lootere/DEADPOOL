import io
import logging
import textwrap
import asyncio
from urllib.request import urlopen

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)
POSTER_SIZE = (720, 1080)


def _font(size, bold=False):
    candidates = (
        ["arialbd.ttf", "DejaVuSans-Bold.ttf"]
        if bold else ["arial.ttf", "DejaVuSans.ttf"]
    )
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def create_custom_poster(metadata, image_bytes):
    with Image.open(io.BytesIO(image_bytes)) as source:
        poster = source.convert("RGB")
        poster.thumbnail(POSTER_SIZE)

    canvas = Image.new("RGB", POSTER_SIZE, (15, 17, 26))
    x = (POSTER_SIZE[0] - poster.width) // 2
    canvas.paste(poster, (x, 0))
    draw = ImageDraw.Draw(canvas, "RGBA")
    panel_top = POSTER_SIZE[1] - 330
    draw.rectangle((0, panel_top, POSTER_SIZE[0], POSTER_SIZE[1]), fill=(8, 10, 18, 238))

    title = str(metadata.get("title") or "Unknown title")
    title_lines = textwrap.wrap(title, width=28)[:2]
    draw.multiline_text(
        (38, panel_top + 24),
        "\n".join(title_lines),
        font=_font(42, bold=True),
        fill=(255, 255, 255),
        spacing=4,
    )
    year = metadata.get("year")
    rating = metadata.get("rating")
    languages = metadata.get("languages")
    details = [
        "  •  ".join(str(item) for item in (year, f"IMDb {rating}" if rating else None) if item),
        f"Language: {languages}" if languages else "",
        "RKMOVIESZIP",
    ]
    draw.multiline_text(
        (40, panel_top + 142),
        "\n".join(line for line in details if line),
        font=_font(25),
        fill=(225, 228, 238),
        spacing=12,
    )

    output = io.BytesIO()
    canvas.save(output, format="JPEG", quality=88, optimize=True)
    return output.getvalue()


async def fetch_custom_poster(metadata):
    poster_url = metadata.get("poster")
    if not poster_url:
        return None
    try:
        def download():
            with urlopen(poster_url, timeout=12) as response:
                return response.read()

        image_bytes = await asyncio.to_thread(download)
        return create_custom_poster(metadata, image_bytes)
    except Exception:
        logger.exception("Could not generate custom poster for %r", metadata.get("title"))
        return None
