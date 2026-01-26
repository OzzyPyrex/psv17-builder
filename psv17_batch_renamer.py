# =============================================================================
# PSV17 BATCH AUTOMATION SUITE
# =============================================================================
# AUTHOR:      Adithya
# COPYRIGHT:   © 2026 Adithya. All Rights Reserved.
# DATE:        2026-01-25
# VERSION:     v10.0 (Pilot Build)
# DESCRIPTION: Computer Vision automation for NTA Driver Licensing (PSV17).
#              Extracts Badge IDs via OCR and pairs files by scan timestamp.
# =============================================================================
# NOTICE: This tool is a prototype developed to improve operational efficiency.
#         Maintenance and updates are managed by the author.
# =============================================================================

import re
import sys
import shutil
from pathlib import Path
from datetime import datetime
import cv2
import numpy as np
import pytesseract
from PIL import Image
from pdf2image import convert_from_path

# =========================================================================
# 1. CONFIGURATION & SETUP
# =========================================================================
# Adjust these paths if the office computer has them installed elsewhere.
# HARDCODED OFFICE PATHS
TESSERACT_EXE = r"C:\Users\Adithya_Muralidharan\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"
POPPLER_BIN = r"C:\poppler\Library\bin"

# Point pytesseract to the executable
if TESSERACT_EXE:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE

# Supported photo extensions for the sibling files
PHOTO_EXTS = (".jpg", ".jpeg", ".png")

# Folder names for the output
OUT_DIR_NAME = "output"
MANUAL_DIR_NAME = "manual_review"
LOG_DIR_NAME = "logs"


def now_stamp() -> str:
    """Returns a clean timestamp string for filenames."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_dirs(base: Path) -> tuple[Path, Path, Path]:
    """Creates the necessary output folders if they don't exist."""
    out_dir = base / OUT_DIR_NAME
    manual_dir = base / MANUAL_DIR_NAME
    log_dir = base / LOG_DIR_NAME
    out_dir.mkdir(exist_ok=True)
    manual_dir.mkdir(exist_ok=True)
    log_dir.mkdir(exist_ok=True)
    return out_dir, manual_dir, log_dir


def write_log(log_file: Path, msg: str) -> None:
    """Appends a message to the daily log file."""
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(msg + "\n")


# =========================================================================
# 2. INTELLIGENT NAME EXTRACTION
# =========================================================================
def extract_name_from_page(pil_img: Image.Image) -> str:
    """
    Attempts to find the driver's name on a receipt page.
    Includes a 'Strict Filter' to reject garbage text or headers.
    """
    try:
        # 1. ROI Selection: Crop top 40% (Names are rarely at the bottom)
        w, h = pil_img.size
        crop = pil_img.crop((0, 0, w, int(h * 0.4)))

        # 2. OCR Scan: PSM 6 is optimized for single blocks of text
        text = pytesseract.image_to_string(crop, config='--psm 6')
        lines = text.split('\n')

        # 3. Blocklist: Common words on the receipt that are NOT names
        BLOCKLIST = [
            "RECEIPT", "PAYMENT", "LICENSING", "AUTHORITY", "NATIONAL",
            "TRANSPORT", "DUBLIN", "NAISIUNTA", "IOMPAIR", "UDARAS",
            "OFFICE", "LICENCE", "SPSV", "DRIVER", "AMOUNT", "TOTAL",
            "DATE", "TIME", "STREET", "AVENUE", "ROAD"
        ]

        for line in lines:
            # Cleanup: Uppercase, remove special chars
            clean = re.sub(r"[^A-Z\s]", "", line.upper()).strip()

            # --- SAFETY CHECKS ---
            if len(clean) < 5: continue  # Too short to be a full name
            if any(char.isdigit() for char in line): continue  # Names don't have numbers

            # If the line contains ANY of the blocklist words, skip it.
            if any(blocked in clean for blocked in BLOCKLIST):
                continue

            # Two-Word Minimum Check (First Name + Last Name)
            words = clean.split()
            if len(words) < 2:
                continue

            # Sanity Check for Gibberish (e.g. "A B C")
            if sum(len(w) for w in words) < 5:
                continue

            # If we survived all checks, return the formatted name
            return clean.replace(" ", "_")[:30]

    except Exception:
        pass
    return ""


# =========================================================================
# 3. BADGE EXTRACTION (THE SNIPER)
# =========================================================================
def extract_badge_with_context(pil_img: Image.Image, page_num: int) -> tuple[str | None, int, bool]:
    """
    Scans the page for the Badge Number (e.g., M0635).
    Also detects if the page is a 'Receipt' to trigger name extraction.
    Returns: (Badge, Confidence, Is_Receipt_Page)
    """
    is_receipt = False
    try:
        # Convert to Grayscale for better OCR
        gray = np.array(pil_img.convert("L"))
        h, w = gray.shape[:2]

        # --- CHECK 1: Is this a Receipt Page? ---
        # We do a quick low-res scan for keywords
        full_page_thumb = cv2.resize(gray, (w // 2, h // 2))
        thumb_text = pytesseract.image_to_string(full_page_thumb).upper()
        if "RECEIPT" in thumb_text and "PAYMENT" in thumb_text:
            is_receipt = True

        # --- CHECK 2: The Sniper Scope (Badge Hunt) ---
        # We look in two specific places: Top Right (Table) and Center (Receipt Body)
        crops = [
            ("Top-Right Table", int(h * 0.15), int(h * 0.35), int(w * 0.75), w),
            ("Center Receipt", int(h * 0.20), int(h * 0.60), int(w * 0.10), int(w * 0.90))
        ]

        for (scope_name, y1, y2, x1, x2) in crops:
            crop = gray[y1:y2, x1:x2]
            if crop.size == 0: continue

            # Image Pre-processing: Zoom x3 + Thresholding (B&W)
            sh, sw = crop.shape[:2]
            zoomed = cv2.resize(crop, (sw * 3, sh * 3), interpolation=cv2.INTER_CUBIC)
            bw = cv2.threshold(zoomed, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

            # Run OCR on the zoomed crop
            text = pytesseract.image_to_string(bw, config='--psm 6')
            text_upper = text.upper().strip()

            # Context Verification: Does it look like a license area?
            has_context = any(k in text_upper for k in ["LICENCE", "NUMBER", "DRIVER", "BADGE", "SPSV"])

            # --- THE REGEX FIX ---
            # Finds [Letter] followed by [3 or 4 Digits]
            # {3,4} ensures we catch M123 AND M0635
            candidates = re.findall(r"\b([A-Z])\s?([0-9O]{3,4})\b", text_upper)

            for (let, nums) in candidates:
                # If we are in the Table (strong location) or have text context (strong keywords)...
                if has_context or scope_name == "Top-Right Table":
                    # Fix common OCR error: Letter 'O' -> Digit '0'
                    nums_fixed = nums.replace('O', '0')
                    badge = f"{let}{nums_fixed}"
                    print(f"   [JACKPOT] Found Badge {badge} via {scope_name} on Page {page_num}")
                    return badge, 99, is_receipt

    except Exception:
        pass
    return None, -1, is_receipt


# =========================================================================
# 4. DOCUMENT PROCESSOR
# =========================================================================
def extract_data_from_pdf(pdf_path: Path):
    """
    Opens a PDF and loops through every page to find the Badge and Name.
    """
    # Convert PDF pages to Images
    pages = convert_from_path(str(pdf_path), poppler_path=POPPLER_BIN)

    found_badge = None
    found_name = ""

    # Loop through pages
    for idx, page in enumerate(pages):
        badge, conf, is_receipt = extract_badge_with_context(page, idx + 1)

        # Grab Badge if we haven't found one yet
        if badge and not found_badge:
            found_badge = badge

        # Grab Name if we haven't found one yet AND this is a receipt page
        if is_receipt and not found_name:
            found_name = extract_name_from_page(page)
            if found_name:
                print(f"   [NAME] Found Name '{found_name}' on Page {idx + 1}")

    return found_badge, found_name


def process_batch(folder_path: Path) -> None:
    """
    The Main Coordinator.
    1. Sorts files by TIME (to pair PDFs with Photos correctly).
    2. Runs extraction on PDFs.
    3. Renames and moves files based on results.
    """
    out_dir, manual_dir, log_dir = ensure_dirs(folder_path)
    log_file = log_dir / f"run_{now_stamp()}.log"

    # SORT BY TIME: Critical for scanners that name files sequentially
    files = sorted([p for p in folder_path.iterdir() if p.is_file()], key=lambda p: p.stat().st_mtime)

    # Counters for the Final Report
    total_files = len(files)
    success_count = 0
    manual_count = 0

    print("\n" + "=" * 60)
    print(" PSV17 AUTOMATION TOOL - v10.0 (Pilot)")
    print(" Developed by: Adithya")
    print(" For Internal DL Operations Efficiency")
    print("=" * 60 + "\n")

    start_msg = f"Batch Run: {folder_path.name} | Found {total_files} files (Sorted by Time)."
    print(start_msg)
    write_log(log_file, start_msg)

    processed_indices = set()

    # Loop through all files
    for i in range(len(files)):
        if i in processed_indices: continue

        file_a = files[i]

        # We only process PDFs as the "Leader" of a pair
        if file_a.suffix.lower() == ".pdf":
            print(f"Processing: {file_a.name}...")

            # Check the NEXT file in the list. Is it a photo?
            file_b = None
            if i + 1 < len(files):
                potential_b = files[i + 1]
                if potential_b.suffix.lower() in PHOTO_EXTS:
                    file_b = potential_b

            # --- EXTRACT DATA ---
            badge, name, _ = (None, "", None)
            try:
                badge, name = extract_data_from_pdf(file_a)
            except Exception as e:
                print(f"   [Error] {e}")
                write_log(log_file, f"ERROR processing {file_a.name}: {e}")

            # --- DECISION TIME ---
            if badge:
                # [SUCCESS PATH]
                success_count += 1
                base_name = f"{badge}_{name}" if name else f"{badge}"
                new_pdf_name = f"{base_name}_PSV17.pdf"
                new_photo_name = f"{base_name}_PHOTO{file_b.suffix.lower()}" if file_b else None

                # Handle Duplicate Filenames (Increment counter)
                target_pdf = out_dir / new_pdf_name
                counter = 1
                while target_pdf.exists():
                    target_pdf = out_dir / f"{base_name}_{counter}_PSV17.pdf"
                    if new_photo_name:
                        new_photo_name = f"{base_name}_{counter}_PHOTO{file_b.suffix.lower()}"
                    counter += 1

                # MOVE PDF
                shutil.move(str(file_a), str(target_pdf))
                print(f"   ✅ PDF Renamed: {new_pdf_name}")
                log_msg = f"SUCCESS: {file_a.name} -> {new_pdf_name}"

                # MOVE PHOTO (If it exists)
                if file_b:
                    target_photo = out_dir / new_photo_name
                    shutil.move(str(file_b), str(target_photo))
                    print(f"   ✅ Photo Renamed: {new_photo_name}")
                    log_msg += f" | Photo: {file_b.name} -> {new_photo_name}"
                    processed_indices.add(i + 1)  # Mark photo as done
                else:
                    print(f"   ⚠️ No sibling photo found.")
                    log_msg += " | No Photo Found"

                write_log(log_file, log_msg)
                processed_indices.add(i)  # Mark PDF as done

            else:
                # [FAILURE PATH] -> MANUAL REVIEW
                manual_count += 1
                print(f"   ❌ FAILED: Badge not found. Moving to Manual.")
                shutil.move(str(file_a), str(manual_dir / file_a.name))
                msg = f"MANUAL: {file_a.name} (Badge not found)"

                if file_b:
                    shutil.move(str(file_b), str(manual_dir / file_b.name))
                    msg += f" | Photo: {file_b.name} moved"
                    processed_indices.add(i + 1)

                write_log(log_file, msg)
                processed_indices.add(i)

    # --- FINAL REPORT ---
    summary = (
        f"\n{'=' * 30}\n"
        f"BATCH COMPLETE REPORT\n"
        f"{'=' * 30}\n"
        f"Total Scanned: {total_files}\n"
        f"✅ Auto-Renamed: {success_count}\n"
        f"⚠️ Manual Review: {manual_count}\n"
        f"{'=' * 30}"
    )
    print(summary)
    write_log(log_file, summary)


# =========================================================================
# 5. EXECUTION ENTRY POINT
# =========================================================================
if __name__ == "__main__":
    # 1. Grab folder from command line (Drag & Drop support)
    target_folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()

    # 2. Run the processor
    process_batch(target_folder)

    # 3. KEEP WINDOW OPEN so user can see the report
    print("\nProcessing finished.")
    input("Press Enter to close this window...")