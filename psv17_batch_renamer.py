"""Privacy-first OCR-assisted batch organiser.

This utility plans PDF/photo moves from an OCR-extracted reference identifier.
It is deliberately non-destructive by default: the command only creates or
moves files when the caller supplies ``--apply``.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence


PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png"}
OUTPUT_DIRECTORY = "output"
MANUAL_REVIEW_DIRECTORY = "manual_review"
LOG_DIRECTORY = "logs"

# One letter followed by three or four digits is the limited identifier shape
# used by this legacy workflow. Keeping it strict prevents arbitrary OCR text
# from becoming part of a filename.
IDENTIFIER_PATTERN = re.compile(r"\b([A-Z])\s?([0-9O]{3,4})\b", re.IGNORECASE)


@dataclass(frozen=True)
class PlannedAction:
    """A validated move that has not necessarily been applied yet."""

    kind: str
    source: Path
    destination: Path
    record_identifier: str | None


@dataclass(frozen=True)
class BatchSummary:
    """Non-sensitive batch outcome counts."""

    scanned_files: int
    automatic_actions: int
    manual_review_actions: int
    applied: bool
    actions: tuple[PlannedAction, ...]


def normalise_identifier(value: str | None) -> str | None:
    """Return a strict, OCR-normalised identifier or ``None``.

    The normalised identifier is intentionally the only OCR result allowed in
    output filenames. Candidate names are not extracted or used.
    """

    if not value:
        return None
    match = IDENTIFIER_PATTERN.fullmatch(value.strip().upper())
    if not match:
        return None
    return f"{match.group(1)}{match.group(2).replace('O', '0')}"


def extract_identifier_from_text(text: str) -> str | None:
    """Find the first strict identifier in OCR text, correcting O/0 noise."""

    for match in IDENTIFIER_PATTERN.finditer(text.upper()):
        identifier = normalise_identifier(match.group(0))
        if identifier:
            return identifier
    return None


def _ocr_dependencies():
    """Load optional OCR dependencies only when a real document is processed."""

    try:
        import cv2
        import numpy as np
        import pytesseract
        from pdf2image import convert_from_path
    except ImportError as error:  # pragma: no cover - exercised by real users
        raise RuntimeError(
            "OCR dependencies are unavailable. Install requirements.txt before processing documents."
        ) from error

    tesseract_executable = os.getenv("TESSERACT_EXE") or shutil.which("tesseract")
    if tesseract_executable:
        pytesseract.pytesseract.tesseract_cmd = tesseract_executable
    return cv2, np, pytesseract, convert_from_path


def extract_identifier_from_page(page) -> str | None:
    """Use conservative OCR regions to find an identifier on one PDF page."""

    cv2, np, pytesseract, _ = _ocr_dependencies()
    gray = np.array(page.convert("L"))
    height, width = gray.shape[:2]
    regions = (
        (int(height * 0.12), int(height * 0.38), int(width * 0.68), width),
        (int(height * 0.20), int(height * 0.60), int(width * 0.10), int(width * 0.90)),
    )

    for y_start, y_end, x_start, x_end in regions:
        crop = gray[y_start:y_end, x_start:x_end]
        if crop.size == 0:
            continue
        crop_height, crop_width = crop.shape[:2]
        enlarged = cv2.resize(
            crop,
            (crop_width * 3, crop_height * 3),
            interpolation=cv2.INTER_CUBIC,
        )
        thresholded = cv2.threshold(
            enlarged, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )[1]
        identifier = extract_identifier_from_text(
            pytesseract.image_to_string(thresholded, config="--psm 6")
        )
        if identifier:
            return identifier
    return None


def extract_identifier_from_pdf(pdf_path: Path) -> str | None:
    """Extract a conservative identifier without retaining page images or text."""

    _, _, _, convert_from_path = _ocr_dependencies()
    poppler_path = os.getenv("POPPLER_BIN") or None
    pages = convert_from_path(str(pdf_path), poppler_path=poppler_path)
    for page in pages:
        identifier = extract_identifier_from_page(page)
        if identifier:
            return identifier
    return None


def _path_token(path: Path) -> str:
    """Create a stable non-reversible-looking reference for audit logs."""

    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()
    return digest[:12]


def redact_log_message(message: str) -> str:
    """Remove common personal-data forms before any audit entry is written.

    Callers should not pass personal data to logs in the first place. This is a
    defence-in-depth layer for filenames, e-mail addresses, identifier strings,
    and accidental Windows paths included by lower-level exceptions.
    """

    redacted = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "<email>", message)
    # Treat a complete log segment containing a document name (and an optional
    # source-to-destination arrow) as sensitive. This also covers filenames
    # containing spaces, which a simple ``\S+`` pattern would miss.
    redacted = re.sub(
        r"(?i)(?:^|(?<=[;|]))[^;|\r\n]*?\.(?:pdf|jpe?g|png|tiff?)(?:\s*->\s*[^;|\r\n]*?\.(?:pdf|jpe?g|png|tiff?))?",
        "<file>",
        redacted,
    )
    redacted = re.sub(
        r"(?i)(?:[A-Z]:)?(?:[^\\/:*?\"<>|\r\n]+\\)+[^\\/:*?\"<>|\r\n]+",
        "<path>",
        redacted,
    )
    redacted = IDENTIFIER_PATTERN.sub("<identifier>", redacted)
    return redacted


def write_log(log_file: Path, message: str) -> None:
    """Append a redacted audit entry; never persist source filenames or OCR text."""

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with log_file.open("a", encoding="utf-8") as stream:
        stream.write(f"{timestamp} {redact_log_message(message)}\n")


def _assert_within_batch(batch_directory: Path, path: Path) -> None:
    """Prevent an unexpected path from escaping the selected batch directory."""

    batch_root = batch_directory.resolve()
    try:
        path.resolve(strict=False).relative_to(batch_root)
    except ValueError as error:
        raise ValueError("Refusing to operate outside the selected batch directory.") from error


def _unique_destination(candidate: Path, reserved: set[Path]) -> Path:
    """Return an unused destination without overwriting an existing file."""

    suffix = candidate.suffix
    stem = candidate.stem
    counter = 1
    destination = candidate
    while destination.exists() or destination.resolve(strict=False) in reserved:
        destination = candidate.with_name(f"{stem}_{counter}{suffix}")
        counter += 1
    reserved.add(destination.resolve(strict=False))
    return destination


def _source_files(batch_directory: Path) -> list[Path]:
    """List direct batch files in timestamp order, without traversing subfolders."""

    def scan_role(path: Path) -> int:
        # A scanner can assign identical timestamps. In that case, deliberately
        # place the document before its following photo rather than depending on
        # filesystem enumeration order.
        if path.suffix.lower() == ".pdf":
            return 0
        if path.suffix.lower() in PHOTO_EXTENSIONS:
            return 1
        return 2

    return sorted(
        (path for path in batch_directory.iterdir() if path.is_file()),
        key=lambda path: (path.stat().st_mtime, scan_role(path), path.name.casefold()),
    )


def build_batch_plan(
    batch_directory: Path,
    extractor: Callable[[Path], str | None] = extract_identifier_from_pdf,
) -> tuple[list[PlannedAction], int]:
    """Create a non-mutating plan for direct PDF/photo scan pairs."""

    batch_directory = batch_directory.expanduser().resolve()
    if not batch_directory.is_dir():
        raise NotADirectoryError("The selected batch location is not a folder.")

    files = _source_files(batch_directory)
    output_directory = batch_directory / OUTPUT_DIRECTORY
    manual_directory = batch_directory / MANUAL_REVIEW_DIRECTORY
    reserved: set[Path] = set()
    processed: set[int] = set()
    actions: list[PlannedAction] = []

    for index, source_pdf in enumerate(files):
        if index in processed or source_pdf.suffix.lower() != ".pdf":
            continue

        source_photo: Path | None = None
        if index + 1 < len(files) and files[index + 1].suffix.lower() in PHOTO_EXTENSIONS:
            source_photo = files[index + 1]

        identifier = normalise_identifier(extractor(source_pdf))
        if identifier:
            document_destination = _unique_destination(
                output_directory / f"{identifier}_document.pdf", reserved
            )
            actions.append(
                PlannedAction("rename_document", source_pdf, document_destination, identifier)
            )
            if source_photo:
                photo_destination = _unique_destination(
                    output_directory / f"{identifier}_photo{source_photo.suffix.lower()}",
                    reserved,
                )
                actions.append(
                    PlannedAction("rename_photo", source_photo, photo_destination, identifier)
                )
                processed.add(index + 1)
        else:
            document_destination = _unique_destination(manual_directory / source_pdf.name, reserved)
            actions.append(
                PlannedAction("manual_review_document", source_pdf, document_destination, None)
            )
            if source_photo:
                photo_destination = _unique_destination(manual_directory / source_photo.name, reserved)
                actions.append(
                    PlannedAction("manual_review_photo", source_photo, photo_destination, None)
                )
                processed.add(index + 1)
        processed.add(index)

    return actions, len(files)


def _apply_actions(batch_directory: Path, actions: Sequence[PlannedAction], log_file: Path) -> None:
    """Perform previously planned moves after explicit caller approval."""

    for action in actions:
        _assert_within_batch(batch_directory, action.source)
        _assert_within_batch(batch_directory, action.destination)
        if not action.source.is_file():
            raise FileNotFoundError("A planned source document is no longer available.")
        if action.destination.exists():
            raise FileExistsError("A planned destination now exists; re-run the preview first.")

        action.destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(action.source), str(action.destination))
        except OSError as error:
            # Do not persist exception text: it can contain a full filename/path.
            write_log(
                log_file,
                f"event=move_failed kind={action.kind} source={_path_token(action.source)} reason={type(error).__name__}",
            )
            raise
        write_log(
            log_file,
            f"event=move_applied kind={action.kind} source={_path_token(action.source)} destination={_path_token(action.destination)}",
        )


def process_batch(
    batch_directory: Path,
    *,
    apply: bool = False,
    extractor: Callable[[Path], str | None] = extract_identifier_from_pdf,
) -> BatchSummary:
    """Preview a batch by default; mutate it only when ``apply=True``.

    In preview mode this function does not create output, manual-review, or log
    folders. OCR still reads PDFs to make the proposed plan, so use only on
    documents the caller is authorised to process.
    """

    batch_directory = batch_directory.expanduser().resolve()
    actions, scanned_files = build_batch_plan(batch_directory, extractor)
    automatic_actions = sum(action.kind.startswith("rename_") for action in actions)
    manual_actions = len(actions) - automatic_actions

    if apply:
        log_directory = batch_directory / LOG_DIRECTORY
        log_directory.mkdir(exist_ok=True)
        log_file = log_directory / f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.log"
        write_log(
            log_file,
            f"event=batch_started scanned_files={scanned_files} planned_actions={len(actions)}",
        )
        _apply_actions(batch_directory, actions, log_file)
        write_log(
            log_file,
            f"event=batch_completed automatic_actions={automatic_actions} manual_review_actions={manual_actions}",
        )

    return BatchSummary(
        scanned_files=scanned_files,
        automatic_actions=automatic_actions,
        manual_review_actions=manual_actions,
        applied=apply,
        actions=tuple(actions),
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview a privacy-first OCR batch plan; use --apply to move files."
    )
    parser.add_argument("batch_directory", type=Path, help="Folder containing one scan batch")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Explicitly apply the reviewed move plan. Omit this for a safe preview.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = process_batch(args.batch_directory, apply=args.apply)
    except Exception as error:
        # Exception messages can include document names, so only reveal their class.
        print(f"Processing stopped safely ({type(error).__name__}).", file=sys.stderr)
        return 2

    mode = "Applied" if summary.applied else "Preview"
    print(
        f"{mode}: scanned {summary.scanned_files} file(s); "
        f"automatic actions {summary.automatic_actions}; "
        f"manual-review actions {summary.manual_review_actions}."
    )
    if not summary.applied:
        print("No files or folders were changed. Review the batch, then re-run with --apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
