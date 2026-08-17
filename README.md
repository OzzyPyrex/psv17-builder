# PSV17 Batch OCR Automation

A Windows-focused Python pilot that uses OCR and computer vision to organise PSV17 scan batches. It extracts badge identifiers and candidate names from PDFs, pairs each PDF with the next scanned photo by timestamp, applies consistent filenames, logs results, and routes uncertain documents for manual review.

## Features

- Targeted OCR regions for badge-number extraction
- Common OCR correction for O/0 ambiguity
- Receipt detection and conservative name extraction
- Timestamp-based PDF/photo pairing
- Duplicate-safe filenames
- Separate output, manual-review, and log folders
- Optional Windows executable build through GitHub Actions

## Requirements

- Python 3.10 or newer
- Tesseract OCR
- Poppler for PDF rendering
- Python packages from requirements.txt

Install the Python dependencies:

    python -m pip install -r requirements.txt

If Tesseract or Poppler are not on PATH, configure them before running.

PowerShell:

    $env:TESSERACT_EXE = "C:\Program Files\Tesseract-OCR\tesseract.exe"
    $env:POPPLER_BIN = "C:\poppler\Library\bin"

## Usage

Work on copies of documents until the workflow has been validated for your environment. The script moves successfully processed files into output and uncertain files into manual_review.

    python psv17_batch_renamer.py "C:\path\to\a\batch"

## Privacy and operational safety

Licence documents and applicant photographs contain personal data. Never commit input documents, generated logs, OCR outputs, or manual-review files. This repository intentionally contains code only and no real document samples.

OCR can be wrong. Every renamed file should remain subject to human review before it is used in an operational process.

## Status

Pilot automation project. It is not an official licensing-authority system and should be reviewed under the applicable employer, client, privacy, and records-management policies before deployment.
