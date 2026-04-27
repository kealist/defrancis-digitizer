"""Run PaddleOCR 3.x on PNGs in /images/<book>/ and write results to /output/<book>/.

Resilient version:
  - Per-page try/except — one bad page won't kill the whole run.
  - failures.log records the page number and traceback for any errors.
  - Live progress with rate and ETA so you can tell it's not stuck.
  - Summary at the end shows completed / skipped / failed counts.

Idempotent: a page is only marked done if BOTH .txt and .json got written.
A failed page leaves no output, so re-running retries just the failures.
"""
import json
import time
import traceback
from pathlib import Path

from paddleocr import PaddleOCR

IMAGES = Path("/images")
OUTPUT = Path("/output")


def extract_records(res) -> tuple[list[str], list[dict]]:
    """Pull (texts, [{text, confidence, box}, ...]) out of a PaddleOCR 3.x result."""
    data = res.json
    payload = data.get("res", data) if isinstance(data, dict) else {}

    rec_texts = payload.get("rec_texts", []) or []
    rec_scores = payload.get("rec_scores", []) or []
    rec_polys = payload.get("rec_polys", []) or []

    lines: list[str] = []
    records: list[dict] = []
    for i, text in enumerate(rec_texts):
        score = float(rec_scores[i]) if i < len(rec_scores) else 0.0
        poly = rec_polys[i] if i < len(rec_polys) else []
        if hasattr(poly, "tolist"):
            poly = poly.tolist()
        elif poly and hasattr(poly[0], "tolist"):
            poly = [p.tolist() for p in poly]

        lines.append(text)
        records.append({"text": text, "confidence": score, "box": poly})
    return lines, records


def main() -> None:
    print("Initializing PaddleOCR (PP-OCRv5 multilingual)", flush=True)
    print("First run downloads model weights (~few hundred MB) — cached after.", flush=True)
    ocr = PaddleOCR(
        use_textline_orientation=True,
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
    )

    book_dirs = sorted(d for d in IMAGES.iterdir() if d.is_dir())
    if not book_dirs:
        print("No image directories in /images. Run preprocess first.", flush=True)
        return

    for book_dir in book_dirs:
        out_dir = OUTPUT / book_dir.name
        out_dir.mkdir(parents=True, exist_ok=True)
        failure_log = out_dir / "failures.log"

        pages = sorted(book_dir.glob("page-*.png"))
        total = len(pages)
        print(f"\n[ocr] {book_dir.name}: {total} pages", flush=True)

        all_pages_text: list[str] = []
        completed = 0
        skipped = 0
        failed: list[str] = []
        start = time.time()

        for idx, img in enumerate(pages, 1):
            page_num = img.stem.split("-")[-1]
            txt_out = out_dir / f"page-{page_num}.txt"
            json_out = out_dir / f"page-{page_num}.json"

            if txt_out.exists() and json_out.exists():
                skipped += 1
                all_pages_text.append(
                    f"=== Page {page_num} ===\n{txt_out.read_text(encoding='utf-8')}"
                )
                if idx % 25 == 0:
                    print(f"  [skip] up to page {page_num} ({idx}/{total})", flush=True)
                continue

            try:
                result = ocr.predict(str(img))

                page_lines: list[str] = []
                page_records: list[dict] = []
                for res in result:
                    lines, records = extract_records(res)
                    page_lines.extend(lines)
                    page_records.extend(records)

                txt_out.write_text("\n".join(page_lines), encoding="utf-8")
                json_out.write_text(
                    json.dumps(page_records, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                all_pages_text.append(
                    f"=== Page {page_num} ===\n" + "\n".join(page_lines)
                )
                completed += 1

                elapsed = time.time() - start
                rate = completed / elapsed if elapsed > 0 and completed else 0
                remaining = total - idx
                eta = remaining / rate if rate > 0 else 0
                print(
                    f"  [ocr]  page {page_num}  ({idx}/{total}, "
                    f"{rate:.2f} pg/s, ~{eta/60:.1f} min remaining)",
                    flush=True,
                )

            except Exception as e:
                failed.append(page_num)
                with failure_log.open("a", encoding="utf-8") as fh:
                    fh.write(f"=== page {page_num} ({img.name}) ===\n")
                    fh.write(f"{type(e).__name__}: {e}\n")
                    fh.write(traceback.format_exc())
                    fh.write("\n")
                print(
                    f"  [FAIL] page {page_num} ({idx}/{total}): "
                    f"{type(e).__name__}: {e}",
                    flush=True,
                )

        # Write the rolling concatenation even on partial runs
        (out_dir / "full.txt").write_text(
            "\n\n".join(all_pages_text), encoding="utf-8"
        )

        elapsed = time.time() - start
        print(
            f"[done] {book_dir.name}: "
            f"{completed} new, {skipped} skipped, {len(failed)} failed "
            f"in {elapsed/60:.1f} min",
            flush=True,
        )
        if failed:
            print(f"       failed pages: {', '.join(failed)}", flush=True)
            print(f"       see {failure_log} for tracebacks", flush=True)
            print(f"       re-run `docker compose up` to retry just the failed pages", flush=True)


if __name__ == "__main__":
    main()
