#!/usr/bin/env python3
"""Generate the two local contact QR SVGs; shared vector encoder for the PDF."""

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.graphics.barcode.qrencoder import QRCode, QRErrorCorrectLevel
from reportlab.lib.colors import HexColor


ROOT = Path(__file__).resolve().parents[1]
GREEN = "#184b3c"
QUIET_ZONE = 4
CONTACTS = {
    "qr-vk.svg": "https://vk.ru/mp_luhovitsy",
    "qr-telegram.svg": "https://t.me/mpluhov",
}


def matrix(url):
    """Use error correction Q and an automatic version, without embedded logos."""
    qr = QRCode(None, QRErrorCorrectLevel.Q)
    qr.addData(url)
    qr.make()
    return qr.modules


def dark_runs(modules):
    """Combine adjacent modules in each row for compact, seam-free vector paths."""
    for row_index, row in enumerate(modules):
        start = None
        for column, dark in enumerate([*row, False]):
            if dark and start is None:
                start = column
            elif not dark and start is not None:
                yield start, row_index, column-start
                start = None


def svg_document(url):
    modules = matrix(url)
    extent = len(modules) + 2*QUIET_ZONE
    path = " ".join(f"M{x+QUIET_ZONE} {y+QUIET_ZONE}h{length}v1h-{length}z"
                    for x, y, length in dark_runs(modules))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {extent} {extent}" '
            f'width="256" height="256" role="img" aria-label="QR: {escape(url)}" '
            'shape-rendering="crispEdges">\n'
            f'  <title>{escape(url)}</title>\n'
            f'  <rect width="{extent}" height="{extent}" fill="#ffffff"/>\n'
            f'  <path fill="{GREEN}" d="{path}"/>\n</svg>\n')


def draw_pdf_qr(pdf_canvas, url, x, y, size):
    """Draw a vector QR including its white quiet zone; x/y are bottom-left."""
    modules = matrix(url)
    extent = len(modules) + 2*QUIET_ZONE
    unit = size / extent
    pdf_canvas.saveState()
    pdf_canvas.setFillColor(HexColor("#ffffff"))
    pdf_canvas.rect(x, y, size, size, stroke=0, fill=1)
    pdf_canvas.setFillColor(HexColor(GREEN))
    path = pdf_canvas.beginPath()
    for column, row, length in dark_runs(modules):
        path.rect(x+(column+QUIET_ZONE)*unit,
                  y+size-(row+QUIET_ZONE+1)*unit, length*unit, unit)
    pdf_canvas.drawPath(path, stroke=0, fill=1)
    pdf_canvas.restoreState()


def main():
    for filename, url in CONTACTS.items():
        destination = ROOT / "assets" / filename
        destination.write_text(svg_document(url), encoding="utf-8")
        print(f"{destination}: {url}")


if __name__ == "__main__":
    main()
