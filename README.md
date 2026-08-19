# Privacy-first batch OCR organiser

This repository contains a small Windows-friendly Python pilot for organising a batch of scanned PDFs and their immediately following photos. It uses OCR to locate a tightly validated reference identifier, then proposes a consistent output name.

The repository uses a legacy project name only. It is not affiliated with, endorsed by, or an official system of any organisation.

## Safety-first behaviour

- **Preview is the default.** Running the command without `--apply` reads documents to build a plan but does not create folders, rename files, move files, or write logs.
- **Moves require `--apply`.** Apply a plan only after reviewing a copy of the source batch.
- **Names are not extracted or included in output names.** The tool uses only its narrowly validated reference identifier.
- **Logs are redacted.** Audit logs use opaque document tokens and never intentionally store filenames, OCR text, names, identifiers, e-mail addresses, or exception messages.
- **All generated material is ignored by Git.** Input documents, output folders, manual-review folders, and logs must remain in authorised storage, never in source control.

OCR is probabilistic. This is a pilot workflow, not an automated decision system; a person must review every proposed or applied result.

## Requirements

- Python 3.10 or later
- [Tesseract OCR](https://github.com/tesseract-ocr/tesseract)
- Poppler (needed to render PDF pages)
- Python packages in `requirements.txt`

Install the Python packages:

```powershell
python -m pip install -r requirements.txt
```

If they are not available on `PATH`, configure local paths for the current session only:

```powershell
$env:TESSERACT_EXE = "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"
$env:POPPLER_BIN = "C:\\poppler\\Library\\bin"
```

## Usage

Always start with a copy of an authorised scan batch and run the non-mutating preview:

```powershell
python psv17_batch_renamer.py "C:\\authorised-copy\\scan-batch"
```

The command prints only totals; it intentionally does not print document names or extracted data. If the result is suitable and you have checked the source batch, explicitly apply it:

```powershell
python psv17_batch_renamer.py "C:\\authorised-copy\\scan-batch" --apply
```

When applied, recognised pairs move to `output/` with names based on the detected reference identifier. Unrecognised PDF/photo pairs move to `manual_review/`. The reference identifier can itself be personal data, so treat both directories as restricted material.

## Tests

The test suite uses only empty synthetic files and an injected OCR result. It does not include or access document samples.

```powershell
python -m unittest discover -s tests -v
```

## Data handling boundary

Never add scanned documents, photographs, generated logs, executable files, OCR text, or real-world output examples to this repository. Use an approved records-management location and follow the relevant privacy, retention, and access-control rules for your organisation.
