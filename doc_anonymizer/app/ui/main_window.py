from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from doc_anonymizer.app.core.anonymizer import DocumentAnonymizer
from doc_anonymizer.app.core.models import DocumentJob, Finding, SUPPORTED_EXTENSIONS
from doc_anonymizer.app.core.placeholder_factory import PlaceholderFactory
from doc_anonymizer.app.core.restorer import DocumentRestorer
from doc_anonymizer.app.core.scanner import DocumentScanner
from doc_anonymizer.app.formats import get_handler
from doc_anonymizer.app.formats.common import collect_openxml_images, openxml_image_bytes
from doc_anonymizer.app.storage.project_state import ProjectStateStore


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DocAnonymous")
        self.jobs: list[DocumentJob] = []
        self.current_job: DocumentJob | None = None
        self.scanner = DocumentScanner()
        self.anonymizer = DocumentAnonymizer()
        self.restorer = DocumentRestorer()
        self.project_store = ProjectStateStore()
        self._build_ui()
        self._apply_style()

    def _build_ui(self) -> None:
        toolbar = QToolBar("Aktionen")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        add_action = QAction("Dateien", self)
        add_action.triggered.connect(self.add_files)
        toolbar.addAction(add_action)

        folder_action = QAction("Ordner", self)
        folder_action.triggered.connect(self.add_folder)
        toolbar.addAction(folder_action)

        scan_action = QAction("Scannen", self)
        scan_action.triggered.connect(self.scan_selected)
        toolbar.addAction(scan_action)

        anonymize_action = QAction("Anonymisieren", self)
        anonymize_action.triggered.connect(self.anonymize_selected)
        toolbar.addAction(anonymize_action)

        manual_action = QAction("Finding", self)
        manual_action.triggered.connect(self.add_manual_finding)
        toolbar.addAction(manual_action)

        save_action = QAction("Projekt speichern", self)
        save_action.triggered.connect(self.save_project)
        toolbar.addAction(save_action)

        load_action = QAction("Projekt laden", self)
        load_action.triggered.connect(self.load_project)
        toolbar.addAction(load_action)

        restore_action = QAction("Restore", self)
        restore_action.triggered.connect(self.restore_document)
        toolbar.addAction(restore_action)

        self.llm_toggle = QCheckBox("Lokales LLM")
        self.llm_toggle.setToolTip("Vorbereitet, aktuell ohne aktive Backend-Anbindung.")
        self.llm_toggle.setEnabled(False)
        toolbar.addWidget(self.llm_toggle)

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(12, 10, 12, 12)
        root_layout.setSpacing(10)

        splitter = QSplitter(Qt.Orientation.Vertical)
        root_layout.addWidget(splitter)

        upper = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(upper)

        self.document_table = QTableWidget(0, 5)
        self.document_table.setHorizontalHeaderLabels(["Datei", "Typ", "Groesse", "Status", "Pfad"])
        self.document_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.document_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.document_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.document_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.document_table.itemSelectionChanged.connect(self._document_selection_changed)
        upper.addWidget(self._wrap("Dokumente", self.document_table))

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(8)
        self.summary = QLabel("Keine Datei ausgewaehlt")
        self.summary.setWordWrap(True)
        side_layout.addWidget(self._wrap("Status", self.summary))

        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        side_layout.addWidget(self._wrap("Vorschau", self.preview))

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        side_layout.addWidget(self._wrap("Protokoll", self.log))
        upper.addWidget(side)
        upper.setSizes([900, 360])

        review_tabs = QTabWidget()

        findings_panel = QWidget()
        findings_layout = QVBoxLayout(findings_panel)
        findings_layout.setContentsMargins(0, 0, 0, 0)
        filters = QHBoxLayout()
        self.category_filter = QComboBox()
        self.category_filter.addItem("Alle Kategorien")
        self.category_filter.currentTextChanged.connect(self._apply_finding_filter)
        self.active_filter = QComboBox()
        self.active_filter.addItems(["Alle", "Aktiv", "Inaktiv"])
        self.active_filter.currentTextChanged.connect(self._apply_finding_filter)
        self.confidence_filter = QComboBox()
        self.confidence_filter.addItems(["Alle Sicherheiten", "< 0.70", "< 0.85"])
        self.confidence_filter.currentTextChanged.connect(self._apply_finding_filter)
        enable_all = QPushButton("Alle aktiv")
        enable_all.clicked.connect(lambda: self._set_all_findings(True))
        disable_all = QPushButton("Alle inaktiv")
        disable_all.clicked.connect(lambda: self._set_all_findings(False))
        for widget in (self.category_filter, self.active_filter, self.confidence_filter, enable_all, disable_all):
            filters.addWidget(widget)
        filters.addStretch(1)
        findings_layout.addLayout(filters)

        self.findings_table = QTableWidget(0, 8)
        self.findings_table.setHorizontalHeaderLabels(
            ["Aktiv", "Original", "Ersatz", "Kategorie", "Subtyp", "Quelle", "Sicherheit", "Vorkommen"]
        )
        self.findings_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.findings_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.findings_table.itemChanged.connect(self._finding_item_changed)
        self.findings_table.itemSelectionChanged.connect(self._preview_selected_finding)
        findings_layout.addWidget(self.findings_table)
        review_tabs.addTab(findings_panel, "Findings")

        images_panel = QWidget()
        images_layout = QVBoxLayout(images_panel)
        images_layout.setContentsMargins(0, 0, 0, 0)
        image_actions = QHBoxLayout()
        keep_all_images = QPushButton("Alle behalten")
        keep_all_images.clicked.connect(lambda: self._set_all_images_keep(True))
        remove_all_images = QPushButton("Alle entfernen")
        remove_all_images.clicked.connect(lambda: self._set_all_images_keep(False))
        image_actions.addWidget(keep_all_images)
        image_actions.addWidget(remove_all_images)
        image_actions.addStretch(1)
        images_layout.addLayout(image_actions)

        self.images_table = QTableWidget(0, 6)
        self.images_table.setHorizontalHeaderLabels(["Behalten", "Vorschau", "Datei", "Typ", "Groesse", "Ort"])
        self.images_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.images_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.images_table.itemChanged.connect(self._image_item_changed)
        images_layout.addWidget(self.images_table)
        review_tabs.addTab(images_panel, "Bilder")

        splitter.addWidget(self._wrap("Pruefen und bearbeiten", review_tabs))
        splitter.setSizes([330, 450])

        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Bereit")

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background: #f6f7f8; }
            QGroupBox {
                border: 1px solid #d4d8dd;
                border-radius: 6px;
                margin-top: 18px;
                padding: 10px;
                background: #ffffff;
                font-weight: 600;
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QTableWidget {
                gridline-color: #e3e6ea;
                selection-background-color: #cfe2ff;
                selection-color: #111827;
                alternate-background-color: #f9fafb;
            }
            QHeaderView::section {
                background: #eef1f4;
                border: 0;
                border-right: 1px solid #d4d8dd;
                padding: 6px;
                font-weight: 600;
            }
            QToolBar {
                background: #ffffff;
                border-bottom: 1px solid #d4d8dd;
                spacing: 6px;
                padding: 6px;
            }
            QPushButton, QToolButton {
                min-height: 28px;
                padding: 4px 10px;
            }
            QTextEdit, QLineEdit, QComboBox {
                border: 1px solid #cfd6dd;
                border-radius: 4px;
                padding: 4px;
                background: #ffffff;
            }
            """
        )

    def _wrap(self, title: str, widget: QWidget) -> QGroupBox:
        box = QGroupBox(title)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(widget)
        return box

    def add_files(self) -> None:
        filters = "Dokumente (*.docx *.xlsx *.pptx *.pdf *.txt)"
        files, _ = QFileDialog.getOpenFileNames(self, "Dokumente auswaehlen", "", filters)
        self._add_paths([Path(file) for file in files])

    def add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Ordner auswaehlen")
        if not folder:
            return
        paths = [p for p in Path(folder).rglob("*") if p.suffix.lower() in SUPPORTED_EXTENSIONS]
        self._add_paths(paths)

    def _add_paths(self, paths: list[Path]) -> None:
        known = {job.source_path.resolve() for job in self.jobs}
        added = 0
        for path in paths:
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS or path.resolve() in known:
                continue
            self.jobs.append(DocumentJob(source_path=path))
            added += 1
        self._refresh_documents()
        self._log(f"{added} Dokument(e) hinzugefuegt.")

    def scan_selected(self) -> None:
        jobs = self._selected_jobs()
        if not jobs:
            self._warn("Bitte mindestens ein Dokument auswaehlen.")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for job in jobs:
                job.status = "Scan laeuft"
                self._refresh_documents()
                try:
                    self.scanner.scan(job)
                    self._log(f"Scan abgeschlossen: {job.source_path.name} ({len(job.findings)} Findings)")
                except Exception as exc:
                    job.status = "Fehler"
                    job.errors.append(str(exc))
                    self._log(f"Fehler beim Scan von {job.source_path.name}: {exc}")
        finally:
            QApplication.restoreOverrideCursor()
        self._refresh_documents()
        self._refresh_findings()
        self._refresh_images()

    def anonymize_selected(self) -> None:
        jobs = self._selected_jobs()
        if not jobs:
            self._warn("Bitte mindestens ein Dokument auswaehlen.")
            return
        if any(not job.findings for job in jobs):
            answer = QMessageBox.question(
                self,
                "Ohne Findings fortfahren?",
                "Mindestens ein Dokument hat keine Scan-Ergebnisse. Trotzdem Kopien erzeugen?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for job in jobs:
                try:
                    self.anonymizer.anonymize(job)
                    self._log(f"Anonymisiert: {job.output_path} | Restore: {job.restore_package_path}")
                except Exception as exc:
                    job.status = "Fehler"
                    job.errors.append(str(exc))
                    self._log(f"Fehler beim Anonymisieren von {job.source_path.name}: {exc}")
        finally:
            QApplication.restoreOverrideCursor()
        self._refresh_documents()
        self._refresh_findings()
        self._refresh_images()

    def save_project(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Projekt speichern", "", "DocAnonymous Projekt (*.docanon)")
        if not path:
            return
        if not path.lower().endswith(".docanon"):
            path = f"{path}.docanon"
        self.project_store.save(Path(path), self.jobs)
        self._log(f"Projekt gespeichert: {path}")

    def load_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Projekt laden",
            "",
            "DocAnonymous Projekt (*.docanon);;Legacy Projekt (*.docanon.json);;Alle Dateien (*)",
        )
        if not path:
            return
        self.jobs = self.project_store.load(Path(path))
        self.current_job = self.jobs[0] if self.jobs else None
        self._refresh_documents()
        if self.jobs:
            self.document_table.selectRow(0)
        self._refresh_findings()
        self._refresh_images()
        self._log(f"Projekt geladen: {path}")

    def restore_document(self) -> None:
        job = self.current_job
        if not job:
            self._warn("Bitte zuerst ein anonymisiertes Dokument auswaehlen oder ein Projekt mit Restore-Pfad laden.")
            return
        anonymized = job.output_path
        restore_package = job.restore_package_path
        if not anonymized or not anonymized.exists():
            file_path, _ = QFileDialog.getOpenFileName(self, "Anonymisierte Datei auswaehlen", "", "Dokumente (*.docx *.xlsx *.pptx *.pdf *.txt)")
            anonymized = Path(file_path) if file_path else None
        if not restore_package or not restore_package.exists():
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "Restore-Paket auswaehlen",
                "",
                "Restore Paket (*.dam);;Legacy Restore Paket (*.aim *.zip);;Alle Dateien (*)",
            )
            restore_package = Path(file_path) if file_path else None
        if not anonymized or not restore_package:
            return
        output, _ = QFileDialog.getSaveFileName(
            self,
            "Wiederhergestellte Datei speichern",
            str(anonymized.with_name(f"{anonymized.stem}.restored{anonymized.suffix}")),
        )
        if not output:
            return
        restored = self.restorer.restore(anonymized, restore_package, Path(output))
        self._log(f"Wiederhergestellt: {restored}")

    def add_manual_finding(self) -> None:
        job = self.current_job
        if not job:
            self._warn("Bitte zuerst ein Dokument auswaehlen.")
            return
        dialog = ManualFindingDialog(self)
        if dialog.exec() != ManualFindingDialog.DialogCode.Accepted:
            return
        original, replacement, category, sub_category = dialog.values()
        if not original:
            return
        if not replacement:
            factory = PlaceholderFactory()
            for existing in job.findings:
                factory.replacement_for(existing.original_text, existing.category, existing.sub_category)
            replacement = factory.replacement_for(original, category, sub_category)
        job.findings.append(
            Finding(
                original_text=original,
                replacement_text=replacement,
                category=category,
                sub_category=sub_category or None,
                confidence=1.0,
                source="manual",
            )
        )
        self._update_category_filter()
        self._refresh_findings()

    def _document_selection_changed(self) -> None:
        rows = self.document_table.selectionModel().selectedRows()
        self.current_job = self.jobs[rows[0].row()] if rows else None
        self._refresh_findings()
        self._refresh_images()

    def _selected_jobs(self) -> list[DocumentJob]:
        rows = self.document_table.selectionModel().selectedRows()
        return [self.jobs[row.row()] for row in rows]

    def _refresh_documents(self) -> None:
        self.document_table.setRowCount(len(self.jobs))
        for row, job in enumerate(self.jobs):
            values = [
                job.source_path.name,
                job.format.upper(),
                self._size_label(job.source_path),
                job.status,
                str(job.source_path),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if job.status == "Fehler":
                    item.setBackground(QColor("#ffe2e2"))
                elif job.status == "Anonymisiert":
                    item.setBackground(QColor("#e6f4ea"))
                self.document_table.setItem(row, col, item)
        self._refresh_summary()

    def _refresh_findings(self) -> None:
        self.findings_table.blockSignals(True)
        job = self.current_job
        findings = job.findings if job else []
        self._update_category_filter()
        self.findings_table.setRowCount(len(findings))
        for row, finding in enumerate(findings):
            active = QTableWidgetItem()
            active.setFlags(active.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            active.setCheckState(Qt.CheckState.Checked if finding.enabled else Qt.CheckState.Unchecked)
            self.findings_table.setItem(row, 0, active)
            values = [
                finding.original_text,
                finding.replacement_text,
                finding.category,
                finding.sub_category or "",
                finding.source,
                f"{finding.confidence:.2f}",
                str(finding.occurrence_count),
            ]
            for col, value in enumerate(values, start=1):
                item = QTableWidgetItem(value)
                if col in (1, 2, 3, 4):
                    item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
                else:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.findings_table.setItem(row, col, item)
        self.findings_table.blockSignals(False)
        self._apply_finding_filter()
        self._refresh_summary()
        self._preview_selected_finding()

    def _ensure_image_choices(self, job: DocumentJob) -> None:
        if job.image_replacements or job.source_path.suffix.lower() not in {".docx", ".xlsx", ".pptx"}:
            return
        try:
            job.image_replacements = collect_openxml_images(job.source_path)
        except Exception as exc:
            job.errors.append(f"Bild-Galerie nicht verfuegbar: {exc}")

    def _refresh_images(self) -> None:
        self.images_table.blockSignals(True)
        job = self.current_job
        if not job:
            self.images_table.setRowCount(0)
            self.images_table.blockSignals(False)
            self._refresh_summary()
            return
        self._ensure_image_choices(job)
        images = job.image_replacements
        self.images_table.setRowCount(len(images))
        self.images_table.setIconSize(QPixmap(96, 64).size())
        for row, image in enumerate(images):
            keep = QTableWidgetItem()
            keep.setFlags(keep.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            keep.setCheckState(Qt.CheckState.Checked if image.keep else Qt.CheckState.Unchecked)
            self.images_table.setItem(row, 0, keep)

            preview = QTableWidgetItem()
            package_path = image.locations[0].extra.get("package_path") if image.locations else ""
            if package_path:
                data = openxml_image_bytes(job.source_path, package_path)
                pixmap = QPixmap()
                if data and pixmap.loadFromData(data):
                    preview.setData(Qt.ItemDataRole.DecorationRole, pixmap.scaled(96, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            preview.setFlags(preview.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.images_table.setItem(row, 1, preview)

            values = [
                image.original_file_name,
                image.original_mime_type,
                self._image_size_label(image.width, image.height),
                package_path or "-",
            ]
            for col, value in enumerate(values, start=2):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.images_table.setItem(row, col, item)
            self.images_table.setRowHeight(row, 72)
        self.images_table.blockSignals(False)
        self._refresh_summary()

    def _image_item_changed(self, item: QTableWidgetItem) -> None:
        if not self.current_job or item.column() != 0 or item.row() >= len(self.current_job.image_replacements):
            return
        self.current_job.image_replacements[item.row()].keep = item.checkState() == Qt.CheckState.Checked
        self._refresh_summary()

    def _set_all_images_keep(self, keep: bool) -> None:
        if not self.current_job:
            return
        self._ensure_image_choices(self.current_job)
        for image in self.current_job.image_replacements:
            image.keep = keep
        self._refresh_images()

    def _finding_item_changed(self, item: QTableWidgetItem) -> None:
        if not self.current_job or item.row() >= len(self.current_job.findings):
            return
        finding = self.current_job.findings[item.row()]
        col = item.column()
        if col == 0:
            finding.enabled = item.checkState() == Qt.CheckState.Checked
        elif col == 1:
            finding.original_text = item.text()
        elif col == 2:
            finding.replacement_text = item.text()
        elif col == 3:
            finding.category = item.text() or "custom"
        elif col == 4:
            finding.sub_category = item.text() or None
        self._refresh_summary()
        self._apply_finding_filter()

    def _set_all_findings(self, enabled: bool) -> None:
        if not self.current_job:
            return
        for finding in self.current_job.findings:
            if self._finding_matches_current_filter(finding):
                finding.enabled = enabled
        self._refresh_findings()

    def _update_category_filter(self) -> None:
        current = self.category_filter.currentText() if hasattr(self, "category_filter") else "Alle Kategorien"
        categories = sorted({finding.category for finding in self.current_job.findings}) if self.current_job else []
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem("Alle Kategorien")
        self.category_filter.addItems(categories)
        index = self.category_filter.findText(current)
        self.category_filter.setCurrentIndex(index if index >= 0 else 0)
        self.category_filter.blockSignals(False)

    def _apply_finding_filter(self) -> None:
        if not self.current_job:
            return
        for row, finding in enumerate(self.current_job.findings):
            self.findings_table.setRowHidden(row, not self._finding_matches_current_filter(finding))

    def _finding_matches_current_filter(self, finding: Finding) -> bool:
        category = self.category_filter.currentText()
        active = self.active_filter.currentText()
        confidence = self.confidence_filter.currentText()
        if category != "Alle Kategorien" and finding.category != category:
            return False
        if active == "Aktiv" and not finding.enabled:
            return False
        if active == "Inaktiv" and finding.enabled:
            return False
        if confidence == "< 0.70" and finding.confidence >= 0.70:
            return False
        if confidence == "< 0.85" and finding.confidence >= 0.85:
            return False
        return True

    def _preview_selected_finding(self) -> None:
        if not self.current_job:
            self.preview.clear()
            return
        rows = self.findings_table.selectionModel().selectedRows()
        if not rows:
            self.preview.setPlainText("Kein Finding ausgewaehlt.")
            return
        row = rows[0].row()
        if row >= len(self.current_job.findings):
            return
        finding = self.current_job.findings[row]
        snippets: list[str] = []
        try:
            for chunk in get_handler(self.current_job.source_path).extract_text(self.current_job.source_path):
                idx = chunk.text.casefold().find(finding.original_text.casefold())
                if idx < 0:
                    continue
                start = max(0, idx - 120)
                end = min(len(chunk.text), idx + len(finding.original_text) + 120)
                before = chunk.text[start:idx]
                hit = chunk.text[idx : idx + len(finding.original_text)]
                after = chunk.text[idx + len(finding.original_text) : end]
                snippets.append(f"[{chunk.part}]\n...{before}>> {hit} <<{after}...")
                if len(snippets) >= 5:
                    break
        except Exception as exc:
            snippets.append(f"Vorschau nicht verfuegbar: {exc}")
        self.preview.setPlainText("\n\n".join(snippets) if snippets else "Keine Kontextstelle gefunden.")

    def _refresh_summary(self) -> None:
        job = self.current_job
        if not job:
            self.summary.setText("Keine Datei ausgewaehlt")
            return
        active = len([f for f in job.findings if f.enabled])
        self._ensure_image_choices(job)
        removed_images = len([img for img in job.image_replacements if not img.keep])
        kept_images = len(job.image_replacements) - removed_images
        self.summary.setText(
            f"{job.source_path.name}\n"
            f"Status: {job.status}\n"
            f"Findings: {len(job.findings)} gesamt, {active} aktiv\n"
            f"Bilder: {removed_images} entfernen, {kept_images} behalten\n"
            f"Ausgabe: {job.output_path or '-'}\n"
            f"Restore: {job.restore_package_path or '-'}"
        )

    def _log(self, text: str) -> None:
        self.log.append(text)
        self.statusBar().showMessage(text, 7000)

    def _warn(self, text: str) -> None:
        QMessageBox.warning(self, "DocAnonymous", text)

    @staticmethod
    def _size_label(path: Path) -> str:
        try:
            size = path.stat().st_size
        except OSError:
            return "-"
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / (1024 * 1024):.1f} MB"

    @staticmethod
    def _image_size_label(width: float | None, height: float | None) -> str:
        if width and height:
            return f"{int(width)} x {int(height)} px"
        return "-"


class ManualFindingDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manuelles Finding")
        self.original = QLineEdit()
        self.replacement = QLineEdit()
        self.category = QComboBox()
        self.category.addItems(
            ["custom", "person", "company", "authority", "association", "group", "address", "email", "phone", "url", "iban", "reference"]
        )
        self.sub_category = QLineEdit()
        self.sub_category.setPlaceholderText("z. B. GmbH, AG")

        form = QFormLayout()
        form.addRow("Suchstring", self.original)
        form.addRow("Ersatz", self.replacement)
        form.addRow("Kategorie", self.category)
        form.addRow("Subtyp", self.sub_category)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str, str, str | None]:
        return (
            self.original.text().strip(),
            self.replacement.text().strip(),
            self.category.currentText(),
            self.sub_category.text().strip() or None,
        )
