from __future__ import annotations

import ctypes
import os
import sys
import time
from pathlib import Path

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from doc_anonymizer.app.ui.main_window import MainWindow


APP_NAME = "DocAnonymous"
APP_USER_MODEL_ID = "DocAnonymous.DocAnonymous"
ASSETS_PATH = Path(__file__).resolve().parent / "assets"
ICON_PATH = ASSETS_PATH / "app_icon.ico"
SPLASH_PATH = ASSETS_PATH / "splash.png"
SPLASH_MINIMUM_SECONDS = 3.0


def _set_windows_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)


def _create_splash_screen() -> QSplashScreen | None:
    if os.environ.get("DOCANONYMIZER_EXTERNAL_SPLASH") == "1":
        return None
    pixmap = QPixmap(str(SPLASH_PATH))
    if pixmap.isNull():
        return None
    screen = QApplication.primaryScreen()
    if screen:
        available = screen.availableGeometry()
        max_width = min(960, round(available.width() * 0.72))
        max_height = min(540, round(available.height() * 0.72))
        pixmap = pixmap.scaled(
            max_width,
            max_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    splash = QSplashScreen(pixmap)
    splash.show()
    QApplication.processEvents()
    return splash


def _wait_for_splash_minimum(started_at: float) -> None:
    remaining = SPLASH_MINIMUM_SECONDS - (time.monotonic() - started_at)
    if remaining <= 0:
        return
    loop = QEventLoop()
    QTimer.singleShot(round(remaining * 1000), loop.quit)
    loop.exec()


def main() -> int:
    _set_windows_app_user_model_id()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    icon = QIcon(str(ICON_PATH))
    app.setWindowIcon(icon)
    splash_started_at = time.monotonic()
    splash = _create_splash_screen()
    window = MainWindow()
    window.setWindowIcon(icon)
    window.resize(1280, 820)
    if splash:
        _wait_for_splash_minimum(splash_started_at)
    window.show()
    if splash:
        splash.finish(window)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
