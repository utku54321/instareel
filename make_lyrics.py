#!/usr/bin/env python3
"""
make_lyrics.py - build lyrics.json for a lyric video.

Order of attempts:
  1. LRCLIB (free synced lyrics, no API key)
  2. If not found -> Demucs (isolate vocals) + Whisper (Hindi, word timestamps)
Then, if the text is in Devanagari and GEMINI_API_KEY is set, convert it to Hinglish.

Usage:
  python make_lyrics.py song.mp3 --artist "Artist Name" --title "Song Title" --clip-start 62.5
  python make_lyrics.py song.mp3 --whisper-only          # skip LRCLIB

--clip-start = where your clip begins inside the full song (seconds). LRCLIB timings are
for the full song, so this shifts them to match your clip. Not needed for Whisper.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

# Use the portable ffmpeg from static-ffmpeg if ffmpeg isn't installed system-wide.
if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
    try:
        import static_ffmpeg
        static_ffmpeg.add_paths()
    except Exception:
        pass

LRCLIB = "https://lrclib.net/api"
HEADERS = {"User-Agent": "lyric-video-maker/1.0 (personal project)"}
DEVANAGARI = re.compile(r"[\u0900-\u097F]")


# ----------------------------------------------------------------- helpers
def audio_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def spread_words(text, start, end):
    """Give each word an even share of the line's time (used when we only have line timings)."""
    words = text.split()
    if not words:
        return []
    span = max(end - start, 0.3) * 0.9  # finish highlighting a bit before the next line
    step = span / len(words)
    return [{"w": w, "start": round(start + i * step, 2), "end": round(start + (i + 1) * step, 2)}
            for i, w in enumerate(words)]


def log(msg):
    print(f"[make_lyrics] {msg}", flush=True)


# ----------------------------------------------------------------- 1. LRCLIB
LRC_LINE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)")


def parse_lrc(lrc):
    lines = []
    for raw in lrc.splitlines():
        m = LRC_LINE.match(raw.strip())
        if not m:
            continue
        t = int(m.group(1)) * 60 + float(m.group(2))
        text = m.group(3).strip()
        lines.append((t, text))
    return sorted(lines)


def lrclib_search(artist, title, song_duration=None):
    params = {"track_name": title}
    if artist:
        params["artist_name"] = artist
    try:
        r = requests.get(f"{LRCLIB}/search", params=params, headers=HEADERS, timeout=15)
        r.raise_for_status()
        results = r.json()
    except Exception as e:
        log(f"LRCLIB request failed: {e}")
        return None

    synced = [x for x in results if x.get("syncedLyrics") and not x.get("instrumental")]
    if not synced:
        log("LRCLIB: no synced lyrics found.")
        return None
    if song_duration:
        synced.sort(key=lambda x: abs((x.get("duration") or 0) - song_duration))
    best = synced[0]
    log(f"LRCLIB: found '{best.get('trackName')}' by {best.get('artistName')} "
        f"({best.get('duration')} s).")
    return best["syncedLyrics"]


def lrc_to_clip(lrc, clip_start, clip_len):
    """Keep only lines inside the clip window and shift them so the clip starts at 0."""
    parsed = parse_lrc(lrc)
    clip_end = clip_start + clip_len
    out = []
    for i, (t, text) in enumerate(parsed):
        nxt = parsed[i + 1][0] if i + 1 < len(parsed) else t + 5
        nxt = min(nxt, t + 8)  # a line followed by a long music break shouldn't stretch forever
        if not text or nxt <= clip_start or t >= clip_end:
            continue
        s = max(t, clip_start) - clip_start
        e = min(nxt, clip_end) - clip_start
        out.append({"start": round(s, 2), "end": round(e, 2), "text": text,
                    "words": spread_words(text, s, e)})
    return out


# ----------------------------------------------------------------- 2. Demucs + Whisper
def isolate_vocals(audio, workdir):
    if shutil.which("demucs") is None and not _has_module("demucs"):
        log("Demucs not installed, transcribing the full mix instead.")
        return audio
    log("Demucs: separating vocals (first run downloads the model)...")
    try:
        subprocess.run([sys.executable, "-m", "demucs", "--two-stems=vocals", "-n", "htdemucs",
                        "-o", str(workdir), str(audio)], check=True)
    except Exception as e:  # noqa: BLE001
        log(f"Demucs failed ({e}); transcribing the full mix instead.")
        return audio
    vocals = next(Path(workdir).rglob("vocals.wav"), None)
    if vocals is None:
        log("Demucs gave no vocals file, using the full mix.")
        return audio
    return vocals


def _has_module(name):
    import importlib.util
    return importlib.util.find_spec(name) is not None


def whisper_transcribe(audio, model_name, language):
    import whisper  # openai-whisper
    log(f"Whisper: loading '{model_name}' (first run downloads it)...")
    model = whisper.load_model(model_name)
    log("Whisper: transcribing...")
    res = model.transcribe(str(audio), language=language, word_timestamps=True,
                           condition_on_previous_text=False, fp16=False)
    lines = []
    for seg in res["segments"]:
        text = seg["text"].strip()
        if not text:
            continue
        words = [{"w": w["word"].strip(), "start": round(w["start"], 2), "end": round(w["end"], 2)}
                 for w in seg.get("words", []) if w["word"].strip()]
        lines.append({"start": round(seg["start"], 2), "end": round(seg["end"], 2),
                      "text": text, "words": words or spread_words(text, seg["start"], seg["end"])})
    return lines


# ----------------------------------------------------------------- 3. Hinglish via Gemini
def to_hinglish(lines, model_name):
    if not any(DEVANAGARI.search(l["text"]) for l in lines):
        return lines, False
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        log("Text is in Devanagari. Set GEMINI_API_KEY to auto-convert to Hinglish; keeping Devanagari.")
        return lines, False
    try:
        from google import genai
    except ImportError:
        log("google-genai not installed; keeping Devanagari.")
        return lines, False

    prompt = (
        "Convert each Hindi line to natural Hinglish: Roman script the way Indians type Hindi "
        "on WhatsApp (e.g. 'dil', 'pyaar', 'tumhe', 'kya hua'), not academic transliteration. "
        "Keep the same number of lines and, where possible, the same number of words per line. "
        "Return only a JSON array of strings.\n\n"
        + json.dumps([l["text"] for l in lines], ensure_ascii=False)
    )
    try:
        client = genai.Client(api_key=key)
        resp = client.models.generate_content(
            model=model_name, contents=prompt,
            config={"response_mime_type": "application/json"})
        converted = json.loads(resp.text)
    except Exception as e:
        log(f"Gemini conversion failed ({e}); keeping Devanagari.")
        return lines, False
    if not isinstance(converted, list) or len(converted) != len(lines):
        log("Gemini returned a different number of lines; keeping Devanagari.")
        return lines, False

    for line, new in zip(lines, converted):
        new = str(new).strip()
        new_words = new.split()
        old = line["words"]
        if len(new_words) == len(old):  # keep exact per-word timings
            for w, nw in zip(old, new_words):
                w["w"] = nw
        else:                           # word count changed: spread evenly
            line["words"] = spread_words(new, line["start"], line["end"])
        line["text"] = new
    log("Converted lyrics to Hinglish.")
    return lines, True


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Make lyrics.json: LRCLIB first, Whisper fallback.")
    ap.add_argument("audio")
    ap.add_argument("--artist", default="")
    ap.add_argument("--title", default="")
    ap.add_argument("--clip-start", type=float, default=0.0,
                    help="where the clip starts inside the full song, in seconds")
    ap.add_argument("--song-duration", type=float, default=None,
                    help="full song length in seconds (helps pick the right LRCLIB match)")
    ap.add_argument("--whisper-only", action="store_true")
    ap.add_argument("--model", default="large-v3-turbo",
                    help="whisper model: large-v3-turbo (default), large-v3, medium, small")
    ap.add_argument("--language", default="hi")
    ap.add_argument("--no-demucs", action="store_true")
    ap.add_argument("--gemini-model", default="gemini-2.5-flash")
    ap.add_argument("--out", default="lyrics.json")
    a = ap.parse_args()

    audio = Path(a.audio)
    if not audio.exists():
        sys.exit(f"Audio file not found: {audio}")
    clip_len = audio_duration(audio)
    log(f"Clip length: {clip_len:.1f} s")

    lines, source = [], None

    # 1. LRCLIB
    if not a.whisper_only and a.title:
        lrc = lrclib_search(a.artist, a.title, a.song_duration)
        if lrc:
            lines = lrc_to_clip(lrc, a.clip_start, clip_len)
            if lines:
                source = "lrclib"
            else:
                log("LRCLIB lyrics had no lines inside this clip window. "
                    "Check --clip-start. Falling back to Whisper.")
    elif not a.whisper_only:
        log("No --title given, skipping LRCLIB.")

    # 2. Whisper fallback
    if not lines:
        with tempfile.TemporaryDirectory() as tmp:
            src = audio if a.no_demucs else isolate_vocals(audio, tmp)
            lines = whisper_transcribe(src, a.model, a.language)
        source = f"whisper:{a.model}"

    if not lines:
        sys.exit("No lyrics found or transcribed.")

    # 3. Hinglish
    lines, converted = to_hinglish(lines, a.gemini_model)

    data = {"source": source, "hinglish": converted or not any(DEVANAGARI.search(l["text"]) for l in lines),
            "clip_length": round(clip_len, 2), "lines": lines}
    Path(a.out).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Saved {len(lines)} lines to {a.out} (source: {source}).")
    for l in lines:
        print(f"  {l['start']:6.2f}  {l['text']}")
    print("\nReview the lines above and fix any mistakes in lyrics.json before building the video.")


if __name__ == "__main__":
    main()
