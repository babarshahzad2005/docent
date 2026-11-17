"""Builds the problem files in `files/bad/`, used to test that each fails with its own reason.

    uv run --with pypdf --with pillow python tests/extraction/make_bad_files.py

- `password.pdf`: a real PDF from `files/`, encrypted with a password.
- `scanned.pdf`: a page that is only a picture of text, as a scanner produces.
- `damaged.pdf`: a real PDF cut off half-way, as an interrupted download leaves it.
- `old-word.doc`: the start of an old binary Word file (the format .docx replaced, and the
  container Word also uses for password-protected .docx files).
"""

import io
from pathlib import Path

FILES = Path(__file__).parent / "files"
BAD = FILES / "bad"


def password_pdf() -> None:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(FILES / "fit-note-checklist.pdf"))
    writer.encrypt(user_password="open-sesame", algorithm="AES-256")
    with open(BAD / "password.pdf", "wb") as out:
        writer.write(out)


def scanned_pdf() -> None:
    from PIL import Image, ImageDraw

    page = Image.new("RGB", (850, 1100), "white")
    draw = ImageDraw.Draw(page)
    for line in range(20):
        draw.text((80, 80 + line * 40), f"Line {line + 1} of a scanned policy page.", fill="black")
    buffer = io.BytesIO()
    page.save(buffer, format="PDF", resolution=100)
    (BAD / "scanned.pdf").write_bytes(buffer.getvalue())


def damaged_pdf() -> None:
    whole = (FILES / "fit-note-checklist.pdf").read_bytes()
    (BAD / "damaged.pdf").write_bytes(whole[: len(whole) // 3])


def old_word() -> None:
    # The Compound File signature every .doc (and encrypted .docx) starts with, then padding.
    (BAD / "old-word.doc").write_bytes(bytes.fromhex("D0CF11E0A1B11AE1") + bytes(504))


if __name__ == "__main__":
    BAD.mkdir(exist_ok=True)
    password_pdf()
    scanned_pdf()
    damaged_pdf()
    old_word()
    print("Wrote", sorted(path.name for path in BAD.iterdir()))
