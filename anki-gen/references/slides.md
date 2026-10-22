# PowerPoint sources

`.pptx` is a ZIP of XML, not a reason to install Office.

`extract_pdf.py slides.pptx <work> --tag <tag>` routes to `extract_slides.py`, which reads:

- slide text and order from `ppt/slides/slideN.xml`;
- speaker notes from the slide relationship target;
- embedded raster images from `ppt/media/`, filtered with the same visual score as PDF figures.

Output is `<tag>.md` plus `media/slideNN_imgM.*` and `figures.json`; cite `source @ slide N`.
A diagram made only of PowerPoint shapes is **not rendered**. Cite the slide, or use a PDF export
through `extract_pdf.py`; never use LibreOffice/`soffice`/Office. Ask for a PDF when full visual
fidelity matters. For PDF lecture decks, `extract_pdf.py` also writes tight `slide-crop`
candidates (caption/title/nearby-text association, `confirm` only); use
`media_index.py <work> --cards cards.jsonl` to rank them.

Do not download a random PPTX to replace missing video frames. Use slides when they are the real
source or the user provides them; otherwise cite the video/slide and skip the image.
