"""Scan reconstructed pages for Chinese textbook section markers.

This version restricts LESSON detection to the page header area (first N
non-empty lines), which avoids false matches on body-text references like
ToC entries or "see Lesson 19" callouts.

Section detection (vocab/dialogue/narrative/etc.) still runs on the full page,
since those headers can appear anywhere a section starts.

Outputs:
  - manifest.json        page → {lesson, sections, header_line, first_line}
  - debug_pages.txt      one line per page showing what was detected (for sanity-checking)

Path argument:
  - Single book dir → process that book
  - /output (no page-*.txt directly) → process every book subdir

Usage:
    python find_sections.py /output
"""
import argparse
import json
import re
from pathlib import Path

# How many non-empty lines from the top of the page count as "header area".
# Headers, page numbers, and lesson titles are typically in the first ~3 lines;
# 5 gives some slack for OCR noise.
HEADER_LINES = 5

# Lesson markers — only matched in header area.
LESSON_PATTERNS = [
    re.compile(r"第\s*([一二三四五六七八九十百零兩\d]+)\s*課"),
    re.compile(r"\bLesson\s+(\d+)\b", re.IGNORECASE),
    re.compile(r"\bLESSON\s+(\d+)\b"),
]

# Within-page section markers — matched on full page text.
SECTION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"目\s*錄"), "toc"),
    (re.compile(r"序\s*言|前\s*言|緒\s*論|^序$|Preface|Introduction", re.IGNORECASE | re.MULTILINE), "preface"),
    (re.compile(r"生\s*字|字\s*表"), "new_characters"),
    (re.compile(r"新\s*詞|生\s*詞|詞\s*彙"), "new_words"),
    (re.compile(r"詞\s*語|語\s*法|Grammar", re.IGNORECASE), "grammar"),
    (re.compile(r"例\s*句"), "example_sentences"),
    (re.compile(r"對\s*話|Dialogue", re.IGNORECASE), "dialogue"),
    (re.compile(r"敘\s*述|短\s*文|課\s*文|Narrative", re.IGNORECASE), "narrative"),
    (re.compile(r"英\s*譯|翻\s*譯|Translation", re.IGNORECASE), "translation"),
    (re.compile(r"練\s*習|Exercise", re.IGNORECASE), "exercises"),
    (re.compile(r"注\s*釋|注\s*解|Notes", re.IGNORECASE), "notes"),
]

CN_DIGIT = {"零": 0, "一": 1, "二": 2, "兩": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9}


def parse_lesson_number(s: str) -> int | None:
    """Convert '一', '二十五', '45', '十' etc. to an int. Returns None if unparseable."""
    s = s.strip()
    if s.isdigit():
        return int(s)

    # Chinese number — handle up to '九十九'/'一百X'
    if "百" in s:
        before, _, after = s.partition("百")
        hundreds = CN_DIGIT.get(before, 1) if before else 1
        rest = parse_lesson_number(after) if after else 0
        return hundreds * 100 + (rest or 0)
    if "十" in s:
        before, _, after = s.partition("十")
        tens = CN_DIGIT.get(before, 1) if before else 1
        ones = CN_DIGIT.get(after, 0) if after else 0
        return tens * 10 + ones
    if len(s) == 1 and s in CN_DIGIT:
        return CN_DIGIT[s]
    return None


def find_header_lesson(layout_text: str) -> tuple[str | None, str]:
    """Return (lesson_label, matched_header_line) or (None, '') if no match."""
    lines = [l.strip() for l in layout_text.splitlines() if l.strip()]
    for line in lines[:HEADER_LINES]:
        for pat in LESSON_PATTERNS:
            m = pat.search(line)
            if m:
                return m.group(1), line
    return None, ""


def find_body_sections(text: str) -> list[str]:
    return [label for pat, label in SECTION_PATTERNS if pat.search(text)]


def text_files_for_book(book_dir: Path) -> list[Path]:
    layout = sorted(book_dir.glob("page-*.layout.txt"))
    if layout:
        return layout
    return sorted(p for p in book_dir.glob("page-*.txt") if not p.name.endswith(".layout.txt"))


def has_text_files(d: Path) -> bool:
    return any(d.glob("page-*.txt")) or any(d.glob("page-*.layout.txt"))


def find_book_dirs(path: Path) -> list[Path]:
    if has_text_files(path):
        return [path]
    return sorted(d for d in path.iterdir() if d.is_dir() and has_text_files(d))


def process_book(book_dir: Path) -> None:
    text_files = text_files_for_book(book_dir)
    if not text_files:
        print(f"[sections] {book_dir.name}: no text files", flush=True)
        return

    pages: list[dict] = []
    debug_lines: list[str] = []
    current_lesson: str | None = None

    for tp in text_files:
        page_num_str = tp.stem.split("-")[-1].replace(".layout", "")
        try:
            page_num = int(page_num_str)
        except ValueError:
            continue
        text = tp.read_text(encoding="utf-8")

        header_lesson, header_line = find_header_lesson(text)
        sections = find_body_sections(text)
        first_line = next((l.strip() for l in text.splitlines() if l.strip()), "")

        # A page only TRIGGERS a lesson change when its header has an explicit lesson marker.
        # Pages without headers inherit the previous lesson.
        is_lesson_start = False
        if header_lesson is not None and header_lesson != current_lesson:
            current_lesson = header_lesson
            is_lesson_start = True

        page_record = {
            "page": page_num,
            "lesson": current_lesson,
            "header_lesson": header_lesson,
            "is_lesson_start": is_lesson_start,
            "sections": sections,
            "header_line": header_line,
            "first_line": first_line,
        }
        pages.append(page_record)

        debug_lines.append(
            f"p{page_num:04d} | lesson={current_lesson or '-':<6} "
            f"| header={header_lesson or '-':<6} "
            f"| sec={','.join(sections) or '-':<40} "
            f"| {first_line[:60]}"
        )

    # Write outputs
    (book_dir / "manifest.json").write_text(
        json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (book_dir / "debug_pages.txt").write_text("\n".join(debug_lines), encoding="utf-8")

    # Summary
    lesson_pages: dict[str, list[int]] = {}
    section_counts: dict[str, int] = {}
    lesson_starts = 0
    for p in pages:
        if p["lesson"]:
            lesson_pages.setdefault(p["lesson"], []).append(p["page"])
        if p["is_lesson_start"]:
            lesson_starts += 1
        for s in p["sections"]:
            section_counts[s] = section_counts.get(s, 0) + 1

    # Sort lessons by parsed number when possible
    def lesson_sort_key(label: str) -> tuple[int, str]:
        n = parse_lesson_number(label)
        return (n if n is not None else 9999, label)

    print(f"[sections] {book_dir.name}: {len(pages)} pages → manifest.json + debug_pages.txt", flush=True)
    print(f"  unique lessons: {len(lesson_pages)} (lesson_start events: {lesson_starts})", flush=True)
    for lesson_num in sorted(lesson_pages, key=lesson_sort_key):
        pgs = lesson_pages[lesson_num]
        n = parse_lesson_number(lesson_num)
        print(f"    {lesson_num} ({'?' if n is None else f'#{n}'}): pages {min(pgs)}-{max(pgs)} ({len(pgs)} pages)", flush=True)
    print(f"  section markers (page count):", flush=True)
    for label, count in sorted(section_counts.items(), key=lambda x: -x[1]):
        print(f"    {label}: {count}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    args = ap.parse_args()

    books = find_book_dirs(args.path)
    if not books:
        print(f"No text files under {args.path}")
        return
    for book in books:
        process_book(book)


if __name__ == "__main__":
    main()
