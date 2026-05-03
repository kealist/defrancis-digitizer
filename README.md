# OCR Pipeline — Traditional Chinese (+ English) PDFs

Two-stage Docker Compose pipeline:

1. **preprocess** — converts PDFs to 300 DPI PNGs (poppler / `pdf2image`).
2. **ocr** — runs PaddleOCR (`chinese_cht`) on each page, writes `.txt` + `.json` per page and a concatenated `full.txt` per book.

## Layout

```
ocr-pipeline/
├── docker-compose.yml
├── ocr/
│   ├── Dockerfile
│   ├── preprocess.py
│   └── ocr.py
├── input/      ← drop your PDFs here
├── images/     ← intermediate PNGs (created on first run)
└── output/     ← OCR results (created on first run)
```

## Usage

```bash
mkdir -p input images output
cp /path/to/textbook.pdf input/

docker compose build
docker compose up           # runs preprocess, then ocr, then exits
```

Output for `input/textbook.pdf` lands in `output/textbook/`:

- `page-001.txt`, `page-002.txt`, … — plain text per page
- `page-001.json`, `page-002.json`, … — `{text, confidence, box}` records (for re-flowing lists/tables)
- `full.txt` — all pages concatenated

Both stages are **idempotent** — re-running skips PDFs/pages already done. To force a redo, delete the relevant directory under `images/` or `output/`.

## Common tweaks

**Different language.** Edit `OCR_LANG` in `docker-compose.yml`:

| Value          | Recognizes                       |
| -------------- | -------------------------------- |
| `chinese_cht`  | Traditional Chinese + English    |
| `ch`           | Simplified Chinese + English     |
| `en`           | English only                     |
| `japan`        | Japanese                         |
| `korean`       | Korean                           |

PaddleOCR's Chinese models recognize English in the same pass — no need to combine languages.

**Higher accuracy on weak scans.** Bump `DPI = 300` to `400` in `preprocess.py`. Slower and bigger files, but helps with small print and stylized fonts. For really rough scans, run them through `unpaper` or ImageMagick (`-deskew 40% -despeckle`) before dropping into `input/`.

**GPU.** Uncomment the `deploy:` block in `docker-compose.yml` and replace `paddlepaddle==2.6.1` with `paddlepaddle-gpu==2.6.1` in the Dockerfile. Requires `nvidia-container-toolkit` on the host. About 5–10× faster on a textbook.

**Apple Silicon (M1/M2/M3).** The pinned `paddlepaddle` x86 wheel runs under Rosetta — it works but is slow. For native ARM, you'll need to install paddlepaddle from source or use a community ARM wheel; no clean pip path as of writing.

## Audio Generation (Text-to-Speech)

After OCR and lesson parsing, generate MP3 audio files organized by section with multi-voice dialogs:

```bash
docker compose --profile tts build --no-cache tts_multivoice
docker compose --profile tts up tts_multivoice
```

This generates:
- `lesson-NNN-illustrative.mp3` — All illustrative sentences per lesson
- `lesson-NNN-narrative.mp3` — All narrative paragraphs per lesson (automatically numbered)
- `lesson-NNN-dialogs.mp3` — All dialogs combined with different voices per character

**Features:**
- **Multi-voice dialogs**: Each character speaker is assigned a unique voice from an 8-voice pool (Taiwanese, Mainland Chinese, Hong Kong variants)
- **Voice persistence**: Speaker-to-voice mapping saved in `audio/voice_mapping.json` — same character uses the same voice across all lessons
- **Sentence splitting**: Narratives and illustrative sentences are split by punctuation for natural-sounding pacing
- **Automatic retry**: Failed API requests retry with exponential backoff (2s → 4s → 8s)
- **Graceful error handling**: Failed segments are skipped; processing continues

**Output:**
```
audio/
├── voice_mapping.json                (speaker → voice assignments)
├── lesson-001-illustrative.mp3
├── lesson-001-narrative.mp3
├── lesson-001-dialogs.mp3
├── lesson-002-illustrative.mp3
...
```

**Configuration:**
Edit the `delay` parameter in `tts_multivoice.py` (default: 2 seconds between API calls) to adjust rate limiting. Use 2–3 seconds to avoid 503 errors from the Bing API.

## What about the lists?

The `page-NNN.json` files include bounding boxes for every detected text region. For vocabulary lists where columns matter (e.g., Chinese | Pinyin | English), you can sort the records by `box[0][1]` (y) then `box[0][0]` (x), or cluster by x-coordinate to recover the column structure. This is the part that PaddleOCR alone won't do for you — if you'd rather have the layout reconstructed automatically into Markdown tables, swap in MinerU instead.
