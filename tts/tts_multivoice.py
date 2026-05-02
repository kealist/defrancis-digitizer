"""
Convert DeFrancis Reader lesson content to audio with section separation and multi-voice dialogs.

Usage: python tts_multivoice.py <lessons_dir> <audio_root>

Generates:
  - lesson-NNN-illustrative.mp3 (all illustrative sentences in one file)
  - lesson-NNN-narrative.mp3 (all narrative paragraphs in one file)
  - lesson-NNN-dialog-D.mp3 (each dialog with multi-voice speakers)

Voice mapping is saved to <audio_root>/voice_mapping.json for reproducibility.
"""
import asyncio
import json
import re
import sys
import tempfile
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, Dict, List, Tuple

import edge_tts
from pydub import AudioSegment

# Available voices pool: mix of male/female, different regions
VOICE_POOL = [
    "zh-TW-HsiaoChenNeural",     # F Taiwan
    "zh-TW-YunJheNeural",         # M Taiwan
    "zh-TW-HsiaoYuNeural",        # F Taiwan
    "zh-CN-YunjianNeural",        # M Mainland
    "zh-CN-XiaoxiaoNeural",       # F Mainland
    "zh-CN-YunyangNeural",        # M Mainland
    "zh-HK-HiuGaaiNeural",        # F HK
    "zh-HK-WanLungNeural",        # M HK
]

TONE_MARKS = set("āáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜ")


def has_pinyin(s):
    return any(c in TONE_MARKS for c in s)


@dataclass
class SectionContent:
    illustrative: List[str]
    narrative: List[str]
    dialogs: List[Dict[int, List[str]]]  # [{"dialog_num": [lines]}]


def parse_lesson_markdown(markdown_text: str) -> SectionContent:
    """Parse markdown lesson file into sections."""
    lines = markdown_text.splitlines()
    result = SectionContent(illustrative=[], narrative=[], dialogs=[])

    current_section = None
    current_dialog_num = None
    current_dialog_lines: List[str] = []

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Section headers
        if line.lower().startswith("## illustrative"):
            current_section = "illustrative"
            i += 1
            continue

        if line.lower().startswith("## dialogue"):
            current_section = "dialogs"
            i += 1
            continue

        if line.lower().startswith("## narrative"):
            current_section = "narrative"
            i += 1
            continue

        # Skip other sections
        if line.startswith("##"):
            current_section = None
            i += 1
            continue

        # Process content based on current section
        if current_section == "illustrative":
            if line and not line.startswith(">") and not line.startswith("**"):
                # Skip pinyin lines, keep numbers to be spoken
                if not has_pinyin(line) and line:
                    if len(line) >= 4:
                        result.illustrative.append(line)

        elif current_section == "dialogs":
            # Dialog format: **Dialog N** header, then lines starting with >
            if line.startswith("**Dialog"):
                match = re.search(r"Dialog\s+(\d+)", line)
                if match:
                    if current_dialog_lines:
                        result.dialogs.append({current_dialog_num: current_dialog_lines})
                    current_dialog_num = int(match.group(1))
                    current_dialog_lines = []
            elif line.startswith(">"):
                # Extract dialog content
                content = line[1:].strip()
                if content:
                    current_dialog_lines.append(content)

        elif current_section == "narrative":
            if line and not line.startswith("**"):
                # Skip pinyin lines, keep numbers to be spoken
                if not has_pinyin(line) and line:
                    if len(line) >= 4:
                        result.narrative.append(line)

        i += 1

    # Save last dialog if any
    if current_dialog_num is not None and current_dialog_lines:
        result.dialogs.append({current_dialog_num: current_dialog_lines})

    return result


def extract_speakers(dialog_lines: List[str]) -> Dict[int, str]:
    """Extract speaker names from dialog lines. Returns {line_index: speaker_name}."""
    speakers = {}
    speaker_pattern = re.compile(r"^([一-鿿]{1,4})[：:]\s*")

    for idx, line in enumerate(dialog_lines):
        match = speaker_pattern.match(line)
        if match:
            speaker = match.group(1)
            speakers[idx] = speaker

    return speakers


def extract_dialog_text(dialog_line: str) -> str:
    """Remove speaker label and return just the spoken text."""
    # Remove speaker label (e.g., "白：你好" -> "你好")
    cleaned = re.sub(r"^[一-鿿]{1,4}[：:]\s*", "", dialog_line)
    return cleaned.strip()


def load_voice_mapping(audio_root: Path) -> Dict[str, str]:
    """Load existing voice mapping from JSON."""
    mapping_file = audio_root / "voice_mapping.json"
    if mapping_file.exists():
        return json.loads(mapping_file.read_text(encoding="utf-8"))
    return {}


def save_voice_mapping(audio_root: Path, mapping: Dict[str, str]):
    """Save voice mapping to JSON."""
    mapping_file = audio_root / "voice_mapping.json"
    mapping_file.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")


def get_or_assign_voice(speaker: str, voice_mapping: Dict[str, str], next_voice_idx: List[int]) -> str:
    """Get voice for speaker, assigning if not yet mapped."""
    if speaker in voice_mapping:
        return voice_mapping[speaker]

    voice = VOICE_POOL[next_voice_idx[0] % len(VOICE_POOL)]
    voice_mapping[speaker] = voice
    next_voice_idx[0] += 1

    print(f"    Assigned voice {voice} to speaker '{speaker}'", flush=True)
    return voice


async def synthesize_text(text: str, voice: str, out_path: Path, delay: float = 1.0):
    """Generate MP3 for text using specified voice."""
    if not text or not text.strip():
        return

    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(out_path))

    # Rate limiting: delay between API calls
    await asyncio.sleep(delay)


def parse_dialog_segments(dialog_lines: List[str]) -> List[Tuple[str, str]]:
    """Parse dialog into (speaker, text) tuples preserving order."""
    segments = []
    for line in dialog_lines:
        speaker_match = re.match(r"^([一-鿿]{1,4})[：:]\s*", line)
        if speaker_match:
            speaker = speaker_match.group(1)
            text = extract_dialog_text(line)
            if text:
                segments.append((speaker, text))
    return segments


async def synthesize_dialog_with_voices(
    dialog_lines: List[str],
    dialog_num: int,
    lesson_num: int,
    out_dir: Path,
    voice_mapping: Dict[str, str],
) -> bool:
    """Synthesize a single dialog with different voices for each speaker."""
    if not dialog_lines:
        return False

    segments = parse_dialog_segments(dialog_lines)
    if not segments:
        return False

    next_voice_idx = [len(voice_mapping)]

    # Synthesize each segment with speaker's assigned voice
    audio_segments = []
    temp_files = []

    for speaker, text in segments:
        voice = get_or_assign_voice(speaker, voice_mapping, next_voice_idx)

        # Synthesize to temporary file
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = Path(tmp.name)
            temp_files.append(tmp_path)

        await synthesize_text(text, voice, tmp_path)

        # Load audio segment
        try:
            audio = AudioSegment.from_mp3(str(tmp_path))
            audio_segments.append(audio)
        except Exception as e:
            print(f"    Error loading audio segment: {e}", flush=True)
            return False

    # Merge all segments with small pause between speakers
    if not audio_segments:
        return False

    combined = audio_segments[0]
    silence = AudioSegment.silent(duration=300)  # 300ms pause

    for segment in audio_segments[1:]:
        combined += silence + segment

    # Save combined dialog
    out_file = out_dir / f"lesson-{lesson_num:03d}-dialog-{dialog_num}.mp3"
    print(
        f"    [tts] dialog {dialog_num:2d}  ({len(segments)} lines, {len(set(s[0] for s in segments))} speakers → {out_file.name})",
        flush=True,
    )

    combined.export(str(out_file), format="mp3")

    # Clean up temp files
    for tmp_file in temp_files:
        try:
            tmp_file.unlink()
        except:
            pass

    return True


async def synthesize_combined_dialogs(
    dialogs: List[Dict[int, List[str]]],
    lesson_num: int,
    out_dir: Path,
    voice_mapping: Dict[str, str],
) -> bool:
    """Synthesize all dialogs for a lesson and combine into one file."""
    if not dialogs:
        return False

    all_audio_segments = []
    temp_files = []
    next_voice_idx = [len(voice_mapping)]
    dialog_pause = AudioSegment.silent(duration=500)  # 500ms pause between dialogs

    for dialog_dict in dialogs:
        for dialog_num, dialog_lines in dialog_dict.items():
            segments = parse_dialog_segments(dialog_lines)
            if not segments:
                continue

            # Synthesize each segment with speaker's assigned voice
            dialog_audio_segments = []

            for speaker, text in segments:
                voice = get_or_assign_voice(speaker, voice_mapping, next_voice_idx)

                # Synthesize to temporary file
                with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                    tmp_path = Path(tmp.name)
                    temp_files.append(tmp_path)

                await synthesize_text(text, voice, tmp_path)

                # Load audio segment
                try:
                    audio = AudioSegment.from_mp3(str(tmp_path))
                    dialog_audio_segments.append(audio)
                except Exception as e:
                    print(f"    Error loading audio segment: {e}", flush=True)
                    continue

            # Merge segments within this dialog with pauses
            if dialog_audio_segments:
                combined_dialog = dialog_audio_segments[0]
                speaker_pause = AudioSegment.silent(duration=300)  # 300ms pause between speakers

                for segment in dialog_audio_segments[1:]:
                    combined_dialog += speaker_pause + segment

                all_audio_segments.append(combined_dialog)

    # Merge all dialogs with pauses
    if not all_audio_segments:
        return False

    combined_all = all_audio_segments[0]
    for dialog_audio in all_audio_segments[1:]:
        combined_all += dialog_pause + dialog_audio

    # Save combined dialogs
    out_file = out_dir / f"lesson-{lesson_num:03d}-dialogs.mp3"
    total_speakers = len(set(s for d in dialogs for sd in d.values() for s, _ in parse_dialog_segments(sd)))
    print(
        f"    [tts] all dialogs ({len(dialogs)} dialogs, {total_speakers} speakers → {out_file.name})",
        flush=True,
    )

    combined_all.export(str(out_file), format="mp3")

    # Clean up temp files
    for tmp_file in temp_files:
        try:
            tmp_file.unlink()
        except:
            pass

    return True


async def process_lesson(lesson_path: Path, audio_root: Path, voice_mapping: Dict[str, str]):
    """Process a single lesson file."""
    lesson_num_match = re.search(r"(\d+)", lesson_path.stem)
    if not lesson_num_match:
        return

    lesson_num = int(lesson_num_match.group(1))
    audio_dir = Path(audio_root)
    audio_dir.mkdir(parents=True, exist_ok=True)

    # Parse lesson
    markdown_text = lesson_path.read_text(encoding="utf-8")
    sections = parse_lesson_markdown(markdown_text)

    print(f"  Lesson {lesson_num:3d}: {len(sections.illustrative)} illustrative, "
          f"{len(sections.narrative)} narrative, {len(sections.dialogs)} dialogs", flush=True)

    # Generate illustrative MP3
    if sections.illustrative:
        illustrative_text = "。".join(sections.illustrative)
        out_file = audio_dir / f"lesson-{lesson_num:03d}-illustrative.mp3"
        voice = "zh-TW-HsiaoChenNeural"  # Use consistent voice for illustrative
        print(f"    [tts] illustrative → {out_file.name}", flush=True)
        await synthesize_text(illustrative_text, voice, out_file)

    # Generate narrative MP3
    if sections.narrative:
        narrative_text = "。".join(sections.narrative)
        out_file = audio_dir / f"lesson-{lesson_num:03d}-narrative.mp3"
        voice = "zh-TW-HsiaoChenNeural"  # Use consistent voice for narrative
        print(f"    [tts] narrative   → {out_file.name}", flush=True)
        await synthesize_text(narrative_text, voice, out_file)

    # Generate combined dialogs MP3
    if sections.dialogs:
        await synthesize_combined_dialogs(
            sections.dialogs,
            lesson_num,
            audio_dir,
            voice_mapping
        )


async def main(lessons_root: str, audio_root: str):
    """Process all lessons."""
    lessons_dir = Path(lessons_root)
    audio_dir = Path(audio_root)

    if not lessons_dir.exists():
        print(f"Lessons directory not found: {lessons_root}", flush=True)
        return

    audio_dir.mkdir(parents=True, exist_ok=True)

    # Load existing voice mapping
    voice_mapping = load_voice_mapping(audio_dir)
    print(f"[tts] Loaded {len(voice_mapping)} existing voice mappings", flush=True)

    # Find and process all lesson files
    lesson_files = sorted(lessons_dir.glob("Lesson *.md"))
    if not lesson_files:
        print(f"No lesson files found in {lessons_root}", flush=True)
        return

    print(f"[tts] Processing {len(lesson_files)} lessons", flush=True)

    for lesson_path in lesson_files:
        await process_lesson(lesson_path, audio_dir, voice_mapping)

    # Save final voice mapping
    save_voice_mapping(audio_dir, voice_mapping)
    print(f"[done] Saved voice mapping ({len(voice_mapping)} speakers)", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: tts_multivoice.py <lessons_dir> <audio_root>", file=sys.stderr)
        sys.exit(1)
    asyncio.run(main(sys.argv[1], sys.argv[2]))
