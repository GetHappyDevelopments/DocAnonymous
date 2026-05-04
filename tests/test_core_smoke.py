from pathlib import Path
import zipfile

from doc_anonymizer.app.core.anonymizer import DocumentAnonymizer
from doc_anonymizer.app.core.models import DocumentJob, Finding
from doc_anonymizer.app.core.restorer import DocumentRestorer
from doc_anonymizer.app.core.scanner import DocumentScanner
from doc_anonymizer.app.formats import get_handler
from doc_anonymizer.app.storage.project_state import ProjectStateStore


def _write_minimal_text_pdf(path: Path, text: str) -> None:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 24 Tf 72 720 Td ({escaped}) Tj ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(stream.encode('latin-1'))} >>\nstream\n{stream}\nendstream".encode("latin-1"),
    ]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(data))
        data.extend(f"{index} 0 obj\n".encode("ascii"))
        data.extend(obj)
        data.extend(b"\nendobj\n")
    xref_offset = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    data.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(bytes(data))


def test_txt_scan_and_anonymize(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_text(
        "Bayer AG, Vater&Soehne GmbH, Herr Max Mustermann, test@example.com",
        encoding="utf-8",
    )
    job = DocumentJob(source)

    DocumentScanner().scan(job)
    originals = {finding.original_text for finding in job.findings}

    assert "Bayer AG" in originals
    assert "Vater&Soehne GmbH" in originals
    assert "Herr Max Mustermann" in originals
    assert "test@example.com" in originals

    DocumentAnonymizer().anonymize(job, tmp_path)

    text = job.output_path.read_text(encoding="utf-8")
    assert "Firma AG 1" in text
    assert "Firma GmbH 1" in text
    assert "Person 1" in text
    assert "E-Mail 1" in text
    assert job.restore_package_path.exists()
    assert job.restore_package_path.suffix == ".dam"
    assert zipfile.is_zipfile(job.restore_package_path)


def test_company_variant_and_authority_detection(tmp_path: Path) -> None:
    source = tmp_path / "variants.txt"
    source.write_text(
        "Bayer Aktiengesellschaft arbeitet mit Bayer AG und Amtsgericht Muenchen.",
        encoding="utf-8",
    )
    job = DocumentJob(source)

    DocumentScanner().scan(job)

    company_replacements = {
        finding.replacement_text
        for finding in job.findings
        if finding.category == "company"
    }
    assert company_replacements == {"Firma AG 1"}
    assert any(finding.category == "authority" for finding in job.findings)


def test_umlaut_person_company_and_address_detection(tmp_path: Path) -> None:
    source = tmp_path / "umlauts.txt"
    source.write_text(
        "Frau Dr. Anna Müller wohnt in der Käferstraße 12, 12345 München.\n"
        "Die Müller & Söhne GmbH arbeitet später nur als Müller & Söhne weiter.",
        encoding="utf-8",
    )
    job = DocumentJob(source)

    DocumentScanner().scan(job)
    originals = {finding.original_text for finding in job.findings}

    assert "Frau Dr. Anna Müller" in originals
    assert "Käferstraße 12, 12345 München" in originals
    assert "Müller & Söhne GmbH" in originals
    assert "Müller & Söhne" in originals


def test_multiline_address_block_detection(tmp_path: Path) -> None:
    source = tmp_path / "address.txt"
    source.write_text(
        "Max Mustermann\nMusterweg 7\n10115 Berlin\n\nBitte zeitnah melden.",
        encoding="utf-8",
    )
    job = DocumentJob(source)

    DocumentScanner().scan(job)

    assert any(
        finding.category == "address"
        and "Max Mustermann" in finding.original_text
        and "10115 Berlin" in finding.original_text
        for finding in job.findings
    )


def test_manual_findings_are_reused_as_local_learning(tmp_path: Path) -> None:
    source = tmp_path / "learned.txt"
    source.write_text("Codexia Projektbüro liefert. Codexia Projektbüro rechnet ab.", encoding="utf-8")
    job = DocumentJob(source)
    job.findings.append(
        DocumentScanner()._merge_and_assign_placeholders(
            [
                Finding(
                    original_text="Codexia Projektbüro",
                    replacement_text="",
                    category="company",
                    confidence=1.0,
                    source="manual",
                )
            ]
        )[0]
    )

    DocumentScanner().scan(job)

    learned = [finding for finding in job.findings if finding.original_text == "Codexia Projektbüro"]
    assert learned
    assert learned[0].occurrence_count == 2


def test_project_state_roundtrip(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_text("Bayer AG", encoding="utf-8")
    job = DocumentJob(source)
    DocumentScanner().scan(job)
    project = tmp_path / "state.docanon"

    store = ProjectStateStore()
    store.save(project, [job])
    loaded = store.load(project)

    assert loaded[0].source_path == source
    assert loaded[0].findings[0].replacement_text == "Firma AG 1"


def test_txt_restore_roundtrip(tmp_path: Path) -> None:
    source = tmp_path / "restore.txt"
    source.write_text("Bayer AG und Herr Max Mustermann", encoding="utf-8")
    job = DocumentJob(source)
    DocumentScanner().scan(job)
    DocumentAnonymizer().anonymize(job, tmp_path)

    restored = DocumentRestorer().restore(job.output_path, job.restore_package_path, tmp_path / "restored.txt")

    assert restored.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")


def test_docx_scan_anonymize_and_restore(tmp_path: Path) -> None:
    from docx import Document

    source = tmp_path / "sample.docx"
    doc = Document()
    doc.add_paragraph("Bayer AG")
    doc.add_table(rows=1, cols=1).cell(0, 0).text = "Vater&Soehne GmbH"
    doc.save(source)
    job = DocumentJob(source)

    DocumentScanner().scan(job)
    DocumentAnonymizer().anonymize(job, tmp_path)
    anonymized_text = "\n".join(chunk.text for chunk in get_handler(job.output_path).extract_text(job.output_path))

    assert "Firma AG 1" in anonymized_text
    assert "Firma GmbH 1" in anonymized_text

    restored = DocumentRestorer().restore(job.output_path, job.restore_package_path, tmp_path / "restored.docx")
    restored_text = "\n".join(chunk.text for chunk in get_handler(restored).extract_text(restored))
    assert "Bayer AG" in restored_text
    assert "Vater&Soehne GmbH" in restored_text


def test_docx_anonymize_removes_header_images(tmp_path: Path) -> None:
    from docx import Document
    from PIL import Image

    source = tmp_path / "header-image.docx"
    logo = tmp_path / "logo.png"
    Image.new("RGB", (32, 16), (120, 120, 120)).save(logo)

    doc = Document()
    doc.add_paragraph("Bayer AG")
    doc.sections[0].header.paragraphs[0].add_run().add_picture(str(logo))
    doc.save(source)
    job = DocumentJob(source)

    DocumentScanner().scan(job)
    DocumentAnonymizer().anonymize(job, tmp_path)

    with zipfile.ZipFile(job.output_path, "r") as zf:
        names = zf.namelist()
        xml_parts = {
            name: zf.read(name)
            for name in names
            if name.endswith((".xml", ".rels")) and name.startswith("word/")
        }

    assert not any("/media/" in name.replace("\\", "/") for name in names)
    assert not any(b"/relationships/image" in data for data in xml_parts.values())
    assert not any(b"<a:blip" in data or b"<v:imagedata" in data for data in xml_parts.values())
    assert job.image_replacements


def test_docx_anonymize_can_keep_selected_image(tmp_path: Path) -> None:
    from docx import Document
    from PIL import Image

    from doc_anonymizer.app.formats.common import collect_openxml_images

    source = tmp_path / "selected-image.docx"
    keep_logo = tmp_path / "keep.png"
    remove_logo = tmp_path / "remove.png"
    Image.new("RGB", (32, 16), (120, 120, 120)).save(keep_logo)
    Image.new("RGB", (32, 16), (200, 200, 200)).save(remove_logo)

    doc = Document()
    doc.add_paragraph("Bayer AG")
    doc.add_picture(str(keep_logo))
    doc.add_picture(str(remove_logo))
    doc.save(source)

    job = DocumentJob(source)
    DocumentScanner().scan(job)
    job.image_replacements = collect_openxml_images(source)
    job.image_replacements[0].keep = True
    kept_path = job.image_replacements[0].locations[0].extra["package_path"]
    removed_path = job.image_replacements[1].locations[0].extra["package_path"]

    DocumentAnonymizer().anonymize(job, tmp_path)

    with zipfile.ZipFile(job.output_path, "r") as zf:
        names = zf.namelist()

    assert kept_path in names
    assert removed_path not in names
    assert [image.keep for image in job.image_replacements] == [True, False]


def test_pdf_scan_and_anonymize_with_pdfium(tmp_path: Path) -> None:
    source = tmp_path / "sample.pdf"
    _write_minimal_text_pdf(source, "Herr Max Mustermann")
    job = DocumentJob(source)

    DocumentScanner().scan(job)
    assert any(finding.original_text == "Herr Max Mustermann" for finding in job.findings)

    DocumentAnonymizer().anonymize(job, tmp_path)

    assert job.output_path.exists()
    assert b"Herr Max Mustermann" not in job.output_path.read_bytes()
