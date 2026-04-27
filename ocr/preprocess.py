"""Convert every PDF in /input to 300 DPI PNGs in /images/<pdf-stem>/.

Streams pages in small batches so progress is visible on large PDFs.
Idempotent: resumes from the last saved page if interrupted.
"""
import time
from pathlib import Path
from pdf2image import convert_from_path, pdfinfo_from_path

INPUT = Path("/input")
OUTPUT = Path("/images")
DPI = 300
BATCH_SIZE = 5  # pages per batch — smaller = more frequent progress, slightly slower


def main() -> None:
    pdfs = sorted(INPUT.glob("*.pdf"))
    if not pdfs:
        print("No PDFs found in ./input/. Drop a .pdf in there and re-run.")
        return

    for pdf in pdfs:
        out_dir = OUTPUT / pdf.stem
        out_dir.mkdir(parents=True, exist_ok=True)

        info = pdfinfo_from_path(str(pdf))
        total = info["Pages"]

        existing = len(list(out_dir.glob("page-*.png")))
        if existing >= total:
            print(f"[skip]    {pdf.name} (all {total} pages already converted)")
            continue

        if existing:
            print(f"[resume]  {pdf.name}: {existing}/{total} already done")
        print(f"[convert] {pdf.name}: {total} pages @ {DPI} DPI")
        start = time.time()

        for first in range(existing + 1, total + 1, BATCH_SIZE):
            last = min(first + BATCH_SIZE - 1, total)
            pages = convert_from_path(
                str(pdf),
                dpi=DPI,
                fmt="png",
                first_page=first,
                last_page=last,
                thread_count=2,
            )
            for offset, page in enumerate(pages):
                page_num = first + offset
                page.save(out_dir / f"page-{page_num:03d}.png", "PNG")

            elapsed = time.time() - start
            done = last - existing
            remaining = total - last
            rate = done / elapsed if elapsed > 0 else 0
            eta = remaining / rate if rate > 0 else 0
            print(
                f"  [page]  {last}/{total}  "
                f"({rate:.2f} pages/sec, ~{eta:.0f}s remaining)"
            )

        print(f"[convert] {pdf.name} done in {time.time()-start:.1f}s")


if __name__ == "__main__":
    main()
