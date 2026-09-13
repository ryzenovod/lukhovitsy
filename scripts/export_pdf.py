#!/usr/bin/env python3
"""Export the site's 11 slides as a 16:9 PDF. Requires reportlab, Pillow, pypdf.

Run from any directory: python3 scripts/export_pdf.py
Content and source URLs are read from index.html; assets are embedded locally.
"""

from __future__ import annotations

import argparse
import io
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from PIL import Image, ImageOps
from pypdf import PdfReader
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from export_qr import draw_pdf_qr


ROOT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT = 1440, 810
PAPER = "#f5f5ee"
GREEN = "#184b3c"
INK = "#193d32"
LIME = "#dafa70"
MUTED = "#59675e"
ORDER = ["home", "directions", "deputies", "memory", "dictation", "leaders",
         "cleanup", "monitoring", "careers", "triatlit", "contacts"]
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr"}


@dataclass
class Element:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def has_class(self, name):
        return name in self.attrs.get("class", "").split()

    def all(self, tag=None, cls=None):
        result = []
        for child in self.children:
            if not isinstance(child, Element):
                continue
            if (tag is None or child.tag == tag) and (cls is None or child.has_class(cls)):
                result.append(child)
            result.extend(child.all(tag, cls))
        return result

    def first(self, tag=None, cls=None):
        matches = self.all(tag, cls)
        if not matches:
            raise ValueError(f"Missing {tag=} {cls=} within {self.tag} {self.attrs}")
        return matches[0]

    def text(self):
        if self.attrs.get("aria-hidden") == "true":
            return ""
        if self.tag == "br":
            return "\n"
        text = "".join(c.text() if isinstance(c, Element) else c for c in self.children)
        return re.sub(r"[^\S\n]+", " ", text).strip()


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.root = Element("document")
        self.stack = [self.root]
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        element = Element(tag, dict(attrs))
        self.stack[-1].children.append(element)
        if tag not in VOID:
            self.stack.append(element)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack = self.stack[:index]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def clean(text):
    return text.replace("\u00a0", " ").replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")


class Deck:
    def __init__(self, destination, document):
        self.document = document
        self.slides = [s for s in document.all("section") if s.has_class("slide")]
        assert [s.attrs["id"] for s in self.slides] == ORDER, "Unexpected slide order in index.html"
        self.by_id = {s.attrs["id"]: s for s in self.slides}
        self.destination = destination
        self.canvas = canvas.Canvas(str(destination), pagesize=(WIDTH, HEIGHT), pageCompression=1)
        self.canvas.setTitle("Молодёжный парламент Луховиц")
        self.canvas.setAuthor("Молодёжный парламент м. о. Луховицы")
        self.canvas.setSubject("Направления деятельности, мероприятия и проекты")
        self.audit = []
        self.page_number = 0
        self.foreground = INK
        self.background = PAPER
        self.image_cache = {}
        for name, filename in (("Regular", "manrope-regular.ttf"),
                               ("Semibold", "manrope-semibold.ttf"),
                               ("ExtraBold", "manrope-extrabold.ttf")):
            pdfmetrics.registerFont(TTFont(name, str(ROOT / "assets" / filename)))

    def rect(self, x, top, width, height, fill):
        self.canvas.setFillColor(HexColor(fill))
        self.canvas.rect(x, HEIGHT - top - height, width, height, stroke=0, fill=1)

    def line(self, x1, y1, x2, y2, color=None, weight=1):
        self.canvas.setStrokeColor(HexColor(color or self.foreground))
        self.canvas.setLineWidth(weight)
        self.canvas.line(x1, HEIGHT-y1, x2, HEIGHT-y2)

    def wrap(self, text, size, width, font="Regular"):
        lines = []
        for paragraph in clean(text).split("\n"):
            words = paragraph.split()
            if not words:
                continue
            line = words.pop(0)
            for word in words:
                candidate = line + " " + word
                if pdfmetrics.stringWidth(candidate, font, size) <= width:
                    line = candidate
                else:
                    lines.append(line)
                    line = word
            lines.append(line)
        return lines

    def text(self, text, x, top, size=24, width=600, font="Regular", color=None,
             leading=1.38, max_bottom=745):
        lines = self.wrap(text, size, width, font)
        bottom = top + len(lines) * size * leading
        if bottom > max_bottom + 0.5:
            raise ValueError(f"Page {self.page_number}: text exceeds layout: {text[:80]!r} ({bottom:.1f})")
        self.canvas.setFillColor(HexColor(color or self.foreground))
        self.canvas.setFont(font, size)
        for index, line in enumerate(lines):
            if pdfmetrics.stringWidth(line, font, size) > width + 1:
                raise ValueError(f"Text wider than its column: {line}")
            self.canvas.drawString(x, HEIGHT-top-size-index*size*leading, line)
        self.audit[-1]["text"].append(clean(text))
        return bottom

    def title(self, text, x, top, width=620, size=68, color=None):
        # Preserve deliberate heading line breaks from the website.
        while any(pdfmetrics.stringWidth(line, "ExtraBold", size) > width
                  for line in clean(text).split("\n")):
            size -= 1
        return self.text(text, x, top, size, width, "ExtraBold", color, leading=1.07)

    def begin(self, section, color=PAPER):
        self.page_number += 1
        self.background = color
        self.foreground = PAPER if color == GREEN else INK
        self.audit.append({"page": self.page_number, "id": section.attrs["id"], "text": [], "links": []})
        self.rect(0, 0, WIDTH, HEIGHT, color)
        self.canvas.bookmarkPage(section.attrs["id"])
        self.canvas.addOutlineEntry(section.attrs.get("data-title", section.attrs["id"]), section.attrs["id"], 0)

    def end(self):
        rule_color = "#608373" if self.background == GREEN else "#bbc9b9"
        self.line(72, 764, 1368, 764, rule_color, .7)
        self.text(f"{self.page_number:02d} / {len(self.slides):02d}", 1290, 773, 12, 100,
                  "Semibold", self.foreground, 1, max_bottom=798)
        self.canvas.showPage()

    def chapter_header(self, section):
        label = section.first(cls="chapter-head").first(cls="eyebrow").text()
        self.text(label.upper(), 72, 48, 15, 1120, "Semibold", leading=1.2)
        index = section.first(cls="chapter-index").text()
        self.text(index, 1280, 48, 16, 100, "Semibold", leading=1.2)

    def photo(self, src, x, top, width, height, position=(.5, .5), photo_crop=None):
        key = (src, round(width), round(height), position, photo_crop)
        if key not in self.image_cache:
            image = Image.open(ROOT / src).convert("RGB")
            if photo_crop:
                image = image.crop(photo_crop)
            image = ImageOps.fit(image, (int(width*2), int(height*2)), Image.Resampling.LANCZOS,
                                 centering=position)
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=92, optimize=True, subsampling=0)
            buffer.seek(0)
            self.image_cache[key] = ImageReader(buffer)
        self.canvas.drawImage(self.image_cache[key], x, HEIGHT-top-height, width, height)

    def arrow(self, x, top, color=None, size=13):
        self.line(x, top+size, x+size, top, color, 1.5)
        self.line(x+2, top, x+size, top, color, 1.5)
        self.line(x+size, top, x+size, top+size-2, color, 1.5)

    def link(self, label, url, x, top, size=17, width=600, color=None):
        label = clean(label).replace("↗", "").strip()
        color = color or self.foreground
        bottom = self.text(label, x, top, size, width, "Semibold", color, 1.2)
        length = pdfmetrics.stringWidth(label, "Semibold", size)
        self.line(x, bottom+3, x+length, bottom+3, color, .8)
        self.arrow(x+length+12, top+6, color, 11)
        self.canvas.linkURL(url, (x, HEIGHT-bottom-10, x+length+29, HEIGHT-top+3), relative=0, thickness=0)
        self.audit[-1]["links"].append(url)
        return bottom+12

    def sources(self, section, x, top=691, width=610):
        for source in section.all("a", "source-link"):
            top = self.link(source.text(), source.attrs["href"], x, top, width=width)

    def paragraphs(self, nodes, x, top, width, size=24, leading=1.4, gap=18, max_bottom=675):
        for node in nodes:
            top = self.text(node.text(), x, top, size, width, leading=leading, max_bottom=max_bottom)+gap
        return top

    def hero(self, section):
        self.begin(section)
        brand = self.document.first(cls="brand-label").text()
        self.text(brand, 72, 46, 18, 620, "Semibold", leading=1.3)
        heading = section.first("h1").text().split("\n")
        y = 175
        for index, line in enumerate(heading):
            y = self.title(line, 72, y, 650, 102, GREEN if index else INK)
        self.text(section.first(cls="hero-description").text(), 76, 447, 24, 570, leading=1.45)
        self.photo(section.first("img").attrs["src"], 750, 170, 618, 424, (.57, .48))
        self.text(section.first("figcaption").text(), 750, 608, 16, 520, "Semibold")
        note = section.first(cls="hero-note")
        self.rect(1110, 552, 258, 180, LIME)
        self.text(note.first(cls="note-number").text(), 1137, 564, 67, 208, "ExtraBold", leading=1)
        self.text(note.first("p").text(), 1139, 645, 17, 209, "Semibold", leading=1.34)
        self.end()

    def overview(self, section):
        self.begin(section, GREEN)
        self.text(section.first(cls="eyebrow").text().upper(), 72, 46, 15, 600, "Semibold")
        self.title(section.first("h2").text(), 72, 108, 630, 63)
        self.text(section.first(cls="mandate").text(), 780, 135, 21, 570, leading=1.46)
        entries = section.first(cls="direction-grid").all("a")
        assert len(entries) == 8
        # Top-to-bottom within each column preserves the eight priorities.
        for index, entry in enumerate(entries):
            column, row = divmod(index, 4)
            x, top = 72+column*682, 312+row*106
            self.line(x, top, x+614, top, "#608373", .8)
            self.text(entry.first("span").text(), x, top+19, 17, 38, "Semibold", LIME)
            heading = entry.first("strong").text()
            fontsize = 26
            while pdfmetrics.stringWidth(heading, "ExtraBold", fontsize) > 550:
                fontsize -= .5
            self.text(heading, x+52, top+15, fontsize, 554, "ExtraBold", leading=1.2)
            self.text(entry.first("small").text(), x+52, top+55, 17, 550, leading=1.35)
            self.canvas.linkRect("", entry.attrs["href"][1:],
                                 (x, HEIGHT-top-100, x+614, HEIGHT-top), relative=0, thickness=0)
        self.end()

    def standard(self, section):
        identifier = section.attrs["id"]
        self.begin(section, LIME if identifier == "monitoring" else PAPER)
        self.chapter_header(section)
        copy = section.first(cls="chapter-copy")
        top = self.title(copy.first("h2").text(), 72, 134, 620, 66)+31
        body = [c for c in copy.children if isinstance(c, Element) and c.tag == "p"]
        notes = []
        for node in body:
            if node.has_class("small-note"):
                notes.append(node)
            elif node.has_class("project-name"):
                top = self.text(node.text(), 72, top, 22, 590, "Semibold", leading=1.3)+22
            else:
                top = self.paragraphs([node], 72, top, 590,
                                      size=23 if identifier == "careers" else 24,
                                      max_bottom=661)
        if identifier == "dictation":
            self.line(72, top+7, 646, top+7, "#b9c6b5", 1)
            top += 24
            fact_pair = copy.first(cls="fact-pair")
            for i, fact in enumerate([c for c in fact_pair.children if isinstance(c, Element)]):
                x = 72+i*282
                self.text(fact.first("strong").text(), x, top, 66, 255, "ExtraBold", GREEN, 1)
                self.text(fact.first("span").text(), x, top+80, 19, 266, "Semibold", leading=1.25)
            top += 126
        if notes:
            self.paragraphs(notes, 72, top+2, 600, 17, 1.3, 0, max_bottom=680)
        image = section.first("img")
        # Preserve group photos and the playground scene without cutting off heads.
        picture_height = 440 if identifier in {"deputies", "dictation", "careers"} else 472
        self.photo(image.attrs["src"], 738, 170, 630, picture_height,
                   (.5, .45) if identifier == "deputies" else (.5, .48))
        self.text(section.first("figcaption").text(), 738, 170+picture_height+16, 15, 630,
                  "Semibold", leading=1.35)
        self.sources(section, 72, 688 if len(section.all("a", "source-link")) == 2 else 706)
        self.end()

    def memory(self, section):
        self.begin(section, GREEN)
        self.chapter_header(section)
        images = section.all("img")
        # The source screenshot's inner photograph matches .memory-crop in CSS.
        self.photo(images[0].attrs["src"], 72, 160, 527, 451, photo_crop=(0, 765, 1170, 1766))
        self.rect(352, 419, 365, 290, GREEN)
        self.photo(images[1].attrs["src"], 363, 430, 343, 257)
        captions = section.all("figcaption")
        assert len(captions) == 2, "Both memory events need separate photo captions"
        self.text(captions[0].text(), 72, 630, 15, 270, "Semibold", leading=1.4)
        self.text(captions[1].text(), 363, 705, 15, 343, "Semibold", leading=1.4)
        copy = section.first(cls="chapter-copy")
        top = self.title(copy.first("h2").text(), 780, 138, 570, 77)+32
        body = [c for c in copy.children if isinstance(c, Element) and c.tag == "p"]
        self.paragraphs(body, 782, top, 568, size=24)
        self.sources(section, 782, 688, 565)
        self.end()

    def leaders(self, section):
        self.begin(section, GREEN)
        self.chapter_header(section)
        self.photo(section.first("img").attrs["src"], 72, 180, 644, 437, (.5, .48))
        self.text(section.first("figcaption").text(), 72, 636, 16, 644, "Semibold")
        copy = section.first(cls="chapter-copy")
        top = self.title(copy.first("h2").text(), 785, 134, 577, 66)+31
        body = [c for c in copy.children if isinstance(c, Element) and c.tag == "p"]
        top = self.paragraphs(body, 788, top, 570, 23, 1.42, 16)
        person = copy.first(cls="person-note")
        self.line(788, top+4, 1364, top+4, "#608373", .8)
        top = self.text(person.first("span").text(), 788, top+24, 16, 570, "Semibold", LIME)+7
        top = self.text(person.first("strong").text(), 788, top, 29, 570, "ExtraBold")+7
        self.text(person.first("p").text(), 788, top, 19, 570, leading=1.4)
        self.sources(section, 788, 706, 576)
        self.end()

    def cleanup(self, section):
        self.begin(section)
        self.chapter_header(section)
        heading = section.first(cls="wide-story-heading")
        self.title(heading.first("h2").text(), 72, 111, 842, 63)
        self.paragraphs(heading.all("p"), 976, 172, 392, 23, 1.4, 24, max_bottom=662)
        # Keep the entire 16:9 scene, including people at the top of the frame.
        self.photo(section.first("img").attrs["src"], 72, 266, 842, 842*9/16)
        self.sources(section, 976, 706, 392)
        self.end()

    def triatlit(self, section):
        self.begin(section, LIME)
        self.chapter_header(section)
        heading = section.first(cls="triatlit-heading")
        self.title(heading.first("h2").text(), 72, 119, 770, 103)
        summary = [p for p in heading.all("p") if not p.has_class("eyebrow")][0]
        self.text(summary.text(), 934, 149, 24, 426, leading=1.42)
        self.photo(section.first("img").attrs["src"], 72, 304, 782, 352, (.5, .42))
        stages = section.first(cls="literary-stages")
        for i, stage in enumerate([c for c in stages.children if isinstance(c, Element)]):
            top = 300+i*114
            self.line(921, top, 1368, top, "#88a458", .8)
            self.text(stage.first("span").text(), 921, top+24, 18, 48, "Semibold")
            self.text(stage.first("h3").text(), 974, top+12, 35, 392, "ExtraBold", leading=1.2)
            self.text(stage.first("p").text(), 974, top+66, 18, 392, leading=1.32)
        self.text(section.first(cls="triatlit-footer").first("p").text(), 72, 684, 16, 780,
                  "Semibold", leading=1.4)
        self.sources(section, 921, 688, 447)
        self.end()

    def contacts(self, section):
        self.begin(section, GREEN)
        self.text(self.document.first(cls="brand-label").text(), 72, 46, 18, 610, "Semibold", leading=1.3)
        self.title(section.first("h2").text(), 72, 132, 1200, 133, LIME)
        self.text(section.first(cls="contact-bottom").first("p").text(), 77, 321, 28, 1120, leading=1.4)
        contacts = section.first(cls="contact-links").all("a")
        for index, item in enumerate(contacts):
            x, top = 72+index*674, 434
            self.rect(x, top, 622, 290, PAPER if index == 0 else LIME)
            outer_span = item.first("span")
            handle = outer_span.first("small").text()
            label = outer_span.text().replace(handle, "").strip()
            self.text(label, x+32, top+39, 35, 308, "ExtraBold", INK, 1.2)
            self.text(handle, x+34, top+105, 22, 308, "Semibold", INK, 1.3)
            self.arrow(x+34, top+213, INK, 28)
            draw_pdf_qr(self.canvas, item.attrs["href"], x+368, HEIGHT-top-32-222, 222)
            self.canvas.linkURL(item.attrs["href"], (x, HEIGHT-top-290, x+622, HEIGHT-top), relative=0, thickness=0)
            self.audit[-1]["links"].append(item.attrs["href"])
        self.end()

    def export(self):
        handlers = {"home": self.hero, "directions": self.overview, "memory": self.memory,
                    "leaders": self.leaders, "cleanup": self.cleanup, "triatlit": self.triatlit,
                    "contacts": self.contacts}
        for section in self.slides:
            handlers.get(section.attrs["id"], self.standard)(section)
        self.canvas.save()
        reader = PdfReader(self.destination)
        assert len(reader.pages) == 11
        for i, page in enumerate(reader.pages):
            assert round(float(page.mediabox.width)/float(page.mediabox.height), 8) == round(16/9, 8)
            extracted = page.extract_text()
            assert extracted.strip(), f"Slide {i+1} has no extractable text"
            assert "самопрезентация" not in extracted.casefold()
        urls = [annotation.get_object().get("/A", {}).get("/URI") for page in reader.pages
                for annotation in page.get("/Annots", [])]
        urls = [url for url in urls if url]
        expected = [url for page in self.audit for url in page["links"]]
        assert urls == expected, "Missing or reordered external source links"
        assert len(urls) == 14, f"Expected 12 source links and 2 social links, got {len(urls)}"
        assert not any(url.endswith("lukhovitsy.pdf") for url in urls)
        return {"pages": len(reader.pages), "dimensions": [WIDTH, HEIGHT], "external_links": urls,
                "bytes": self.destination.stat().st_size, "slides": self.audit}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "output/pdf/lukhovitsy.pdf")
    parser.add_argument("--qa-dir", type=Path, default=ROOT / "work/pdf")
    options = parser.parse_args()
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.qa_dir.mkdir(parents=True, exist_ok=True)
    document = Document((ROOT / "index.html").read_text(encoding="utf-8")).root
    report = Deck(options.output, document).export()
    (options.qa_dir / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("pages", "dimensions", "bytes")}, ensure_ascii=False))
    print(f"PDF: {options.output}")


if __name__ == "__main__":
    main()
