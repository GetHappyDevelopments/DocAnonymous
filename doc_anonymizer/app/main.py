from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from doc_anonymizer.app.ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("DocAnonymous")
    app.setOrganizationName("DocAnonymous")
    window = MainWindow()
    window.resize(1280, 820)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
