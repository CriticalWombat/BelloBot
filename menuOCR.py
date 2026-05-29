"""
menuOCR.py
-----------
Extract and format menu items from an image using Tesseract OCR (free, no API key needed).
Automatically detects multi-column layouts and OCRs each column independently
before recombining, which gives significantly cleaner output than single-pass OCR.

Dependencies:
    pip install pytesseract pillow numpy
    # macOS:  brew install tesseract
    # Ubuntu: sudo apt install tesseract-ocr
    # Windows: https://github.com/UB-Mannheim/tesseract/wiki
"""

import re
import numpy as np
from PIL import Image, ImageEnhance
import pytesseract
import requests
from io import BytesIO


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_menu_text(source: str, preprocess: bool = True) -> str:
    """
    Run Tesseract OCR on a menu image and return cleaned, formatted text.

    Automatically detects whether the menu is single- or multi-column and
    OCRs each column separately before joining, preventing lines from
    adjacent columns from bleeding into each other.

    Args:
        source:     File path (PNG, JPG, WEBP, etc.) or an http/https URL.
        preprocess: Upscale + sharpen before OCR. Recommended for most
                    printed menus. Disable only for already-large images.

    Returns:
        Cleaned OCR text with each column's content in order, separated
        by a divider line.
    """
    if source.startswith("http://") or source.startswith("https://"):
        response = requests.get(source)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content))
    else:
        img = Image.open(source)

    columns = _detect_columns(img)

    parts = []
    for i, (x_start, x_end) in enumerate(columns):
        col_img = img.crop((x_start, 0, x_end, img.height))
        if preprocess:
            col_img = _preprocess(col_img)
        raw = pytesseract.image_to_string(col_img, config="--psm 4 --oem 3")
        cleaned = _clean(raw)
        if cleaned:
            parts.append(cleaned)

    return "\n\n---\n\n".join(parts)


def parse_menu_items(text: str) -> list[dict]:
    """
    Parse cleaned OCR text into a list of menu item dicts.

    Each dict has:
        name        (str)        – item name / title
        price       (str | None) – e.g. "$6.50", or None
        description (str)        – ingredient / detail lines that follow

    Works on both single-column text and multi-column text joined by
    the "---" divider that extract_menu_text inserts.
    """
    PRICE_RE = re.compile(r"\$\s*\d+\.\d{2}")

    # Strip section dividers — treat all columns as one stream
    text = text.replace("---", "")

    items: list[dict] = []
    current: dict | None = None
    desc_lines: list[str] = []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        price_match = PRICE_RE.search(line)
        if price_match:
            # Flush previous item
            if current is not None:
                current["description"] = " ".join(desc_lines).strip()
                items.append(current)
                desc_lines = []

            price = price_match.group().replace(" ", "")
            name = PRICE_RE.sub("", line).strip(" -–—")
            current = {"name": name, "price": price, "description": ""}
        else:
            if current is not None:
                desc_lines.append(line)

    # Flush last item
    if current is not None:
        current["description"] = " ".join(desc_lines).strip()
        items.append(current)

    return items


def format_menu(items: list[dict]) -> str:
    """Return a human-readable string of parsed menu items."""
    lines = []
    for item in items:
        lines.append(f"{item['name']}  {item['price']}")
        if item["description"]:
            lines.append(f"  {item['description']}")
        lines.append("")
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Column detection
# ---------------------------------------------------------------------------

def _detect_columns(img: Image.Image, search_band: tuple = (0.35, 0.65)) -> list[tuple]:
    """
    Return a list of (x_start, x_end) slices representing each column.

    Strategy: build a horizontal word-density histogram from Tesseract's
    bounding boxes, smooth it, then look for a significant gap in the
    middle band of the image. If no clear gap is found, returns a single
    column covering the full width.

    Args:
        img:         PIL Image (original, unscaled)
        search_band: Fraction of image width to search for a column gap.
                     (0.35, 0.65) means we only look in the middle 30%.
    """
    # Use a quick low-res preprocess just for detection
    detect_img = _preprocess(img)
    scale = detect_img.width / img.width

    data = pytesseract.image_to_data(
        detect_img, config="--psm 4 --oem 3",
        output_type=pytesseract.Output.DATAFRAME
    )
    words = data[(data.conf > 30) & (data.text.str.strip() != "")].copy()

    if words.empty:
        return [(0, img.width)]

    # Build density histogram in original image coordinates
    hist = np.zeros(img.width)
    for _, row in words.iterrows():
        l = int(row["left"] / scale)
        r = int((row["left"] + row["width"]) / scale)
        l, r = max(0, l), min(img.width, r)
        hist[l:r] += 1

    # Smooth to merge nearby word gaps
    kernel = np.ones(25) / 25
    smooth = np.convolve(hist, kernel, mode="same")

    mid_start = int(img.width * search_band[0])
    mid_end = int(img.width * search_band[1])
    mid_smooth = smooth[mid_start:mid_end]

    gap_val = mid_smooth.min()
    gap_idx = int(np.argmin(mid_smooth))
    split_x = mid_start + gap_idx

    # Only split if the gap density is < 30% of the overall average
    avg_density = smooth.mean()
    if avg_density > 0 and gap_val < avg_density * 0.3:
        return [(0, split_x), (split_x, img.width)]

    return [(0, img.width)]


# ---------------------------------------------------------------------------
# Image preprocessing
# ---------------------------------------------------------------------------

def _preprocess(img: Image.Image) -> Image.Image:
    """Upscale narrow images and sharpen for cleaner OCR."""
    if img.width < 2000:
        scale = max(1, 2000 // img.width)
        img = img.resize((img.width * scale, img.height * scale), Image.LANCZOS)
    img = ImageEnhance.Sharpness(img).enhance(2.0)
    img = ImageEnhance.Contrast(img).enhance(1.5)
    return img


# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------

def _clean(text: str) -> str:
    """Strip common OCR noise and normalize whitespace."""
    # Remove lone special-character artifacts
    text = re.sub(r"(?<!\w)[©@~`\|\\^{}](?!\w)", "", text)
    # Collapse 3+ blank lines to one
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip trailing spaces per line
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return text.strip()


# ---------------------------------------------------------------------------
# CLI / quick test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from pathlib import Path

    path = sys.argv[1] if len(sys.argv) > 1 else "menu.png"
    if not Path(path).exists():
        print(f"File not found: {path}")
        sys.exit(1)

    print("=== Raw OCR text (per column) ===")
    raw_text = extract_menu_text(path)
    print(raw_text)

    print("\n\n=== Parsed menu items ===")
    items = parse_menu_items(raw_text)
    print(format_menu(items))
    print(f"\n→ {len(items)} items found")