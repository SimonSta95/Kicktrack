import ctypes
import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app.branding import app_icon, bundled_icon_path
from app.theme import APP_STYLESHEET
from app.fonts import body_font_family, load_local_fonts, print_font_report
from app.ui import MainWindow
from app.version import APP_DISPLAY_NAME


def _set_windows_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "KickTrack.KickbaseAnalytics"
        )
    except Exception:
        pass


def _force_windows_window_icon(window) -> None:
    """Set both native Win32 title-bar icons from the bundled .ico.

    Qt normally handles this, but WM_SETICON makes the result deterministic on
    Windows even when the Python executable has its own generic icon.
    """
    if sys.platform != "win32":
        return

    path = bundled_icon_path()
    if not path.exists():
        return

    try:
        user32 = ctypes.windll.user32
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x0010
        LR_DEFAULTSIZE = 0x0040
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1

        hicon_small = user32.LoadImageW(
            None,
            str(path),
            IMAGE_ICON,
            16,
            16,
            LR_LOADFROMFILE,
        )
        hicon_big = user32.LoadImageW(
            None,
            str(path),
            IMAGE_ICON,
            32,
            32,
            LR_LOADFROMFILE,
        )

        hwnd = int(window.winId())
        if hicon_small:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
        if hicon_big:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
    except Exception:
        pass


def main() -> int:
    _set_windows_app_id()

    app = QApplication(sys.argv)
    app.setApplicationName("KickTrack")
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    font_report = load_local_fonts()
    print_font_report(font_report)
    app.setFont(QFont(body_font_family()))
    app.setStyleSheet(APP_STYLESHEET)

    icon = app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    window = MainWindow()
    if not icon.isNull():
        window.setWindowIcon(icon)

    window.show()
    _force_windows_window_icon(window)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
