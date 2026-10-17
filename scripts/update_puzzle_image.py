#!/usr/bin/env python3
"""Replace the artwork in the existing SVG puzzle without changing its masks.

The page's existing pic.jpg background is preserved.

Requires Pillow. Example: python3 scripts/update_puzzle_image.py new-picture.png
HEIC inputs can first be converted to PNG with ImageMagick.
"""

import argparse
import base64
from datetime import datetime
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[1]
XLINK = "{http://www.w3.org/1999/xlink}href"
NUMBER = r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?"
DATA_URI = re.compile(r"data:image/png;base64,[A-Za-z0-9+/=\s]+(?=[\"'])")


def read_piece(path):
    xml = path.read_text()
    root = ET.fromstring(xml)
    images = list(root.iter("{http://www.w3.org/2000/svg}image"))
    if len(images) != 1:
        raise ValueError(f"Expected one embedded image in {path}")
    element = images[0]
    parent = next(node for node in root.iter() if element in list(node))
    matrix = tuple(map(float, re.findall(NUMBER, parent.attrib["transform"])))
    a, b, c, d, x, y = matrix
    if a * d - b * c <= 0:
        raise ValueError(f"Unsupported transform in {path}: {matrix}")
    png = base64.b64decode(element.attrib[XLINK].split(",", 1)[1])
    mask = Image.open(BytesIO(png)).convert("RGBA").getchannel("A")
    left, top, right, bottom = mask.getbbox()
    corners = [(a * u + c * v + x, b * u + d * v + y)
               for u in (left, right) for v in (top, bottom)]
    bounds = (min(p[0] for p in corners), min(p[1] for p in corners),
              max(p[0] for p in corners), max(p[1] for p in corners))
    return path, xml, matrix, mask, bounds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    with Image.open(args.source) as image:
        source = ImageOps.exif_transpose(image).convert("RGB")

    paths = sorted((ROOT / "puzzle_pieces").glob("*.svg"), key=lambda p: int(p.stem))
    if [int(path.stem) for path in paths] != list(range(1, 82)):
        raise ValueError("Expected the existing 81 numbered SVG pieces (1.svg–81.svg)")
    pieces = [read_piece(path) for path in paths]
    left = min(piece[4][0] for piece in pieces)
    top = min(piece[4][1] for piece in pieces)
    right = max(piece[4][2] for piece in pieces)
    bottom = max(piece[4][3] for piece in pieces)
    if abs((source.width / source.height) / ((right - left) / (bottom - top)) - 1) > 0.01:
        raise ValueError("Crop the source to a square before replacing this square puzzle")

    # Prepare every replacement before touching any existing assets.
    sx, sy = source.width / (right - left), source.height / (bottom - top)
    replacements = []
    for path, xml, matrix, mask, _ in pieces:
        a, b, c, d, x, y = matrix
        tile = source.transform(
            mask.size,
            Image.Transform.AFFINE,
            (a * sx, c * sx, (x - left) * sx, b * sy, d * sy, (y - top) * sy),
            resample=Image.Resampling.BICUBIC,
        ).convert("RGBA")
        tile.putalpha(mask)
        png = BytesIO()
        tile.save(png, format="PNG", optimize=True)
        uri = "data:image/png;base64," + base64.b64encode(png.getvalue()).decode("ascii")
        updated, count = DATA_URI.subn(lambda _: uri, xml)
        if count != 1:
            raise ValueError(f"Expected one PNG data URI in {path}")
        replacements.append((path, updated))

    stamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d_%H%M%S")
    backup = ROOT / "backups" / f"puzzle-{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copytree(ROOT / "puzzle_pieces", backup / "puzzle_pieces")
    for name in ("pic.jpg", "assets/puzzle-source.png", "puzzle-preview.png"):
        current = ROOT / name
        if current.is_file():
            destination = backup / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(current, destination)
    hashes = {
        str(path.relative_to(backup)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(backup.rglob("*")) if path.is_file()
    }
    (backup / "manifest.json").write_text(json.dumps(hashes, indent=2) + "\n")
    (backup / "README.txt").write_text(
        "Original assets saved before replacing the puzzle artwork.\n"
        "To restore, copy puzzle_pieces/*.svg back to the project's puzzle_pieces/\n"
        "and pic.jpg back to the project root. Keep the same numeric filenames.\n"
        "manifest.json records SHA-256 hashes of the original files.\n"
    )

    for path, updated in replacements:
        path.write_text(updated)
    (ROOT / "assets").mkdir(exist_ok=True)
    source.save(ROOT / "assets" / "puzzle-source.png", optimize=True)
    print(f"Updated {len(replacements)} SVG pieces and assets/puzzle-source.png")
    print(f"Backup: {backup.relative_to(ROOT)}")
    print(f"Artwork bounds: {left}, {top}, {right}, {bottom}")


if __name__ == "__main__":
    main()
