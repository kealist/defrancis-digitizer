# Reconstructing the Book

Workflow for turning the OCR output into a structured digital textbook.

## Phase 1 — Recover layout

Your `page-NNN.txt` files lost the column structure of vocabulary tables (character | pinyin | meaning rows are mashed flat). The `page-NNN.json` files preserve bounding boxes, so columns can be recovered geometrically.

```bash
python reconstruct/reconstruct_layout.py output/<your-book>/
```

This produces a `page-NNN.layout.txt` next to each `page-NNN.json`, plus a combined `full.layout.txt`. Multi-column rows show up as `col1 | col2 | col3`. Single-line text is unchanged.

Open a few vocab pages and a few prose pages in `full.layout.txt` to spot-check. If columns are merging in vocab tables, increase `gap_factor` in the script (default 1.5 — try 1.2). If unrelated lines are being treated as columns, decrease it (try 2.0).

## Phase 2 — Find sections

Scan all pages for Chinese textbook section markers (生字, 新詞, 對話, 敘述, 例句, 第X課, 練習, 目錄, 序 …) and produce a manifest.

```bash
python reconstruct/find_sections.py output/<your-book>/
```

Output: `manifest.json` listing every page with its detected lesson number and section markers, plus a summary printed to console:

```
Detected lessons: 24
  Lesson 一: pages 12-19 (8 pages)
  Lesson 二: pages 20-28 (9 pages)
  ...
Section markers found (page count):
  new_characters: 24
  dialogue: 31
  narrative: 28
  ...
```

**Expect to clean this up by hand.** OCR errors, decorative section breaks, and pages that span sections will mean some pages get classified wrong or missed. Open `manifest.json` in any text editor and edit it directly. The `first_line` field on each entry helps you scan for issues quickly.

## Phase 3 — Assemble structured output

This is where it gets project-specific. Each section type wants a different shape:

| Section            | Output shape                                           |
| ------------------ | ------------------------------------------------------ |
| New characters     | `[{char, pinyin, meaning}, ...]`                       |
| New words / 詞語   | `[{word, pinyin, meaning, example}, ...]`              |
| Example sentences  | `[{chinese, pinyin?, english}, ...]` (paired w/ trans) |
| Dialogue           | `[{speaker?, line}, ...]`                              |
| Narrative          | Cleaned prose paragraphs                               |

**My recommendation:** drive Phase 3 with the Anthropic API. The reconstructed page text plus the page image is plenty of context for Claude to produce clean structured JSON for one section at a time. The pattern looks like:

```python
import anthropic, base64, json
from pathlib import Path

client = anthropic.Anthropic()

def extract_vocab(layout_text: str, image_path: Path) -> list[dict]:
    img_b64 = base64.standard_b64encode(image_path.read_bytes()).decode()
    msg = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=4000,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {
                    "type": "base64", "media_type": "image/png", "data": img_b64,
                }},
                {"type": "text", "text": (
                    "This is a page from a Traditional Chinese language textbook "
                    "showing a vocabulary table. The OCR'd text with column "
                    "markers is below. Return a JSON array of "
                    "{character, pinyin, meaning} objects, one per row. Fix "
                    "obvious OCR errors using the image. Return JSON only, no "
                    "prose.\n\n" + layout_text
                )},
            ],
        }],
    )
    return json.loads(msg.content[0].text)
```

Why this works well for your case:
- Vision gives Claude the image to fix OCR mistakes (especially helpful for rare Traditional characters and tone marks).
- One section per call keeps the output schema simple and the cost low.
- The manifest tells you which pages and which section type, so you can dispatch to the right extractor automatically.

If you'd rather not use an API, the alternative is per-section regex-based extractors. Workable for vocab tables (the layout reconstruction does most of the work — you just split each row on ` | `), painful for dialogues and narratives.

## Suggested order of operations

1. Run Phase 1 (`reconstruct_layout.py`) on your full book.
2. Eyeball 5–10 pages of different types — vocab, dialogue, narrative — to confirm the layout reconstruction looks reasonable.
3. Run Phase 2 (`find_sections.py`) to get `manifest.json`.
4. Manually clean up `manifest.json` — fix lesson boundaries, missed section markers, mis-detections. Plan ~30 minutes per ~10 lessons.
5. Build out Phase 3 one section type at a time. Start with `new_characters` (simplest schema), then `example_sentences`, then prose sections.
6. Output one Markdown file per lesson, then assemble the book.

Phase 3 is where I'd write more code if you want help — let me know which section type you want to tackle first and I'll build out the extractor for it.
