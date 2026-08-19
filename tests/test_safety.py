import tempfile
import unittest
from pathlib import Path

from psv17_batch_renamer import (
    LOG_DIRECTORY,
    MANUAL_REVIEW_DIRECTORY,
    OUTPUT_DIRECTORY,
    extract_identifier_from_text,
    process_batch,
    redact_log_message,
)


class SafetyBehaviourTests(unittest.TestCase):
    def _batch(self, directory: Path) -> tuple[Path, Path]:
        pdf = directory / "confidential-person.pdf"
        photo = directory / "confidential-person.jpg"
        pdf.write_bytes(b"synthetic test input")
        photo.write_bytes(b"synthetic test input")
        return pdf, photo

    def test_preview_is_non_mutating_and_creates_no_folders(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            batch = Path(temporary_directory)
            pdf, photo = self._batch(batch)

            summary = process_batch(batch, extractor=lambda _: "A0123")

            self.assertFalse(summary.applied)
            self.assertEqual(2, summary.scanned_files)
            self.assertEqual(2, summary.automatic_actions)
            self.assertTrue(pdf.exists())
            self.assertTrue(photo.exists())
            self.assertFalse((batch / OUTPUT_DIRECTORY).exists())
            self.assertFalse((batch / MANUAL_REVIEW_DIRECTORY).exists())
            self.assertFalse((batch / LOG_DIRECTORY).exists())

    def test_apply_requires_an_explicit_true_flag_and_log_is_redacted(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            batch = Path(temporary_directory)
            pdf, photo = self._batch(batch)

            summary = process_batch(batch, apply=True, extractor=lambda _: "A0123")

            self.assertTrue(summary.applied)
            self.assertFalse(pdf.exists())
            self.assertFalse(photo.exists())
            self.assertTrue((batch / OUTPUT_DIRECTORY / "A0123_document.pdf").exists())
            self.assertTrue((batch / OUTPUT_DIRECTORY / "A0123_photo.jpg").exists())
            log_text = next((batch / LOG_DIRECTORY).glob("*.log")).read_text(encoding="utf-8")
            self.assertNotIn("confidential-person", log_text)
            self.assertNotIn("A0123", log_text)
            self.assertIn("event=move_applied", log_text)

    def test_failed_extraction_is_planned_for_manual_review_only_when_applied(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            batch = Path(temporary_directory)
            pdf, photo = self._batch(batch)

            preview = process_batch(batch, extractor=lambda _: None)
            self.assertEqual(2, preview.manual_review_actions)
            self.assertTrue(pdf.exists())
            self.assertTrue(photo.exists())

            process_batch(batch, apply=True, extractor=lambda _: None)
            self.assertTrue((batch / MANUAL_REVIEW_DIRECTORY / pdf.name).exists())
            self.assertTrue((batch / MANUAL_REVIEW_DIRECTORY / photo.name).exists())

    def test_identifier_normalisation_and_log_redaction(self):
        self.assertEqual("A1023", extract_identifier_from_text("Reference A1O23"))
        self.assertIsNone(extract_identifier_from_text("Reference 12"))

        message = "SUCCESS: Jane Doe.pdf -> A0123_Jane_Doe.pdf; jane@example.com"
        redacted = redact_log_message(message)
        self.assertNotIn("Jane", redacted)
        self.assertNotIn("A0123", redacted)
        self.assertNotIn("example.com", redacted)
        self.assertIn("<file>", redacted)
        self.assertIn("<email>", redacted)


if __name__ == "__main__":
    unittest.main()
