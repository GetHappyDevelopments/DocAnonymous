from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
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
from doc_anonymizer.app.i18n import Translator
from doc_anonymizer.app.storage.project_state import ProjectStateStore


STATUS_TRANSLATION_KEYS = {
    "Nicht gescannt": "status.unscanned",
    "Scan laeuft": "status.scan_running",
    "Scan läuft": "status.scan_running",
    "Scan abgeschlossen": "status.scan_complete",
    "Fehler": "status.error",
    "Anonymisiert": "status.anonymized",
}

CATEGORY_OPTIONS = (
    "custom",
    "person",
    "company",
    "authority",
    "association",
    "group",
    "address",
    "email",
    "phone",
    "url",
    "iban",
    "reference",
)

PREVIEW_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff"}
MAX_PREVIEW_BYTES = 8 * 1024 * 1024
MAX_PREVIEW_PIXELS = 16_000_000


class ProcessingWorker(QObject):
    log_message = Signal(str)
    refresh_documents = Signal()
    finished = Signal()

    def __init__(self, action: str, jobs: list[DocumentJob], i18n: Translator) -> None:
        super().__init__()
        self.action = action
        self.jobs = jobs
        self.i18n = i18n
        self.scanner = DocumentScanner()
        self.anonymizer = DocumentAnonymizer()

    @Slot()
    def run(self) -> None:
        try:
            if self.action == "scan":
                self._scan_jobs()
            elif self.action == "anonymize":
                self._anonymize_jobs()
        finally:
            self.finished.emit()

    def _scan_jobs(self) -> None:
        for job in self.jobs:
            job.status = "Scan laeuft"
            self.refresh_documents.emit()
            try:
                self.scanner.scan(job)
                self.log_message.emit(
                    self._t("log.scan_complete", file_name=job.source_path.name, count=len(job.findings))
                )
            except Exception as exc:
                job.status = "Fehler"
                job.errors.append(str(exc))
                self.log_message.emit(self._t("log.scan_error", file_name=job.source_path.name, error=exc))

    def _anonymize_jobs(self) -> None:
        for job in self.jobs:
            try:
                self.anonymizer.anonymize(job)
                self.log_message.emit(
                    self._t("log.anonymized", output_path=job.output_path, restore_path=job.restore_package_path)
                )
            except Exception as exc:
                job.status = "Fehler"
                job.errors.append(str(exc))
                self.log_message.emit(self._t("log.anonymize_error", file_name=job.source_path.name, error=exc))

    def _t(self, key: str, **values) -> str:
        return self.i18n.text(key, **values)


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
        self.i18n = Translator()
        self._worker_thread: QThread | None = None
        self._worker: ProcessingWorker | None = None
        self._build_ui()
        self._apply_style()

    def _t(self, key: str, **values) -> str:
        return self.i18n.text(key, **values)

    def _build_ui(self) -> None:
        self.toolbar = QToolBar(self._t("toolbar.actions"))
        self.toolbar.setMovable(False)
        self.addToolBar(self.toolbar)

        add_action = QAction(self._t("action.add_files"), self)
        add_action.triggered.connect(self.add_files)
        self.toolbar.addAction(add_action)

        folder_action = QAction(self._t("action.add_folder"), self)
        folder_action.triggered.connect(self.add_folder)
        self.toolbar.addAction(folder_action)

        scan_action = QAction(self._t("action.scan"), self)
        scan_action.triggered.connect(self.scan_selected)
        self.toolbar.addAction(scan_action)

        anonymize_action = QAction(self._t("action.anonymize"), self)
        anonymize_action.triggered.connect(self.anonymize_selected)
        self.toolbar.addAction(anonymize_action)

        manual_action = QAction(self._t("action.manual_finding"), self)
        manual_action.triggered.connect(self.add_manual_finding)
        self.toolbar.addAction(manual_action)

        save_action = QAction(self._t("action.save_project"), self)
        save_action.triggered.connect(self.save_project)
        self.toolbar.addAction(save_action)

        load_action = QAction(self._t("action.load_project"), self)
        load_action.triggered.connect(self.load_project)
        self.toolbar.addAction(load_action)

        restore_action = QAction(self._t("action.restore"), self)
        restore_action.triggered.connect(self.restore_document)
        self.toolbar.addAction(restore_action)

        self.llm_toggle = QCheckBox(self._t("label.local_llm"))
        self.llm_toggle.setToolTip(self._t("tooltip.local_llm"))
        self.llm_toggle.setEnabled(False)
        self.toolbar.addWidget(self.llm_toggle)

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(12, 10, 12, 12)
        root_layout.setSpacing(10)

        splitter = QSplitter(Qt.Orientation.Vertical)
        root_layout.addWidget(splitter)

        upper = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(upper)

        self.document_table = QTableWidget(0, 5)
        self.document_table.setHorizontalHeaderLabels(
            [
                self._t("table.documents.file"),
                self._t("table.documents.type"),
                self._t("table.documents.size"),
                self._t("table.documents.status"),
                self._t("table.documents.path"),
            ]
        )
        self.document_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.document_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.document_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.document_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.document_table.itemSelectionChanged.connect(self._document_selection_changed)
        upper.addWidget(self._wrap(self._t("section.documents"), self.document_table))

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(8)
        self.summary = QLabel(self._t("message.no_file_selected"))
        self.summary.setWordWrap(True)
        side_layout.addWidget(self._wrap(self._t("section.status"), self.summary))

        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        side_layout.addWidget(self._wrap(self._t("section.preview"), self.preview))

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        side_layout.addWidget(self._wrap(self._t("section.log"), self.log))
        upper.addWidget(side)
        upper.setSizes([900, 360])

        review_tabs = QTabWidget()

        findings_panel = QWidget()
        findings_layout = QVBoxLayout(findings_panel)
        findings_layout.setContentsMargins(0, 0, 0, 0)
        filters = QHBoxLayout()
        self.category_filter = QComboBox()
        self.category_filter.addItem(self._t("filter.category.all"), None)
        self.category_filter.currentTextChanged.connect(self._apply_finding_filter)
        self.active_filter = QComboBox()
        self.active_filter.addItem(self._t("filter.active.all"), "all")
        self.active_filter.addItem(self._t("filter.active.active"), "active")
        self.active_filter.addItem(self._t("filter.active.inactive"), "inactive")
        self.active_filter.currentTextChanged.connect(self._apply_finding_filter)
        self.confidence_filter = QComboBox()
        self.confidence_filter.addItem(self._t("filter.confidence.all"), "all")
        self.confidence_filter.addItem("< 0.70", "lt_070")
        self.confidence_filter.addItem("< 0.85", "lt_085")
        self.confidence_filter.currentTextChanged.connect(self._apply_finding_filter)
        enable_all = QPushButton(self._t("bulk.enable_all"))
        enable_all.clicked.connect(lambda: self._set_all_findings(True))
        disable_all = QPushButton(self._t("bulk.disable_all"))
        disable_all.clicked.connect(lambda: self._set_all_findings(False))
        correct_all = QPushButton(self._t("bulk.correct_all"))
        correct_all.clicked.connect(lambda: self._set_all_review_state("correct", True))
        correct_none = QPushButton(self._t("bulk.correct_none"))
        correct_none.clicked.connect(lambda: self._set_all_review_state("correct", False))
        incorrect_all = QPushButton(self._t("bulk.incorrect_all"))
        incorrect_all.clicked.connect(lambda: self._set_all_review_state("incorrect", True))
        incorrect_none = QPushButton(self._t("bulk.incorrect_none"))
        incorrect_none.clicked.connect(lambda: self._set_all_review_state("incorrect", False))
        for widget in (
            self.category_filter,
            self.active_filter,
            self.confidence_filter,
            enable_all,
            disable_all,
            correct_all,
            correct_none,
            incorrect_all,
            incorrect_none,
        ):
            filters.addWidget(widget)
        filters.addStretch(1)
        findings_layout.addLayout(filters)

        self.findings_table = QTableWidget(0, 10)
        self.findings_table.setHorizontalHeaderLabels(
            [
                self._t("table.findings.active"),
                self._t("table.findings.correct"),
                self._t("table.findings.incorrect"),
                self._t("table.findings.original"),
                self._t("table.findings.replacement"),
                self._t("table.findings.category"),
                self._t("table.findings.subtype"),
                self._t("table.findings.source"),
                self._t("table.findings.confidence"),
                self._t("table.findings.occurrences"),
            ]
        )
        self.findings_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.findings_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.findings_table.itemChanged.connect(self._finding_item_changed)
        self.findings_table.itemSelectionChanged.connect(self._preview_selected_finding)
        findings_layout.addWidget(self.findings_table)
        review_tabs.addTab(findings_panel, self._t("tab.findings"))

        images_panel = QWidget()
        images_layout = QVBoxLayout(images_panel)
        images_layout.setContentsMargins(0, 0, 0, 0)
        image_actions = QHBoxLayout()
        keep_all_images = QPushButton(self._t("bulk.keep_all_images"))
        keep_all_images.clicked.connect(lambda: self._set_all_images_keep(True))
        remove_all_images = QPushButton(self._t("bulk.remove_all_images"))
        remove_all_images.clicked.connect(lambda: self._set_all_images_keep(False))
        image_actions.addWidget(keep_all_images)
        image_actions.addWidget(remove_all_images)
        image_actions.addStretch(1)
        images_layout.addLayout(image_actions)

        self.images_table = QTableWidget(0, 6)
        self.images_table.setHorizontalHeaderLabels(
            [
                self._t("table.images.keep"),
                self._t("table.images.preview"),
                self._t("table.images.file"),
                self._t("table.images.type"),
                self._t("table.images.size"),
                self._t("table.images.location"),
            ]
        )
        self.images_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.images_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.images_table.itemChanged.connect(self._image_item_changed)
        images_layout.addWidget(self.images_table)
        review_tabs.addTab(images_panel, self._t("tab.images"))

        splitter.addWidget(self._wrap(self._t("section.review"), review_tabs))
        splitter.setSizes([330, 450])

        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(self._t("status.ready"))

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
        filters = self._t("dialog.documents.filter")
        files, _ = QFileDialog.getOpenFileNames(self, self._t("dialog.documents.title"), "", filters)
        self._add_paths([Path(file) for file in files])

    def add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, self._t("dialog.folder.title"))
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
        self._log(self._t("log.added_documents", count=added))

    def scan_selected(self) -> None:
        jobs = self._selected_jobs()
        if not jobs:
            self._warn(self._t("message.select_one_document"))
            return
        self._start_processing("scan", jobs)

    def anonymize_selected(self) -> None:
        jobs = self._selected_jobs()
        if not jobs:
            self._warn(self._t("message.select_one_document"))
            return
        if any(not job.findings for job in jobs):
            answer = self._question(
                self._t("dialog.no_findings.title"),
                self._t("dialog.no_findings.message"),
            )
            if not answer:
                return
        self._start_processing("anonymize", jobs)

    def save_project(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            self._t("dialog.save_project.title"),
            "",
            self._t("dialog.save_project.filter"),
        )
        if not path:
            return
        if not path.lower().endswith(".docanon"):
            path = f"{path}.docanon"
        self.project_store.save(Path(path), self.jobs)
        self._log(self._t("log.project_saved", path=path))

    def load_project(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            self._t("dialog.load_project.title"),
            "",
            self._t("dialog.load_project.filter"),
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
        self._log(self._t("log.project_loaded", path=path))

    def restore_document(self) -> None:
        job = self.current_job
        if not job:
            self._warn(self._t("message.restore_needs_document"))
            return
        anonymized = job.output_path
        restore_package = job.restore_package_path
        if not anonymized or not anonymized.exists():
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                self._t("dialog.anonymized_file.title"),
                "",
                self._t("dialog.documents.filter"),
            )
            anonymized = Path(file_path) if file_path else None
        if not restore_package or not restore_package.exists():
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                self._t("dialog.restore_package.title"),
                "",
                self._t("dialog.restore_package.filter"),
            )
            restore_package = Path(file_path) if file_path else None
        if not anonymized or not restore_package:
            return
        output, _ = QFileDialog.getSaveFileName(
            self,
            self._t("dialog.restore_output.title"),
            str(anonymized.with_name(f"{anonymized.stem}.restored{anonymized.suffix}")),
        )
        if not output:
            return
        restored = self.restorer.restore(anonymized, restore_package, Path(output))
        self._log(self._t("log.restored", path=restored))

    def add_manual_finding(self) -> None:
        job = self.current_job
        if not job:
            self._warn(self._t("message.no_document_selected"))
            return
        dialog = ManualFindingDialog(self.i18n, self)
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
                self._status_label(job.status),
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
        if job:
            job.findings = self._sorted_findings(job.findings)
            findings = job.findings
        self._update_category_filter()
        self.findings_table.setRowCount(len(findings))
        for row, finding in enumerate(findings):
            active = QTableWidgetItem()
            active.setFlags(active.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            active.setCheckState(Qt.CheckState.Checked if finding.enabled else Qt.CheckState.Unchecked)
            self.findings_table.setItem(row, 0, active)

            correct = QTableWidgetItem()
            correct.setFlags(correct.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            correct.setCheckState(Qt.CheckState.Checked if finding.correct else Qt.CheckState.Unchecked)
            self.findings_table.setItem(row, 1, correct)

            incorrect = QTableWidgetItem()
            incorrect.setFlags(incorrect.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            incorrect.setCheckState(Qt.CheckState.Checked if finding.incorrect else Qt.CheckState.Unchecked)
            self.findings_table.setItem(row, 2, incorrect)

            values = [
                finding.original_text,
                finding.replacement_text,
                finding.category,
                finding.sub_category or "",
                finding.source,
                f"{finding.confidence:.2f}",
                str(finding.occurrence_count),
            ]
            for col, value in enumerate(values, start=3):
                item = QTableWidgetItem(value)
                if col in (3, 4, 5, 6):
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
            job.errors.append(self._t("message.image_gallery_unavailable", error=exc))

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
            if package_path and self._can_load_preview(package_path, image.width, image.height):
                data = openxml_image_bytes(job.source_path, package_path)
                pixmap = self._preview_pixmap(data) if data and len(data) <= MAX_PREVIEW_BYTES else QPixmap()
                if not pixmap.isNull():
                    preview.setData(
                        Qt.ItemDataRole.DecorationRole,
                        pixmap.scaled(
                            96,
                            64,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        ),
                    )
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
            if finding.enabled:
                finding.incorrect = False
        elif col == 1:
            finding.correct = item.checkState() == Qt.CheckState.Checked
            if finding.correct:
                finding.incorrect = False
        elif col == 2:
            finding.incorrect = item.checkState() == Qt.CheckState.Checked
            if finding.incorrect:
                finding.correct = False
                finding.enabled = False
        elif col == 3:
            finding.original_text = item.text()
        elif col == 4:
            finding.replacement_text = item.text()
        elif col == 5:
            finding.category = item.text() or "custom"
        elif col == 6:
            finding.sub_category = item.text() or None
        self._refresh_summary()
        if col in (0, 1, 2):
            self._refresh_findings()
        else:
            self._apply_finding_filter()

    def _set_all_findings(self, enabled: bool) -> None:
        if not self.current_job:
            return
        for finding in self.current_job.findings:
            if self._finding_matches_current_filter(finding):
                finding.enabled = enabled and not finding.incorrect
        self._refresh_findings()

    def _set_all_review_state(self, field: str, checked: bool) -> None:
        if not self.current_job:
            return
        for finding in self.current_job.findings:
            if not self._finding_matches_current_filter(finding):
                continue
            if field == "correct":
                finding.correct = checked
                if checked:
                    finding.incorrect = False
            elif field == "incorrect":
                finding.incorrect = checked
                if checked:
                    finding.correct = False
                    finding.enabled = False
        self._refresh_findings()

    @staticmethod
    def _sorted_findings(findings: list[Finding]) -> list[Finding]:
        return sorted(findings, key=lambda finding: (finding.incorrect, finding.original_text.casefold()))

    def _update_category_filter(self) -> None:
        current = self.category_filter.currentData() if hasattr(self, "category_filter") else None
        categories = sorted({finding.category for finding in self.current_job.findings}) if self.current_job else []
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem(self._t("filter.category.all"), None)
        for category in categories:
            self.category_filter.addItem(self._category_label(category), category)
        index = self.category_filter.findData(current)
        self.category_filter.setCurrentIndex(index if index >= 0 else 0)
        self.category_filter.blockSignals(False)

    def _apply_finding_filter(self) -> None:
        if not self.current_job:
            return
        for row, finding in enumerate(self.current_job.findings):
            self.findings_table.setRowHidden(row, not self._finding_matches_current_filter(finding))

    def _finding_matches_current_filter(self, finding: Finding) -> bool:
        category = self.category_filter.currentData()
        active = self.active_filter.currentData()
        confidence = self.confidence_filter.currentData()
        if category is not None and finding.category != category:
            return False
        if active == "active" and not finding.enabled:
            return False
        if active == "inactive" and finding.enabled:
            return False
        if confidence == "lt_070" and finding.confidence >= 0.70:
            return False
        if confidence == "lt_085" and finding.confidence >= 0.85:
            return False
        return True

    def _preview_selected_finding(self) -> None:
        if not self.current_job:
            self.preview.clear()
            return
        rows = self.findings_table.selectionModel().selectedRows()
        if not rows:
            self.preview.setPlainText(self._t("message.no_finding_selected"))
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
            snippets.append(self._t("message.preview_unavailable", error=exc))
        self.preview.setPlainText("\n\n".join(snippets) if snippets else self._t("message.no_context"))

    def _refresh_summary(self) -> None:
        job = self.current_job
        if not job:
            self.summary.setText(self._t("message.no_file_selected"))
            return
        active = len([f for f in job.findings if f.enabled])
        self._ensure_image_choices(job)
        removed_images = len([img for img in job.image_replacements if not img.keep])
        kept_images = len(job.image_replacements) - removed_images
        self.summary.setText(
            f"{job.source_path.name}\n"
            f"{self._t('summary.status', status=self._status_label(job.status))}\n"
            f"{self._t('summary.findings', total=len(job.findings), active=active)}\n"
            f"{self._t('summary.images', removed=removed_images, kept=kept_images)}\n"
            f"{self._t('summary.output', path=job.output_path or '-')}\n"
            f"{self._t('summary.restore', path=job.restore_package_path or '-')}"
        )

    def _log(self, text: str) -> None:
        self.log.append(text)
        self.statusBar().showMessage(text, 7000)

    def _start_processing(self, action: str, jobs: list[DocumentJob]) -> None:
        if self._worker_thread and self._worker_thread.isRunning():
            return
        self.toolbar.setEnabled(False)
        if self.centralWidget():
            self.centralWidget().setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self._worker_thread = QThread(self)
        self._worker = ProcessingWorker(action, jobs, self.i18n)
        self._worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self._worker.run)
        self._worker.log_message.connect(self._log)
        self._worker.refresh_documents.connect(self._refresh_documents)
        self._worker.finished.connect(self._processing_finished)
        self._worker.finished.connect(self._worker_thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.start()

    def _processing_finished(self) -> None:
        QApplication.restoreOverrideCursor()
        if self.centralWidget():
            self.centralWidget().setEnabled(True)
        self.toolbar.setEnabled(True)
        self._refresh_documents()
        self._refresh_findings()
        self._refresh_images()
        self._worker = None
        self._worker_thread = None

    def _warn(self, text: str) -> None:
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Warning)
        message.setWindowTitle("DocAnonymous")
        message.setText(text)
        message.setStandardButtons(QMessageBox.StandardButton.Ok)
        ok_button = message.button(QMessageBox.StandardButton.Ok)
        if ok_button:
            ok_button.setText(self._t("button.ok"))
        message.exec()

    def _question(self, title: str, text: str) -> bool:
        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Question)
        message.setWindowTitle(title)
        message.setText(text)
        message.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        message.setDefaultButton(QMessageBox.StandardButton.No)
        yes_button = message.button(QMessageBox.StandardButton.Yes)
        no_button = message.button(QMessageBox.StandardButton.No)
        if yes_button:
            yes_button.setText(self._t("button.yes"))
        if no_button:
            no_button.setText(self._t("button.no"))
        return message.exec() == QMessageBox.StandardButton.Yes

    def _status_label(self, status: str) -> str:
        return self._t(STATUS_TRANSLATION_KEYS.get(status, status))

    def _category_label(self, category: str) -> str:
        return self._t(f"category.{category}")

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

    @staticmethod
    def _can_load_preview(package_path: str, width: float | None, height: float | None) -> bool:
        if Path(package_path).suffix.lower() not in PREVIEW_IMAGE_SUFFIXES:
            return False
        if width and height and width * height > MAX_PREVIEW_PIXELS:
            return False
        return True

    @staticmethod
    def _preview_pixmap(data: bytes) -> QPixmap:
        pixmap = QPixmap()
        pixmap.loadFromData(data)
        return pixmap


class ManualFindingDialog(QDialog):
    def __init__(self, i18n: Translator, parent=None) -> None:
        super().__init__(parent)
        self.i18n = i18n
        self.setWindowTitle(self._t("dialog.manual_finding.title"))
        self.original = QLineEdit()
        self.replacement = QLineEdit()
        self.category = QComboBox()
        for category in CATEGORY_OPTIONS:
            self.category.addItem(self._t(f"category.{category}"), category)
        self.sub_category = QLineEdit()
        self.sub_category.setPlaceholderText(self._t("placeholder.sub_category"))

        form = QFormLayout()
        form.addRow(self._t("field.original"), self.original)
        form.addRow(self._t("field.replacement"), self.replacement)
        form.addRow(self._t("field.category"), self.category)
        form.addRow(self._t("field.sub_category"), self.sub_category)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if ok_button:
            ok_button.setText(self._t("button.ok"))
        if cancel_button:
            cancel_button.setText(self._t("button.cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str, str, str | None]:
        return (
            self.original.text().strip(),
            self.replacement.text().strip(),
            self.category.currentData(),
            self.sub_category.text().strip() or None,
        )

    def _t(self, key: str, **values) -> str:
        return self.i18n.text(key, **values)
