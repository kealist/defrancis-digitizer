"""
Convert DeFrancis Reader lesson content to audio using edge-tts.
Keeps: Illustrative Sentences (Chinese) + Dialogues.
Skips: vocabulary lists, Special Combinations, English exercises, grammar notes.

Usage: python tts.py /output /audio
Generates /audio/<book>/lesson-NNN.mp3 for each lesson found.
"""
import asyncio
import re
import sys
from pathlib import Path

import edge_tts

VOICE = "zh-TW-HsiaoChenNeural"

TONE_MARKS = set("āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ")

SKIP_SECTION_HEADERS = {
    "special combinations",
    "vocabulary",
    "exercise 3",
    "exercise 4",
    "exercise 5",
    "who's who",
    "what's what",
    "illustrative sentences (english)",
    "translation",
}

RESUME_SECTION_HEADERS = {
    "exercise 1",
    "exercise 2",
    "dialogues",
    "illustrative sentences (chinese)",
    "narrative",
}

NOTE_PREFIXES = ("note on", "notes on", "note:", "(1)", "(2)", "(3)")


def chinese_ratio(s):
    chars = [c for c in s if not c.isspace()]
    if not chars:
        return 0.0
    chinese = sum(
        1 for c in chars
        if "一" <= c <= "鿿" or "㐀" <= c <= "䶿"
    )
    return chinese / len(chars)


def has_pinyin(s):
    return any(c in TONE_MARKS for c in s)


def is_skip_line(line):
    if has_pinyin(line):
        return True
    if chinese_ratio(line) < 0.35 and len(line.strip()) > 4:
        return True
    return False


def clean_for_tts(line):
    """Strip numbering prefixes and speaker labels, keep the Chinese sentence."""
    # Strip leading number: '1.', '1. ', '１．'
    line = re.sub(r"^\d+[.\s]+", "", line)
    # Strip speaker label: '田：', '馬：' (fullwidth or halfwidth colon)
    line = re.sub(r"^[一-鿿]{1,4}[：:]", "", line)
    # Strip orphaned leading colon when OCR missed the speaker name
    line = re.sub(r"^[：:]\s*", "", line)
    return line.strip()


def extract_lesson_content(text):
    """Return cleaned Chinese lines from lesson sentences and dialogues."""
    lines = text.splitlines()
    result = []
    in_skip = False

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        lower = line.lower()

        if any(lower.startswith(h) for h in SKIP_SECTION_HEADERS):
            in_skip = True
            continue

        if any(lower.startswith(h) for h in RESUME_SECTION_HEADERS):
            in_skip = False
            continue

        if in_skip:
            continue

        if any(line.lower().startswith(p) for p in NOTE_PREFIXES):
            continue

        if is_skip_line(line):
            continue

        if chinese_ratio(line) >= 0.5:
            cleaned = clean_for_tts(line)
            if len(cleaned) >= 4:
                result.append(cleaned)

    return result


def group_by_lesson(book_dir):
    """Return {lesson_num: [chinese_lines]} for all pages in book_dir."""
    pages = sorted(Path(book_dir).glob("page-*.txt"))
    lessons: dict[int, list[str]] = {}
    current_lesson = None
    lesson_re = re.compile(r"\bLesson\s+(\d+)\b", re.IGNORECASE)

    for page_path in pages:
        text = page_path.read_text(encoding="utf-8")
        match = lesson_re.search(text)
        if match:
            current_lesson = int(match.group(1))

        if current_lesson is None:
            continue

        lines = extract_lesson_content(text)
        if lines:
            lessons.setdefault(current_lesson, []).extend(lines)

    return lessons


async def synthesize(text, out_path):
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(str(out_path))


async def process_book(book_dir, audio_root):
    book_name = Path(book_dir).name
    audio_dir = Path(audio_root) / book_name
    audio_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n[tts] {book_name}", flush=True)
    lessons = group_by_lesson(book_dir)

    if not lessons:
        print("  No lesson content found.", flush=True)
        return

    print(f"  Found {len(lessons)} lessons.", flush=True)

    for lesson_num in sorted(lessons.keys()):
        lines = lessons[lesson_num]
        if not lines:
            continue

        out_file = audio_dir / f"lesson-{lesson_num:03d}.mp3"
        if out_file.exists():
            print(f"  [skip] lesson {lesson_num:3d}", flush=True)
            continue

        text = "\n".join(lines)
        print(
            f"  [tts]  lesson {lesson_num:3d}  ({len(lines)} lines → {out_file.name})",
            flush=True,
        )
        await synthesize(text, out_file)

    print(f"[done] {book_name}", flush=True)


async def main(output_root, audio_root):
    book_dirs = sorted(
        d for d in Path(output_root).iterdir() if d.is_dir()
    )
    if not book_dirs:
        print("No book directories found in", output_root, flush=True)
        return

    for book_dir in book_dirs:
        await process_book(book_dir, audio_root)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: tts.py <output_root> <audio_root>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
