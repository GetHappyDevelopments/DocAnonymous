# DocAnonymous

Desktop application for creating anonymized copies of DOCX, XLSX, PPTX, PDF and TXT documents.

## Start

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m doc_anonymizer.app.main
```

For the optional non-LLM NER layer, install a German spaCy model:

```powershell
.\.venv\Scripts\python.exe -m spacy download de_core_news_sm
```

## Workflow

1. Add documents.
2. Scan documents.
3. Review and edit findings.
4. Add manual findings if needed.
5. Create anonymized copies and restoration packages.
6. Optionally restore an anonymized Office/TXT copy with the matching restoration package.

The original documents are never overwritten. Restoration `.dam` files are ZIP packages and contain sensitive original values and images.

## Features

- Finding filters by category, active state and confidence.
- Context preview for selected findings.
- Bulk activate/deactivate.
- Project save/load via `.docanon`.
- More Office text coverage through OpenXML package scanning.
- Rule, gazetteer, address-block and optional classic NER detection for persons, companies and addresses.
- TXT and Office restoration support from restore packages.
