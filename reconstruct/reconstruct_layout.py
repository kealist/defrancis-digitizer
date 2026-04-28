"""Reconstruct page layout from PaddleOCR bounding boxes.

Reads page-NNN.json files (PaddleOCR output) and produces page-NNN.layout.txt
files where multi-column structures (vocab tables) are preserved with ' | '
column separators.

Path argument:
  - If the path contains page-*.json directly → treat as a single book.
  - Otherwise → process every subdirectory that contains page-*.json
    (so passing /output processes all books at once).

Usage:
    python reconstruct_layout.py /output                # all books
    python reconstruct_layout.py /output/textbook       # one specific book
"""
import argparse
import json
from pathlib import Path


def load_records(json_path: Path) -> list[dict]:
    records = json.loads(json_path.read_text(encoding="utf-8"))
    out = []
    for r in records:
        box = r.get("box") or []
        if not box or len(box) < 2:
            continue
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        r["x_min"], r["x_max"] = min(xs), max(xs)
        r["y_min"], r["y_max"] = min(ys), max(ys)
        r["x_center"] = (r["x_min"] + r["x_max"]) / 2
        r["y_center"] = (r["y_min"] + r["y_max"]) / 2
        r["height"] = max(r["y_max"] - r["y_min"], 1.0)
        r["width"] = max(r["x_max"] - r["x_min"], 1.0)
        out.append(r)
    return out


def group_into_rows(records: list[dict], y_overlap: float = 0.4) -> list[list[dict]]:
    if not records:
        return []
    records = sorted(records, key=lambda r: r["y_center"])
    rows: list[list[dict]] = [[records[0]]]
    for r in records[1:]:
        last_row = rows[-1]
        row_ymin = min(x["y_min"] for x in last_row)
        row_ymax = max(x["y_max"] for x in last_row)
        row_h = row_ymax - row_ymin
        overlap = min(r["y_max"], row_ymax) - max(r["y_min"], row_ymin)
        ref_h = min(r["height"], row_h)
        if ref_h > 0 and overlap > y_overlap * ref_h:
            last_row.append(r)
        else:
            rows.append([r])
    for row in rows:
        row.sort(key=lambda r: r["x_center"])
    return rows


def format_row(row: list[dict], gap_factor: float = 1.5) -> str:
    if not row:
        return ""
    if len(row) == 1:
        return row[0]["text"]
    parts = [row[0]["text"]]
    for i in range(1, len(row)):
        prev = row[i - 1]
        curr = row[i]
        gap = curr["x_min"] - prev["x_max"]
        ref = (prev["height"] + curr["height"]) / 2
        if gap > gap_factor * ref:
            parts.append(" | ")
        else:
            parts.append(" ")
        parts.append(curr["text"])
    return "".join(parts)


def reconstruct_page(json_path: Path) -> str:
    records = load_records(json_path)
    rows = group_into_rows(records)
    return "\n".join(format_row(row) for row in rows if row)


def find_book_dirs(path: Path) -> list[Path]:
    """If path holds page-*.json directly it's a book; else its subdirs are."""
    if list(path.glob("page-*.json")):
        return [path]
    return sorted(d for d in path.iterdir() if d.is_dir() and list(d.glob("page-*.json")))


def process_book(book_dir: Path) -> None:
    json_files = sorted(book_dir.glob("page-*.json"))
    print(f"[layout] {book_dir.name}: {len(json_files)} pages", flush=True)

    for jp in json_files:
        layout = reconstruct_page(jp)
        # Use double suffix so it sits next to page-NNN.json, page-NNN.txt cleanly
        out = jp.with_name(f"{jp.stem}.layout.txt")
        out.write_text(layout, encoding="utf-8")

    # Combined view
    all_pages = []
    for jp in json_files:
        page_num = jp.stem.split("-")[-1]
        layout = jp.with_name(f"{jp.stem}.layout.txt").read_text(encoding="utf-8")
        all_pages.append(f"=== Page {page_num} ===\n{layout}")
    (book_dir / "full.layout.txt").write_text("\n\n".join(all_pages), encoding="utf-8")
    print(f"[layout] {book_dir.name} → full.layout.txt", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path, help="Path to /output (all books) or one book dir")
    args = ap.parse_args()

    books = find_book_dirs(args.path)
    if not books:
        print(f"No page-*.json files under {args.path}")
        return
    for book in books:
        process_book(book)


if __name__ == "__main__":
    main()
