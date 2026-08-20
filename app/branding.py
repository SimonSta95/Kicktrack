from __future__ import annotations

from pathlib import Path

import httpx
from PySide6.QtCore import Qt
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
    """Trim the OpenGraph background without a costly full-resolution Python scan.

    Older builds sampled the original image with ``pixelColor`` hundreds of
    thousands of times on every start. Qt/Python calls are comparatively
    expensive and could stall the UI for seconds. We detect the bounding box on
    a small proxy image and map it back to the original resolution.
    """
    if pixmap.isNull():
        return pixmap

    image = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
    width = image.width()
    height = image.height()
    if width < 4 or height < 4:
        return pixmap

    # A ~180 px proxy keeps the scan below ~32k pixels while preserving more
    # than enough detail to locate the high-contrast Kickbase logo.
    proxy_limit = 180
    if max(width, height) > proxy_limit:
        proxy = image.scaled(
            proxy_limit, proxy_limit,
            Qt.KeepAspectRatio, Qt.SmoothTransformation,
        )
    else:
        proxy = image

    pw = proxy.width()
    ph = proxy.height()
    corner = proxy.pixelColor(0, 0)
    min_x, min_y = pw, ph
    max_x = max_y = -1

    for y in range(ph):
        for x in range(pw):
            color = proxy.pixelColor(x, y)
            if color.alpha() < 20:
                continue
            distance = (
                abs(color.red() - corner.red())
                + abs(color.green() - corner.green())
                + abs(color.blue() - corner.blue())
            )
            if distance <= 60:
                continue
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)

    if max_x < min_x or max_y < min_y:
        return pixmap

    scale_x = width / float(pw)
    scale_y = height / float(ph)
    left = int(min_x * scale_x)
    top = int(min_y * scale_y)
    right = int((max_x + 1) * scale_x) - 1
    bottom = int((max_y + 1) * scale_y) - 1

    padding = max(4, int(min(width, height) * 0.02))
    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(width - 1, right + padding)
    bottom = min(height - 1, bottom + padding)

    return pixmap.copy(left, top, right - left + 1, bottom - top + 1)


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
