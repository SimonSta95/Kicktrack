from __future__ import annotations

from pathlib import Path

import httpx
from PySide6.QtGui import QIcon, QImage, QPixmap

from .storage import app_data_dir


KICKBASE_LOGO_URL = (
    "https://cdn.prod.website-files.com/6464bc5faea854743c54d599/"
    "68de8685cd6e9d7ab6c1bc1e_kickbase_opengraph.png"
)


def logo_path() -> Path:
    return app_data_dir() / "kickbase_opengraph.png"


def ensure_logo_file() -> Path | None:
    """Download the exact user-supplied Kickbase image once and cache it locally."""
    path = logo_path()

    if path.exists() and path.stat().st_size > 1024:
        return path

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/127.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        "Referer": "https://www.kickbase.com/",
        "Cache-Control": "no-cache",
    }

    try:
        with httpx.Client(follow_redirects=True, timeout=12.0, headers=headers) as client:
            response = client.get(KICKBASE_LOGO_URL)
            response.raise_for_status()
            raw = response.content

        if len(raw) < 1024:
            return None

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        return path
    except Exception:
        return None


def _crop_to_visible_content(pixmap: QPixmap) -> QPixmap:
    """Trim the large OpenGraph background around the actual logo without altering it."""
    if pixmap.isNull():
        return pixmap

    image = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
    width = image.width()
    height = image.height()
    if width < 4 or height < 4:
        return pixmap

    corner = image.pixelColor(0, 0)
    sample_scale = max(1, max(width, height) // 700)
    min_x, min_y = width, height
    max_x = max_y = -1

    def different_from_background(x: int, y: int) -> bool:
        color = image.pixelColor(x, y)
        if color.alpha() < 20:
            return False
        distance = (
            abs(color.red() - corner.red())
            + abs(color.green() - corner.green())
            + abs(color.blue() - corner.blue())
        )
        return distance > 60

    for y in range(0, height, sample_scale):
        for x in range(0, width, sample_scale):
            if different_from_background(x, y):
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)

    if max_x < min_x or max_y < min_y:
        return pixmap

    padding = max(4, int(min(width, height) * 0.02))
    min_x = max(0, min_x - padding)
    min_y = max(0, min_y - padding)
    max_x = min(width - 1, max_x + padding)
    max_y = min(height - 1, max_y + padding)

    return pixmap.copy(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)


def load_logo_pixmap() -> QPixmap | None:
    path = ensure_logo_file()
    if not path:
        return None
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return None
    return _crop_to_visible_content(pixmap)


def bundled_icon_path() -> Path:
    """Small symbol-only icon used for title bar and Windows taskbar."""
    root = Path(__file__).resolve().parent.parent
    return root / "assets" / "kickbase_icon.ico"


def app_icon() -> QIcon:
    """Use the supplied symbol-only Kickbase mark for the native app icon.

    The full OpenGraph logo is deliberately *not* used here because Windows
    reduces the window icon to 16–32 px, where only the mark stays readable.
    """
    ico = bundled_icon_path()
    if ico.exists():
        icon = QIcon(str(ico))
        if not icon.isNull():
            return icon

    png = ico.with_suffix(".png")
    if png.exists():
        icon = QIcon(str(png))
        if not icon.isNull():
            return icon

    return QIcon()
