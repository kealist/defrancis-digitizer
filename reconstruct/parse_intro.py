"""
Parse DeFrancis Reader front-matter pages (before Lesson 1) into intro.md.

Usage:
    python parse_intro.py <book_dir> <output_md>

Example:
    python parse_intro.py output/"Beginning Chinese Reader..." lessons/Introduction.md
"""
import re
import sys
from pathlib import Path

LESSON_START = re.compile(r"^Lesson\s+1\s*$", re.IGNORECASE)

# All-caps section openers (first page of each section)
SECTION_MAP = {
    "ACKNOWLEDGMENTS": "## Acknowledgments",
    "PREFACE TO SECOND EDITION": "## Preface to the Second Edition",
    "PREFACE TO FIRST EDITION": "## Preface to the First Edition",
    "PROBLEMS IN READING CHINESE": "## Problems in Reading Chinese",
    "PROBLEMS IN READING  CHINESE": "## Problems in Reading Chinese",
    "SUGGESTIONS FOR STUDY": "## Suggestions for Study",
}

# Running page-header lines on continuation pages — strip these.
# Intentionally NOT re.IGNORECASE: all-caps versions are section openers (not noise).
RUNNING_HEADER = re.compile(
    r"^(?:Preface to (?:Second|First) Edition"
    r"|Problems in Reading Chinese"
    r"|Suggestions for Study)\s*$",
)

# Roman-numeral or short arabic page numbers
PAGE_NUM = re.compile(r"^[xivlXIVL\d]{1,7}\s*$")

# Footnote markers and lines
FOOTNOTE = re.compile(r"^\*\s|^\(\d+\)\s")

# Hyphen at end of line (soft wrap) — join to next
SOFT_HYPHEN = re.compile(r"-$")


def is_section_header(line):
    s = " ".join(line.strip().split())
    return SECTION_MAP.get(s.upper())


def is_noise(line):
    s = line.strip()
    if not s:
        return False
    if RUNNING_HEADER.match(s):
        return True
    if PAGE_NUM.match(s) and len(s) <= 8:
        return True
    # Stray single-character OCR artifacts
    if len(s) == 1 and not s.isalnum():
        return True
    return False


def join_paragraphs(lines):
    """Join soft-wrapped prose lines into paragraphs, splitting on blank lines."""
    paragraphs = []
    current = []
    for line in lines:
        s = line.rstrip()
        if not s.strip():
            if current:
                paragraphs.append(" ".join(current))
                current = []
        else:
            # De-hyphenate soft wraps
            if current and SOFT_HYPHEN.search(current[-1]):
                current[-1] = current[-1].rstrip("-")
                current[-1] += s.strip()
            else:
                current.append(s.strip())
    if current:
        paragraphs.append(" ".join(current))
    return [p for p in paragraphs if p.strip()]


def _fix_ocr_num(s):
    """Fix OCR substitutions: lowercase-l for digit-1 in numbers (ll→11, l4→14)."""
    s = re.sub(r"\bll\b", "11", s)          # ll → 11
    s = re.sub(r"\bl(\d)", r"1\1", s)       # l4 → 14
    s = re.sub(r"(\d)l\b", r"\g<1>1", s)   # 4l → 41
    return s


ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]


def parse_toc_pages(pages):
    """Return TOC entries from the layout pages, with UNIT sub-headers."""
    lines = []
    unit_count = 0
    for _, text in pages:
        for line in text.splitlines():
            s = line.strip()
            if not s:
                continue
            # Skip noise / roman-numeral page numbers
            if re.match(r"^(Beginning Chinese Reader|[ixXIVl]+\s*$)", s, re.I):
                continue
            # "Contents of Part N" → part label
            m = re.match(r"^Contents of Part\s+(\w+)", s, re.I)
            if m:
                lines.append(f"\n**Part {m.group(1)}**\n")
                continue
            # UNIT header — OCR unit numbers are unreliable, auto-number sequentially
            if re.match(r"^UNIT\b", s, re.I):
                unit_count += 1
                roman = ROMAN[unit_count - 1] if unit_count <= len(ROMAN) else str(unit_count)
                lines.append(f"\n*Unit {roman}*")
                continue
            # Normalise separator junk (pipes, middle-dots, ellipses, periods, spaces, dashes)
            # into a single space, so every line becomes "<label> <page>".
            clean = re.sub(r"[\s|·….\-]+", " ", s).strip()
            # Lesson entry: "Lesson <N> <page>"
            if re.match(r"^Lesson\s+", clean, re.I):
                m = re.match(r"^Lesson\s+([\dIVXivxl]+)\s+(\d+)\s*$", clean, re.I)
                if m:
                    raw_num = _fix_ocr_num(m.group(1))
                    try:
                        num = int(raw_num)
                    except ValueError:
                        num = raw_num
                    lines.append(f"- Lesson {num} — p. {m.group(2)}")
                else:
                    # Lesson line with no page number (OCR missed it)
                    m2 = re.match(r"^Lesson\s+([\dIVXivxl]+)\s*$", clean, re.I)
                    if m2:
                        raw_num = _fix_ocr_num(m2.group(1))
                        try:
                            num = int(raw_num)
                        except ValueError:
                            num = raw_num
                        lines.append(f"- Lesson {num}")
            elif re.match(r"^[A-Z]", clean):
                # Named section with a trailing page number
                m = re.match(r"^(.+?)\s+(\d+|[xivXIVl]{2,})\s*$", clean)
                if m:
                    lines.append(f"- {m.group(1)} — p. {m.group(2)}")
    return lines


def main():
    if len(sys.argv) < 3:
        print("Usage: parse_intro.py <book_dir> <output_md>", file=sys.stderr)
        sys.exit(1)

    book_dir = Path(sys.argv[1])
    output_md = Path(sys.argv[2])

    pages = sorted(
        p for p in book_dir.glob("page-*.layout.txt")
        if re.match(r"page-\d+\.layout\.txt", p.name)
    )

    # Collect intro pages (stop before Lesson 1)
    intro_pages = []
    for page in pages:
        text = page.read_text(encoding="utf-8")
        if any(LESSON_START.match(line.strip()) for line in text.splitlines()):
            break
        page_num = int(re.search(r"(\d+)", page.name).group(1))
        intro_pages.append((page_num, text))

    print(f"Found {len(intro_pages)} intro pages")

    # Split into labelled groups
    title_lines = []
    copyright_lines = []
    toc_pages = []
    sections = []          # [(header_md, [raw_lines])]
    current_header = None
    current_lines = []

    for page_num, text in intro_pages:
        raw_lines = text.splitlines()

        if page_num == 1:
            title_lines = raw_lines
            continue

        if page_num == 2:
            copyright_lines = raw_lines
            continue

        if page_num in (3, 4):
            toc_pages.append((page_num, text))
            continue

        for line in raw_lines:
            if is_noise(line):
                continue

            hdr = is_section_header(line)
            if hdr:
                if current_header is not None:
                    sections.append((current_header, current_lines))
                current_header = hdr
                current_lines = []
                continue

            current_lines.append(line)

        current_lines.append("")  # paragraph gap between pages

    if current_header is not None:
        sections.append((current_header, current_lines))

    # ── Build markdown ──────────────────────────────────────────────────────────
    out = []

    # Title block
    out.append("# Beginning Chinese Reader\n")
    skip_title_noise = re.compile(
        r"^(?:BEGINNING|CHINESE\s+READER?|BEGINNING\s+CHINESE\s*READER?)\s*$",
        re.IGNORECASE,
    )
    for line in title_lines:
        s = line.strip()
        if not s or skip_title_noise.match(s):
            continue
        if s.upper().startswith("PART"):
            out.append(f"**{s}**\n")
        elif re.match(r"^by\b", s, re.IGNORECASE):
            out.append(f"*{s}*\n")
        elif s.upper().startswith("WITH THE"):
            out.append(f"*{s}*\n")
        elif s.upper().startswith("SECOND EDITION"):
            out.append(f"*Second Edition*\n")
        else:
            out.append(f"{s}\n")

    out.append("\n---\n")

    # Copyright
    if copyright_lines:
        out.append("## Publication Information\n")
        for para in join_paragraphs(copyright_lines):
            out.append(para + "\n")
        out.append("\n---\n")

    # Table of Contents
    toc_entries = parse_toc_pages(toc_pages)
    if toc_entries:
        out.append("## Contents\n")
        out.append("\n".join(toc_entries))
        out.append("\n\n---\n")

    # Named sections
    for header, lines in sections:
        out.append(f"{header}\n")
        for para in join_paragraphs(lines):
            out.append(para + "\n")
        out.append("\n---\n")

    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text("\n".join(out), encoding="utf-8")
    print(f"Written: {output_md}")


if __name__ == "__main__":
    main()
