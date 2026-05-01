"""
Parse DeFrancis Reader OCR output into per-lesson markdown files.

Usage:
    python parse_lessons.py <output_dir> <lessons_dir> [--lessons 1-10]

Example:
    python parse_lessons.py /output /lessons --lessons 1-10
"""
import argparse
import re
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict

# ── Unicode helpers ────────────────────────────────────────────────────────────

TONE_MARKS = set("āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ")


def is_chinese(ch):
    return "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿"


def chinese_ratio(s):
    chars = [c for c in s if not c.isspace()]
    if not chars:
        return 0.0
    return sum(1 for c in chars if is_chinese(c)) / len(chars)


def has_pinyin(s):
    return any(c in TONE_MARKS for c in s)


def extract_cjk(s):
    return "".join(c for c in s if is_chinese(c))


def looks_like_pinyin(s):
    """True if s looks like a pinyin token (latin + possible tone marks + *)."""
    s = s.strip("* \t")
    return bool(s) and bool(re.match(r"^[a-züāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜA-Z]+$", s))


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class CharEntry:
    num: int
    char: str
    pinyin: str
    meaning: str


@dataclass
class VocabEntry:
    num: int
    combo: str
    pinyin: str
    meaning: str


@dataclass
class Dialog:
    index: int
    lines: List[str] = field(default_factory=list)


@dataclass
class Lesson:
    num: int
    characters: List[CharEntry] = field(default_factory=list)
    vocab: List[VocabEntry] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    illustrative: List[str] = field(default_factory=list)
    dialogues: List[Dialog] = field(default_factory=list)
    narrative: List[str] = field(default_factory=list)


# ── Multi-line entry group parser ──────────────────────────────────────────────

ENTRY_START = re.compile(r"^(\d+)[.\s]")  # line starting with N. or N (space)


def group_narrative(lines: List[str]) -> List[List[str]]:
    """Group narrative lines into paragraphs split by numbered prefixes."""
    groups: List[List[str]] = []
    current: List[str] = []
    for line in lines:
        if ENTRY_START.match(line) and current:
            groups.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        groups.append(current)
    return groups


def group_entries(lines: List[str]) -> List[List[str]]:
    """
    Split a list of section lines into per-entry groups.
    A new group starts whenever a line begins with a digit+dot/space.
    """
    groups: List[List[str]] = []
    current: List[str] = []
    for line in lines:
        if ENTRY_START.match(line):
            if current:
                groups.append(current)
            current = [line]
        else:
            if current:
                current.append(line)
            # Lines before any entry start are noise — skip
    if current:
        groups.append(current)
    return groups


def parse_char_group(group: List[str]) -> Optional[CharEntry]:
    """Parse a multi-line group into a CharEntry."""
    if not group:
        return None

    # Extract entry number from first line
    m = ENTRY_START.match(group[0])
    if not m:
        return None
    num = int(m.group(1))
    # Clamp numbers mangled by OCR (e.g. '4.1' → 4)
    if num > 50:
        return None

    # Collect all text tokens across the group
    all_text = " ".join(group)

    # Find CJK character (take the first one, ignoring image-noise singles)
    cjk_chars = extract_cjk(all_text)
    if not cjk_chars:
        return None
    char = cjk_chars[0]  # first CJK char is the main character

    # Find pinyin: first token with no CJK/digits that looks like pinyin
    pinyin = ""
    for token in all_text.split():
        tok = token.strip(".,*")
        if any(c.isdigit() or is_chinese(c) for c in tok):
            continue
        if has_pinyin(tok) or (looks_like_pinyin(tok) and 2 <= len(tok) <= 8):
            pinyin = tok
            break

    def _strip_etymology(s):
        s = re.sub(r"\s*\([A-Z].+", "", s).strip()
        return s

    def _candidate(line):
        stripped = line.strip()
        if not stripped or ENTRY_START.match(stripped):
            return None
        if any(is_chinese(c) for c in stripped):
            return None
        if stripped.startswith("*") or stripped.lower().startswith("asterisk"):
            return None
        if has_pinyin(stripped) and len(stripped) <= 15:
            return None
        return stripped

    # Pass 1: prefer lines with commas or parentheses (unambiguous definitions)
    meaning = ""
    for line in group[1:]:
        cand = _candidate(line)
        if cand and ("," in cand or "(" in cand):
            meaning = _strip_etymology(cand)
            break

    # Pass 2: fall back to first valid non-CJK, non-tone line
    if not meaning:
        for line in group[1:]:
            cand = _candidate(line)
            if cand:
                meaning = _strip_etymology(cand)
                break

    return CharEntry(num=num, char=char, pinyin=pinyin, meaning=meaning)


def parse_vocab_group(group: List[str]) -> Optional[VocabEntry]:
    """Parse a multi-line group into a VocabEntry (special combination)."""
    if not group:
        return None

    m = ENTRY_START.match(group[0])
    if not m:
        return None
    num = int(m.group(1))
    if num > 50:
        return None

    all_text = " ".join(group)

    # Combo: longest CJK sequence found across all lines
    combo = ""
    for line in group:
        cjk = extract_cjk(line)
        if len(cjk) > len(combo):
            combo = cjk

    if not combo:
        return None

    # Pinyin: first pinyin-looking token with no CJK/digits
    pinyin = ""
    for token in all_text.split():
        tok = token.strip(".,*?Y")  # 'Y' and '?' are OCR artifacts
        if any(c.isdigit() or is_chinese(c) for c in tok):
            continue
        if has_pinyin(tok) or (looks_like_pinyin(tok) and 2 <= len(tok) <= 12):
            pinyin = tok
            break

    # Meaning: first English-dominant line from group[1:] (skip entry-start line)
    meaning = ""
    for line in group[1:]:
        stripped = line.strip()
        if not stripped or stripped in ("Y", "?"):
            continue
        if chinese_ratio(stripped) > 0.5:
            continue
        if (has_pinyin(stripped) or looks_like_pinyin(stripped)) and len(stripped) <= 12:
            continue
        if stripped and not stripped.isdigit():
            meaning = stripped
            break

    return VocabEntry(num=num, combo=combo, pinyin=pinyin, meaning=meaning)


# ── Section-level line collector ───────────────────────────────────────────────

# Section tag constants
SECT_CHARS = "chars"
SECT_VOCAB = "vocab"
SECT_NOTE = "note"
SECT_ILLUS = "illus"
SECT_DIALOG = "dialog"
SECT_NARRATIVE = "narrative"
SECT_SKIP = "skip"
SECT_NONE = "none"

SEC_VOCAB_H = re.compile(
    r"^[^\w]*(?:Special\s+Combinations?|Vocabulary)\s*$", re.IGNORECASE
)
SEC_NOTE_H = re.compile(r"^Note\s+on\b", re.IGNORECASE)
SEC_ILLUS_CN_H = re.compile(
    r"^Exercise\s+\d+[.\s]*Illustrative\s+Sentences\s*\(Chinese\)", re.IGNORECASE
)
SEC_ILLUS_EN_H = re.compile(
    r"^Exercise\s+\d+[.\s]*Illustrative\s+Sentences\s*\(English\)", re.IGNORECASE
)
SEC_DIALOG_H = re.compile(r"^Exercise\s+\d+[.\s]*Dialogues?", re.IGNORECASE)
SEC_NARRATIVE_H = re.compile(
    r"^(?:Narrative\s*\d*|Exercise\s+\d+[.\s]*(?:Narrative|Reading))", re.IGNORECASE
)
SEC_SKIP_H = re.compile(
    r"^(?:Exercise\s+\d+[.\s]*(?:Review|Distinguishing|Substitution|Translation"
    r"|Who'?s|What'?s|Sentences\s*\(English\)|Practice|Numbers?|Excerpts?|Dictation)|"
    r"Who'?s\s+Who|What'?s\s+What|Translation|"
    r"Supplementary|Summary|Index|Contents|Acknowledgment|Preface|"
    r"Suggestions|Listed\s+below|Practice\s+pronouncing)",
    re.IGNORECASE,
)
LESSON_HEADER = re.compile(r"^Lesson\s+(\d+)\s*$", re.IGNORECASE)

# Lines that are pure layout noise
NOISE_LINE = re.compile(
    r"^(?:Beginning Chinese Reader|UNIT\s+[IVX]+|"
    r"\d+\s*$|[·•\-—]+\s*$|"
    r"[VXO□\.」」」」\s]{1,10}$)",
    re.IGNORECASE,
)


def is_noise(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if NOISE_LINE.match(stripped):
        return True
    # OCR artifacts: uppercase-only letter sequences (X, Y, OT, etc.)
    if len(stripped) <= 3 and stripped.isupper() and stripped.isalpha():
        return True
    # Single stray non-digit, non-CJK chars (OCR layout artifacts)
    if len(stripped) == 1 and not is_chinese(stripped[0]) and not stripped[0].isdigit():
        return True
    return False


# ── Main parser ────────────────────────────────────────────────────────────────

def parse_pages(pages: List[Path]) -> Optional[Lesson]:
    lesson_num = None
    lesson = None

    # Accumulate raw lines for the whole lesson
    all_lines: List[str] = []

    done = False
    for page_path in pages:
        if done:
            break
        # Prefer layout-reconstructed file when available
        layout_path = page_path.with_name(page_path.stem + ".layout.txt")
        src = layout_path if layout_path.exists() else page_path
        text = src.read_text(encoding="utf-8")
        for raw in text.splitlines():
            # Strip column-separator inserted by reconstruct_layout.py
            raw = raw.replace(" | ", " ")
            line = raw.strip()
            if not line:
                all_lines.append("")
                continue
            m = LESSON_HEADER.match(line)
            if m:
                n = int(m.group(1))
                if lesson is None:
                    lesson_num = n
                    lesson = Lesson(num=n)
                    all_lines.append(f"__LESSON_{n}__")
                elif n != lesson_num:
                    done = True
                    break
            else:
                all_lines.append(line)

    if lesson is None:
        return None

    # ── Pass 2: walk lines, track section, collect section buffers ─────────────

    section = SECT_NONE
    char_buf: List[str] = []
    vocab_buf: List[str] = []
    note_buf: List[str] = []
    illus_buf: List[str] = []
    illus_seen_numbered = False  # True once we've seen the first N. entry
    dialog_lines: List[str] = []
    narrative_buf: List[str] = []
    narrative_seen_numbered = False  # True once we've seen the first N. entry

    def flush_chars():
        for grp in group_entries(char_buf):
            e = parse_char_group(grp)
            if e and e.char:
                # Avoid duplicates
                if not any(c.num == e.num for c in lesson.characters):
                    lesson.characters.append(e)
        char_buf.clear()

    def flush_vocab():
        for grp in group_entries(vocab_buf):
            e = parse_vocab_group(grp)
            if e and e.combo:
                if not any(v.num == e.num for v in lesson.vocab):
                    lesson.vocab.append(e)
        vocab_buf.clear()

    for line in all_lines:
        if line.startswith("__LESSON_"):
            continue

        if is_noise(line):
            continue

        # ── Section transitions ──────────────────────────────────────────────

        if SEC_SKIP_H.match(line):
            if section == SECT_CHARS:
                flush_chars()
            elif section == SECT_VOCAB:
                flush_vocab()
            section = SECT_SKIP
            continue

        if SEC_VOCAB_H.match(line):
            if section == SECT_CHARS:
                flush_chars()
            elif section == SECT_VOCAB:
                flush_vocab()
            section = SECT_VOCAB
            continue

        if SEC_NOTE_H.match(line):
            if section == SECT_CHARS:
                flush_chars()
            elif section == SECT_VOCAB:
                flush_vocab()
            section = SECT_NOTE
            note_buf.append(line)
            continue

        if SEC_ILLUS_CN_H.match(line):
            if section == SECT_CHARS:
                flush_chars()
            elif section == SECT_VOCAB:
                flush_vocab()
            section = SECT_ILLUS
            continue

        if SEC_ILLUS_EN_H.match(line):
            section = SECT_SKIP
            continue

        if SEC_DIALOG_H.match(line):
            section = SECT_DIALOG
            continue

        if SEC_NARRATIVE_H.match(line):
            section = SECT_NARRATIVE
            continue

        if section == SECT_SKIP:
            continue

        # ── Content accumulation ─────────────────────────────────────────────

        if section in (SECT_NONE, SECT_CHARS):
            # The character section has no explicit header in early lessons —
            # it starts right after the lesson header with numbered entries
            if ENTRY_START.match(line):
                section = SECT_CHARS
            char_buf.append(line)

        elif section == SECT_VOCAB:
            vocab_buf.append(line)

        elif section == SECT_NOTE:
            # Collect English prose note lines
            if chinese_ratio(line) < 0.3:
                note_buf.append(line)

        elif section == SECT_ILLUS:
            # Numbered Chinese sentences
            m = re.match(r"^(\d+)[.\s]+(.+)$", line)
            if m and chinese_ratio(m.group(2)) >= 0.4:
                illus_buf.append(m.group(2).strip())
                illus_seen_numbered = True
            elif chinese_ratio(line) >= 0.5:
                if illus_seen_numbered and illus_buf:
                    # After the first numbered entry, all continuation lines
                    # belong to the current entry — mirroring the y-level rule
                    # that content between N. and (N+1). is part of sentence N.
                    illus_buf[-1] += line
                elif illus_buf and illus_buf[-1][-1] not in ".。？！）":
                    # Before first numbered entry: use terminal punct to separate
                    illus_buf[-1] += line
                elif len(line) >= 4:
                    illus_buf.append(line)

        elif section == SECT_DIALOG:
            dialog_lines.append(line)

        elif section == SECT_NARRATIVE:
            m = re.match(r"^(\d+)[.\s]+(.+)$", line)
            if m and chinese_ratio(line) >= 0.4:
                narrative_buf.append(line)
                narrative_seen_numbered = True
            elif chinese_ratio(line) >= 0.5:
                if narrative_seen_numbered and narrative_buf:
                    # Everything between N. and (N+1). belongs to entry N
                    narrative_buf.append(line)
                elif len(line) >= 4:
                    narrative_buf.append(line)

    # Flush any remaining buffers
    if char_buf:
        flush_chars()
    if vocab_buf:
        flush_vocab()

    # ── Parse dialog lines ─────────────────────────────────────────────────────
    # Numbered dialog start: '1. 田：...' or '1.田：...' or '1.' alone
    DIALOG_ENTRY_RE = re.compile(r"^(\d+)[.\s]+([一-鿿]{1,4}[：:].*)")
    DIALOG_NUM_RE = re.compile(r"^(\d+)\.\s*$")
    SPEAKER_RE = re.compile(r"^[一-鿿]{1,4}[：:]")
    EMPTY_DLG_SPEAKER = re.compile(r"^(\d+[.\s]+[一-鿿]{1,4}[：:])\s*$")
    ORPHAN_COLON = re.compile(r"^[：:]\s*")

    # Pre-pass: fix OCR column-reordering where orphan ：content appears
    # immediately before a numbered empty speaker label (e.g. '：我是毛小山' then '2.毛：').
    # Merge them into a proper '2.毛：我是毛小山' entry.
    fixed_dialog_lines = []
    i = 0
    while i < len(dialog_lines):
        line = dialog_lines[i]
        if ORPHAN_COLON.match(line) and i + 1 < len(dialog_lines):
            nxt = dialog_lines[i + 1]
            if EMPTY_DLG_SPEAKER.match(nxt):
                content = ORPHAN_COLON.sub("", line).strip()
                fixed_dialog_lines.append(nxt.rstrip() + content)
                i += 2
                continue
        fixed_dialog_lines.append(line)
        i += 1
    dialog_lines = fixed_dialog_lines

    current_dialog: Optional[Dialog] = None
    dialog_count = 0

    for line in dialog_lines:
        # Numbered line that starts a new dialog AND has a speaker
        de = DIALOG_ENTRY_RE.match(line)
        if de:
            dialog_count += 1
            current_dialog = Dialog(index=dialog_count)
            lesson.dialogues.append(current_dialog)
            current_dialog.lines.append(de.group(2).strip())
            continue

        # Bare number line — new dialog, waiting for content
        dm = DIALOG_NUM_RE.match(line)
        if dm:
            dialog_count += 1
            current_dialog = Dialog(index=dialog_count)
            lesson.dialogues.append(current_dialog)
            continue

        # Speaker line within current dialog
        if SPEAKER_RE.match(line):
            if current_dialog is None:
                dialog_count += 1
                current_dialog = Dialog(index=dialog_count)
                lesson.dialogues.append(current_dialog)
            current_dialog.lines.append(line)
        elif current_dialog is not None and (
            chinese_ratio(line) >= 0.5 or line.startswith("：")
        ):
            # Continuation: merge onto the last speaker's line
            if current_dialog.lines:
                current_dialog.lines[-1] += line
            else:
                current_dialog.lines.append(line)

    lesson.notes = note_buf
    lesson.illustrative = illus_buf
    lesson.narrative = narrative_buf

    return lesson


# ── Markdown renderer ──────────────────────────────────────────────────────────

def render_markdown(lesson: Lesson) -> str:
    parts: List[str] = [f"# Lesson {lesson.num}\n"]

    if lesson.characters:
        parts.append("## New Characters\n")
        parts.append("| # | Character | Pinyin | Meaning |")
        parts.append("|---|-----------|--------|---------|")
        for c in sorted(lesson.characters, key=lambda x: x.num):
            parts.append(f"| {c.num} | {c.char} | {c.pinyin} | {c.meaning} |")
        parts.append("")

    if lesson.vocab:
        parts.append("## Special Combinations / Vocabulary\n")
        parts.append("| # | Combination | Pinyin | Meaning |")
        parts.append("|---|-------------|--------|---------|")
        for v in sorted(lesson.vocab, key=lambda x: x.num):
            parts.append(f"| {v.num} | {v.combo} | {v.pinyin} | {v.meaning} |")
        parts.append("")

    if lesson.notes:
        parts.append("## Notes\n")
        for note in lesson.notes:
            parts.append(note)
        parts.append("")

    if lesson.illustrative:
        parts.append("## Illustrative Sentences\n")
        for i, s in enumerate(lesson.illustrative, 1):
            parts.append(f"{i}. {s}")
        parts.append("")

    if lesson.dialogues:
        parts.append("## Dialogues\n")
        EMPTY_SPEAKER = re.compile(r"^[一-鿿]{1,4}[：:]\s*$")
        for dlg in lesson.dialogues:
            rendered = []
            for line in dlg.lines:
                line = re.sub(r"[：:][：:]", "：", line)
                if not EMPTY_SPEAKER.match(line):
                    rendered.append(f"> {line}")
            if rendered:
                parts.append(f"**Dialog {dlg.index}**\n")
                parts.extend(rendered)
                parts.append("")

    if lesson.narrative:
        parts.append("## Narrative\n")
        for grp in group_narrative(lesson.narrative):
            # Strip leading number prefix from first line, join continuation lines
            first = re.sub(r"^\d+[.\s]+", "", grp[0]).strip()
            rest = "".join(line.strip() for line in grp[1:])
            paragraph = (first + rest).strip()
            if paragraph:
                parts.append(paragraph)
                parts.append("")

    return "\n".join(parts)


# ── Page → lesson mapping ──────────────────────────────────────────────────────

def has_cjk(text: str) -> bool:
    return any("一" <= c <= "鿿" or "㐀" <= c <= "䶿" for c in text)


def discover_lesson_pages(output_dir: Path) -> Dict[int, List[Path]]:
    all_pages = sorted(
        p for p in output_dir.glob("page-*.txt")
        if not p.name.endswith(".layout.txt")
    )
    mapping: Dict[int, List[Path]] = {}
    current_lesson = None

    for page_path in all_pages:
        text = page_path.read_text(encoding="utf-8")
        # Skip front-matter pages that have no Chinese content (TOC, prefaces)
        if not has_cjk(text):
            continue
        for line in text.splitlines():
            m = LESSON_HEADER.match(line.strip())
            if m:
                n = int(m.group(1))
                if n != current_lesson:
                    current_lesson = n
                break
        if current_lesson is not None:
            mapping.setdefault(current_lesson, []).append(page_path)

    return mapping


# ── CLI ────────────────────────────────────────────────────────────────────────

def parse_range(s: str):
    result = set()
    for part in s.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            result.update(range(int(lo), int(hi) + 1))
        else:
            result.add(int(part))
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("output_dir")
    ap.add_argument("lessons_dir")
    ap.add_argument("--lessons", default=None)
    args = ap.parse_args()

    output_root = Path(args.output_dir)
    lessons_dir = Path(args.lessons_dir)
    lessons_dir.mkdir(parents=True, exist_ok=True)

    wanted = parse_range(args.lessons) if args.lessons else None

    book_dirs = sorted(d for d in output_root.iterdir() if d.is_dir())
    if not book_dirs:
        print(f"No book dirs in {output_root}", file=sys.stderr)
        sys.exit(1)

    for book_dir in book_dirs:
        print(f"\n[parse] {book_dir.name}")
        page_map = discover_lesson_pages(book_dir)

        for lesson_num in sorted(page_map.keys()):
            if wanted and lesson_num not in wanted:
                continue

            pages = page_map[lesson_num]
            print(f"  Lesson {lesson_num:3d}  ({len(pages)} pages)", end="", flush=True)

            lesson = parse_pages(pages)
            if lesson is None:
                print("  [skip]")
                continue

            md = render_markdown(lesson)
            out_path = lessons_dir / f"Lesson {lesson_num:03d}.md"
            out_path.write_text(md, encoding="utf-8")
            print(
                f"  → {len(lesson.characters)} chars, "
                f"{len(lesson.vocab)} vocab, "
                f"{len(lesson.illustrative)} sentences, "
                f"{len(lesson.dialogues)} dialogs"
            )

    print("\nDone.")


if __name__ == "__main__":
    main()
