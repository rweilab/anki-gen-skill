#!/usr/bin/env python3
"""PPTX ingestion checks, local and offline."""
from __future__ import annotations

import json
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from extract_pdf import extract_source  # noqa: E402
from extract_slides import extract_pptx  # noqa: E402


def make_pptx(path: Path, image: Path, *, notes: bool = True,
              image_rel: bool = True, write_media: bool = True,
              slides: int = 1) -> None:
    ns = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
    rel_ns = 'xmlns:r="http://schemas.openxmlformats.org/package/2006/relationships"'
    with zipfile.ZipFile(path, "w") as z:
        for number in range(1, slides + 1):
            title = "Priority Inversion" if number == 1 else f"Slide {number}"
            slide = f'''<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" {ns}>
<p:cSld><p:spTree><p:sp><p:txBody>
<a:p><a:r><a:t>{title}</a:t></a:r></a:p>
<a:p><a:r><a:t>A high-priority task waits on a low-priority lock holder.</a:t></a:r></a:p>
</p:txBody></p:sp></p:spTree></p:cSld></p:sld>'''
            rels = [f'<Relationship Id="rId{number}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/>'] if image_rel else []
            if notes:
                rels.append(f'<Relationship Id="n{number}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide" Target="../notesSlides/notesSlide{number}.xml"/>')
                z.writestr(
                    f"ppt/notesSlides/notesSlide{number}.xml",
                    f'''<p:notes xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" {ns}>
<p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Mention the medium-priority task {number}.</a:t></a:r></a:p>
</p:txBody></p:sp></p:spTree></p:cSld></p:notes>''')
            z.writestr(f"ppt/slides/slide{number}.xml", slide)
            z.writestr(f"ppt/slides/_rels/slide{number}.xml.rels",
                       f'<Relationships {rel_ns}>{"".join(rels)}</Relationships>')
        if write_media:
            z.writestr("ppt/media/image1.png", image.read_bytes())


def main() -> int:
    from PIL import Image, ImageDraw
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        image = td / "source.png"
        im = Image.new("RGB", (480, 300), "white")
        d = ImageDraw.Draw(im)
        d.rectangle([30, 30, 450, 270], outline="black", width=4)
        d.rectangle([60, 70, 170, 160], fill="#3366cc")
        d.rectangle([300, 90, 420, 230], fill="#cc6633")
        d.line([(180, 120), (290, 200)], fill="black", width=5)
        im.save(image)

        pptx = td / "priority.pptx"
        make_pptx(pptx, image)
        out = td / "out"
        result = extract_pptx(str(pptx), out, "slides")
        assert result["source_type"] == "pptx", result
        text = (out / "slides.md").read_text()
        assert "Priority Inversion" in text and "medium-priority" in text, text
        assert result["images"], result
        assert "<img" not in text and "media/slide01_img1.png" in text, text
        figs = json.loads((out / "figures.json").read_text())
        assert figs and figs[0]["slide"] == 1 and figs[0]["quality"] in ("high", "medium"), figs

        routed = extract_source(str(pptx), td / "routed", stem="routed")
        assert routed["source_type"] == "pptx" and (td / "routed" / "routed.md").is_file()
        directory = extract_source(str(td), td / "directory", stem="directory")
        assert directory["source_type"] == "directory", directory
        assert "Priority Inversion" in directory["content"], directory
        print("ok    PPTX text, notes, images, directory routing")

        missing_notes = td / "no-notes.pptx"
        make_pptx(missing_notes, image, notes=False)
        no_notes = extract_pptx(str(missing_notes), td / "no-notes-out", "no-notes")
        assert "Speaker notes" not in (td / "no-notes-out" / "no-notes.md").read_text()
        assert no_notes["images"], no_notes

        missing_image = td / "no-image.pptx"
        make_pptx(missing_image, image, write_media=False)
        no_image = extract_pptx(str(missing_image), td / "no-image-out", "no-image")
        assert no_image["images"] == [] and "![" not in (td / "no-image-out" / "no-image.md").read_text()
        print("ok    PPTX survives missing notes/image targets")

        many = td / "many.pptx"
        make_pptx(many, image, notes=False, slides=3)
        many_out = td / "many-out"
        extract_pptx(str(many), many_out, "many")
        many_text = (many_out / "many.md").read_text()
        assert many_text.index("Slide 1") < many_text.index("Slide 2") < many_text.index("Slide 3"), many_text
        print("ok    PPTX slide order")

        empty = td / "empty.pptx"
        with zipfile.ZipFile(empty, "w") as z:
            z.writestr("ppt/media/image1.png", image.read_bytes())
        try:
            extract_pptx(str(empty), td / "empty-out", "empty")
        except ValueError as e:
            assert "no slides" in str(e)
        else:
            raise AssertionError("empty PPTX accepted")
        corrupt = td / "corrupt.pptx"
        corrupt.write_bytes(b"not a zip")
        try:
            extract_pptx(str(corrupt), td / "corrupt-out", "corrupt")
        except zipfile.BadZipFile:
            pass
        else:
            raise AssertionError("corrupt PPTX accepted")
        traversal = td / "traversal.pptx"
        with zipfile.ZipFile(traversal, "w") as z:
            z.writestr("ppt/slides/slide1.xml", """<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Traversal</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>""")
            z.writestr("ppt/slides/_rels/slide1.xml.rels", """<Relationships xmlns:r="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="x" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../../outside.png"/></Relationships>""")
            z.writestr("outside.png", image.read_bytes())
        trav = td / "traversal-out"
        extract_pptx(str(traversal), trav, "traversal")
        assert not (trav / "media" / "slide01_img1.png").exists(), "traversal target imported"
        assert not (td / "outside.png").exists(), "traversal wrote outside output"
        bad_xml = td / "bad-xml.pptx"
        with zipfile.ZipFile(bad_xml, "w") as z:
            z.writestr("ppt/slides/slide1.xml", "<not-xml")
        try:
            extract_pptx(str(bad_xml), td / "bad-xml-out", "bad-xml")
        except ValueError as e:
            assert "invalid slide XML" in str(e), e
        else:
            raise AssertionError("invalid slide XML accepted")
        print("ok    PPTX rejects empty/corrupt/invalid-XML files")

        source = (ROOT / "scripts" / "extract_slides.py").read_text().lower()
        assert "soffice" not in source and "subprocess" not in source, "Office/process fallback in PPTX extractor"
        print("ok    PPTX extractor has no Office dependency")

    print("\nPASS  slides hardening")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
