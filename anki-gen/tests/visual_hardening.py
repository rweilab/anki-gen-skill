#!/usr/bin/env python3
"""Offline tests for visual scoring, PDF filtering, and yt-dlp wiring."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import platform_paths  # noqa: E402
import visual  # noqa: E402
import ytdlp  # noqa: E402

VISION_SCRIPTS = ROOT.parent / "image-vision" / "scripts"
sys.path.insert(0, str(VISION_SCRIPTS))
import vision_check  # noqa: E402


def main() -> int:
    # Decisions from the real RTOS deck: low-edge image-only diagrams and
    # 100-word labelled diagrams must not be treated as text walls.
    diagram = {"edge": 0.019, "focus": 3.35, "color": 0.005, "background": 0.8}
    labelled = {"edge": 0.038, "focus": 2.48, "color": 0.010, "background": 0.7}
    wall = {"edge": 0.050, "focus": 1.10, "color": 0.010, "background": 0.8}
    blank = {"edge": 0.001, "focus": 1.0, "color": 0.001, "background": 1.0}

    q = visual.classify(diagram, words=5, strong_cue=True)
    assert q["quality"] == "high" and q["attach"] == "direct", q
    q = visual.classify(labelled, words=78, strong_cue=True)
    assert q["quality"] == "high" and not q["text_wall"], q
    q = visual.classify(wall, words=80, strong_cue=True)
    assert q["quality"] == "low" and q["text_wall"], q
    q = visual.classify(blank, words=0)
    assert q["quality"] == "low" and q["blank"], q
    assert visual.rank(labelled) > visual.rank(wall)
    print("ok    visual decisions")

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("skip  Pillow missing; image/PDF tests skipped")
        return 0

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)

        diagram_png = td / "diagram.png"
        im = Image.new("RGB", (1280, 720), "white")
        d = ImageDraw.Draw(im)
        d.ellipse((300, 140, 980, 580), outline="black", width=9)
        d.line((640, 60, 640, 660), fill="black", width=7)
        d.line((120, 360, 1160, 360), fill="black", width=7)
        d.rectangle((520, 260, 760, 440), outline="black", width=6)
        im.save(diagram_png)

        wall_png = td / "wall.png"
        im = Image.new("RGB", (1280, 720), "white")
        d = ImageDraw.Draw(im)
        for y in range(70, 680, 28):
            for x in range(80, 1200, 22):
                d.rectangle((x, y, x + 14, y + 14), fill="black")
        im.save(wall_png)

        dm = visual.analyze(diagram_png)
        wm = visual.analyze(wall_png)
        assert dm and 0 <= dm["color"] <= 1, dm
        assert wm and 0 <= wm["color"] <= 1, wm
        assert dm["shash"] != wm["shash"], (dm["shash"], wm["shash"])
        assert dm and visual.classify(dm, words=0, strong_cue=True)["quality"] == "high", dm
        assert wm and visual.classify(wm, words=80)["text_wall"], wm
        assert visual.dhash_distance(dm["dhash"], dm["dhash"]) == 0
        assert visual.dhash_distance(dm["dhash"], wm["dhash"]) > 2
        print("ok    visual metrics and dHash")

        # A PDF with one real diagram, one tiny logo, and a duplicate diagram.
        try:
            import pymupdf as fitz
        except ImportError:
            try:
                import fitz  # type: ignore
            except ImportError:
                print("skip  pymupdf missing; PDF filter test skipped")
                return 0

        logo_png = td / "logo.png"
        Image.new("RGB", (64, 64), "black").save(logo_png)
        pdf = td / "figures.pdf"
        doc = fitz.open()
        page = doc.new_page(width=900, height=650)
        page.insert_image(fitz.Rect(50, 50, 850, 600), filename=str(diagram_png))
        page = doc.new_page(width=900, height=650)
        page.insert_image(fitz.Rect(40, 40, 104, 104), filename=str(logo_png))
        page = doc.new_page(width=900, height=650)
        page.insert_image(fitz.Rect(50, 50, 850, 600), filename=str(diagram_png))
        doc.save(pdf)
        doc.close()

        out = td / "out"
        r = subprocess.run([sys.executable, str(SCRIPTS / "extract_pdf.py"),
                            str(pdf), str(out)], capture_output=True, text=True,
                           cwd=td)
        assert r.returncode == 0, (r.stdout, r.stderr)
        out = td / ".anki-gen-temp" / "out"
        figs = json.loads((out / "figures.json").read_text())
        assert len(figs) == 1, figs
        assert figs[0]["quality"] in ("high", "medium"), figs[0]
        assert figs[0]["flags"] == [], figs[0]
        assert len(json.loads(r.stdout)["images"]) == 1, r.stdout

        r = subprocess.run([sys.executable, str(SCRIPTS / "media_index.py"),
                            str(out), "--json"], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        rows = json.loads(r.stdout)
        assert len(rows) == 1 and rows[0]["quality"] in ("high", "medium"), rows
        print("ok    PDF figure filtering and quality index")

        # Two captioned figures on one page, and a vector-only page with a
        # caption. The first must keep distinct captions/bboxes; the second must
        # yield a page crop because there is no embedded raster.
        diagram2 = td / "diagram2.png"
        im = Image.new("RGB", (640, 400), "white")
        d = ImageDraw.Draw(im)
        d.ellipse((40, 40, 600, 360), outline="black", width=8)
        d.line((320, 20, 320, 380), fill="black", width=6)
        im.save(diagram2)
        two = td / "two.pdf"
        doc = fitz.open()
        page = doc.new_page(width=900, height=700)
        page.insert_image(fitz.Rect(40, 40, 400, 280), filename=str(diagram_png))
        page.insert_text((40, 315), "Figure 1. First diagram", fontsize=12)
        page.insert_image(fitz.Rect(470, 40, 860, 280), filename=str(diagram2))
        page.insert_text((470, 315), "Figure 2. Second diagram", fontsize=12)
        vec = doc.new_page(width=900, height=700)
        vec.draw_rect(fitz.Rect(80, 80, 820, 420), color=(0, 0, 0), width=3)
        vec.draw_line((100, 450), (800, 100), color=(0, 0, 0), width=4)
        vec.draw_line((100, 100), (800, 450), color=(0, 0, 0), width=4)
        vec.insert_text((80, 470), "Figure 3. Vector-only diagram", fontsize=12)
        doc.save(two)
        doc.close()
        two_out = td / "two-out"
        r = subprocess.run([sys.executable, str(SCRIPTS / "extract_pdf.py"),
                            str(two), str(two_out), "--page-crops", "auto"],
                           capture_output=True, text=True, cwd=td)
        assert r.returncode == 0, (r.stdout, r.stderr)
        two_out = td / ".anki-gen-temp" / "two-out"
        figs = json.loads((two_out / "figures.json").read_text())
        embedded = [f for f in figs if f["kind"] == "embedded"]
        assert len(embedded) == 2, figs
        assert {f["caption"] for f in embedded} == {
            "Figure 1. First diagram", "Figure 2. Second diagram"}, figs
        assert all(f.get("bbox") for f in embedded), figs
        assert all(f.get("nearby_text") for f in embedded), figs
        crops = [f for f in figs if f["kind"] in ("page-crop", "slide-crop")]
        assert any(f["page"] == 2 for f in crops), figs
        assert all((two_out / f["file"]).is_file() for f in crops), figs
        print("ok    figure bbox/caption association and vector page crop")

        # Web fixture: relative URL, alt/figcaption, and a figures.json entry.
        web = td / "site"
        (web / "img").mkdir(parents=True)
        (web / "img" / "figure.png").write_bytes(diagram_png.read_bytes())
        (web / "index.html").write_text(
            '<html><body><h1>Unit Cells</h1>'
            '<figure><img src="img/figure.png" alt="FCC cell">'
            '<figcaption>Figure 4. FCC unit cell</figcaption></figure>'
            '<img src="data:image/png;base64,AAAA" alt="skip">'
            '</body></html>')
        from extract_pdf import extract_source
        web_result = extract_source(str(web / "index.html"), td / "web-out", stem="web")
        web_figs = json.loads((td / "web-out" / "figures.json").read_text())
        assert web_result["source_type"] == "url", web_result
        assert len(web_figs) == 1, web_figs
        assert web_figs[0]["file"].endswith(".png"), web_figs
        assert "FCC unit cell" in web_figs[0]["caption"], web_figs
        assert web_figs[0]["source_url"].startswith("file://"), web_figs
        print("ok    web image URL/alt/figcaption and figures.json")

        # Card-driven ranking prefers the same page/slide.
        cards = td / "rank.json"
        cards.write_text(json.dumps([
            {"front": "Which cell is shown in the first figure?",
             "back": "The first diagram.", "layer": "L2", "topic": "Unit Cells",
             "deck": "X", "source": "two.pdf p.1"},
            {"front": "Which cell is shown in the vector figure?",
             "back": "The vector diagram.", "layer": "L2", "topic": "Unit Cells",
             "deck": "X", "source": "two.pdf p.2"},
        ]))
        r = subprocess.run([sys.executable, str(SCRIPTS / "media_index.py"),
                            str(two_out), "--cards", str(cards), "--json"],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        ranked = json.loads(r.stdout)
        assert ranked[0]["candidates"][0]["page"] == 1, ranked[0]
        assert ranked[1]["candidates"][0]["page"] == 2, ranked[1]
        print("ok    card-driven figure ranking")

        # Vision metadata from the work report joins the same index.
        one = embedded[0]
        (two_out / "vision.jsonl").write_text(json.dumps({
            "file": str(two_out / one["file"]), "key": "x", "result": {
                "kind": "diagram", "usable_as_card_image": True,
                "shows": "FCC unit cell", "labels": ["FCC"]}}) + "\n")
        r = subprocess.run([sys.executable, str(SCRIPTS / "media_index.py"),
                            str(two_out), "--json"], capture_output=True, text=True)
        rows = json.loads(r.stdout)
        assert any(x.get("vision_kind") == "diagram" for x in rows), rows
        print("ok    vision metadata joins media index")

        # A bad date filter is an error, not an empty success.
        from extract_pdf import parse_flexible_date
        try:
            parse_flexible_date("not-a-date", __import__("datetime").datetime.now())
        except ValueError:
            pass
        else:
            raise AssertionError("bad date filter was accepted")

        # An explicit --out is the caller's path, not cwd/.anki-gen-temp/<name>.
        explicit = td / "explicit-out"
        r = subprocess.run([sys.executable, str(SCRIPTS / "extract_pdf.py"),
                            str(pdf), "--out", str(explicit)],
                           capture_output=True, text=True, cwd=td)
        assert r.returncode == 0, (r.stdout, r.stderr)
        assert (explicit / "source.md").is_file(), r.stdout
        print("ok    explicit --out is honored")

        # A zero-text, zero-image PDF fails the batch instead of counting as success.
        blank_pdf = td / "blank.pdf"
        doc = fitz.open()
        doc.new_page(width=300, height=300)
        doc.save(blank_pdf)
        doc.close()
        r = subprocess.run([sys.executable, str(SCRIPTS / "extract_pdf.py"),
                            "--batch", str(blank_pdf), "--out", str(td / "blank-out")],
                           capture_output=True, text=True, cwd=td)
        data = json.loads(r.stdout)
        assert data["failed"], data
        print("ok    empty source is a failed extract")

    cmd = ytdlp.cmd("-J", "https://example.invalid")
    assert cmd[:3] == [sys.executable, "-m", "yt_dlp"], cmd
    runtime, runtime_path = ytdlp.runtime()
    if runtime:
        assert runtime_path.is_file(), (runtime, runtime_path)
    req = (ROOT / "requirements.txt").read_text()
    assert "yt-dlp[default,deno]" in req
    assert "yt-dlp-ejs" in req and "deno>=" in req
    assert "--js-runtimes node" not in (SCRIPTS / "frames.py").read_text()
    print("ok    yt-dlp module and dependency wiring")

    assert ytdlp.is_transient("HTTP Error 429: Too Many Requests")
    assert ytdlp.is_transient("Connection reset by peer")
    assert not ytdlp.is_transient("There are no subtitles")
    assert not ytdlp.is_transient("This video is private")

    def transient(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, "",
                                           "HTTP Error 429: Too Many Requests")

    with mock.patch.object(ytdlp.subprocess, "run", side_effect=transient) as call, \
         mock.patch.object(ytdlp.time, "sleep") as slept:
        ytdlp.run(("--version",), attempts=3)
    assert call.call_count == 3 and slept.call_count == 2, (call.call_count, slept.call_count)

    def permanent(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, "", "There are no subtitles")

    with mock.patch.object(ytdlp.subprocess, "run", side_effect=permanent) as call:
        ytdlp.run(("--version",))
    assert call.call_count == 1, call.call_count
    print("ok    yt-dlp bounded retries")

    assert vision_check.pick_model(
        ["models/gemini-2.5-flash", "models/gemini-flash-lite-latest"]
    ) == "gemini-flash-lite-latest"
    assert vision_check.parse_json_text('```json\n{"kind": "diagram"}\n```')["kind"] == "diagram"

    from PIL import Image
    from urllib.error import HTTPError
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        png = td / "frame.png"
        Image.new("RGB", (32, 32), "white").save(png)
        cache = td / "cache.jsonl"
        calls = []

        def ok(model, key, path, *a, **kw):
            calls.append(model)
            return {"kind": "diagram", "usable_as_card_image": True}

        with mock.patch.object(vision_check, "request", side_effect=ok):
            row, cached = vision_check.confirm(png, "key", {}, cache)
            assert not cached and row["result"]["usable_as_card_image"]
            row, cached = vision_check.confirm(
                png, "key", vision_check.load_cache(cache), cache)
            assert cached and len(calls) == 1
        print("ok    vision_check cache")

        def flaky(model, key, path, *a, **kw):
            calls.append(model)
            if len(calls) < 3:
                raise HTTPError("u", 503, "unavailable", {}, None)
            return {"kind": "diagram", "usable_as_card_image": True}

        calls.clear()
        with mock.patch.object(vision_check, "request", side_effect=flaky), \
             mock.patch.object(vision_check.time, "sleep"):
            row, _ = vision_check.confirm(png, "key", {}, td / "cache2.jsonl")
        assert len(calls) == 3 and row["result"]["usable_as_card_image"]
        print("ok    vision_check retries")

        calls.clear()

        def fallback(model, key, path, *a, **kw):
            calls.append(model)
            if calls == ["gemini-flash-lite-latest"]:
                raise HTTPError("u", 404, "not found", {}, None)
            return {"kind": "diagram", "usable_as_card_image": True}

        with mock.patch.object(vision_check, "request", side_effect=fallback), \
             mock.patch.object(vision_check, "list_models",
                               return_value=["models/gemini-3.1-flash-lite"]), \
             mock.patch.object(vision_check, "MODEL_CACHE", td / "models.json"):
            row, _ = vision_check.confirm(png, "key", {}, td / "cache3.jsonl")
        assert len(calls) == 2 and row["result"]["usable_as_card_image"]
        print("ok    vision_check model fallback")

        second = td / "frame2.png"
        Image.new("RGB", (32, 32), "gray").save(second)
        calls.clear()

        def fake_confirm(path, key, cache, cache_path, *a, **kw):
            calls.append(str(path))
            return {"result": {"kind": "diagram", "usable_as_card_image": True}}, False

        with mock.patch.object(vision_check, "load_key", return_value="key"), \
             mock.patch.object(vision_check, "confirm", side_effect=fake_confirm), \
             mock.patch.object(sys, "argv",
                               ["vision_check.py", str(png), str(second), "--max", "1", "--report", str(td / "report1")]):
            vision_check.main()
        assert len(calls) == 1, calls
        print("ok    vision_check --max budget")

        calls.clear()

        def quota(path, key, cache, cache_path, *a, **kw):
            calls.append(str(path))
            raise HTTPError("u", 429, "quota", {}, None)

        with mock.patch.object(vision_check, "load_key", return_value="key"), \
             mock.patch.object(vision_check, "confirm", side_effect=quota), \
             mock.patch.object(sys, "argv",
                               ["vision_check.py", str(png), str(second), "--report", str(td / "report2")]):
            rc = vision_check.main()
        assert rc == 2 and len(calls) == 1, (rc, calls)
        print("ok    vision_check stops on 429")

    old_path = os.environ.get("PATH", "")
    try:
        with mock.patch.object(platform_paths.sys, "platform", "darwin"), \
             mock.patch.object(platform_paths.Path, "is_dir", return_value=True):
            os.environ["PATH"] = "/usr/bin:/bin"
            platform_paths.ensure_tool_paths()
            parts = os.environ["PATH"].split(os.pathsep)
            assert parts[:2] == ["/opt/homebrew/bin", "/usr/local/bin"], parts
            platform_paths.ensure_tool_paths()
            assert os.environ["PATH"].count("/opt/homebrew/bin") == 1, os.environ["PATH"]
        with mock.patch.object(platform_paths.sys, "platform", "linux"):
            os.environ["PATH"] = "/usr/bin:/bin"
            platform_paths.ensure_tool_paths()
            assert os.environ["PATH"] == "/usr/bin:/bin", os.environ["PATH"]
        print("ok    macOS Homebrew PATH fallback")
    finally:
        os.environ["PATH"] = old_path

    print("\nPASS  visual hardening")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
