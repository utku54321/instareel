#!/usr/bin/env python3
"""
Lyric Studio - local server.

Serves the web page and does the heavy work the browser can't:
  * /api/lyrics  : runs make_lyrics.py (LRCLIB first, then Demucs + Whisper) on an uploaded song
  * /api/mp4     : converts the browser's recording to an Instagram-ready MP4 with ffmpeg

Start it with start.bat (Windows) or ./start.sh (Mac/Linux). It opens http://127.0.0.1:8765
"""
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory

HERE = Path(__file__).resolve().parent
JOBS = HERE / "jobs"
JOBS.mkdir(exist_ok=True)
PORT = int(os.environ.get("LYRIC_STUDIO_PORT", "8765"))
MODELS = {"large-v3-turbo", "large-v3", "medium", "small", "base", "tiny"}

app = Flask(__name__, static_folder=str(HERE / "static"), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 600 * 1024 * 1024  # 600 MB uploads

# ------------------------------------------------------------------ setup helpers
def load_gemini_key():
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return True
    f = HERE / "gemini_key.txt"
    if f.exists():
        key = f.read_text(encoding="utf-8").strip()
        if key:
            os.environ["GEMINI_API_KEY"] = key
            return True
    return False


def ensure_ffmpeg():
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return True
    try:
        import static_ffmpeg
        static_ffmpeg.add_paths()  # adds to os.environ["PATH"], inherited by subprocesses
    except Exception as e:
        print("Could not set up ffmpeg:", e)
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def clean_old_jobs(max_age_hours=24):
    now = time.time()
    for d in JOBS.iterdir():
        try:
            if d.is_dir() and now - d.stat().st_mtime > max_age_hours * 3600:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


GEMINI = load_gemini_key()
FFMPEG = ensure_ffmpeg()
clean_old_jobs()

jobs = {}
jobs_lock = threading.Lock()


def has_module(name):
    import importlib.util
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


# ------------------------------------------------------------------ pages
@app.get("/")
def index():
    return send_from_directory(HERE / "static", "index.html")


@app.get("/api/health")
def health():
    return jsonify(ok=True, ffmpeg=FFMPEG, gemini=GEMINI,
                   whisper=has_module("whisper"), demucs=has_module("demucs"))


# ------------------------------------------------------------------ lyrics jobs
STAGES = [
    ("LRCLIB: found", "Found synced lyrics on LRCLIB"),
    ("LRCLIB", "Searching LRCLIB for synced lyrics"),
    ("Demucs", "Separating the vocals from the music"),
    ("Whisper: loading", "Loading the Whisper model"),
    ("Whisper: transcribing", "Listening to the vocals and writing lyrics"),
    ("Hinglish", "Converting to Hinglish"),
    ("Saved", "Lyrics ready"),
]


def stage_from_log(lines):
    for line in reversed(lines):
        for key, label in STAGES:
            if key in line:
                return label
    return "Starting"


def run_job(jid, args, folder):
    job = jobs[jid]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", env=env, cwd=str(HERE))
        job["proc"] = proc
        for raw in proc.stdout:
            for part in raw.replace("\r", "\n").split("\n"):
                part = part.strip()
                if part:
                    job["log"].append(part)
                    del job["log"][:-200]
        proc.wait()
        out = folder / "lyrics.json"
        if job.get("cancelled"):
            job["status"] = "cancelled"
        elif proc.returncode == 0 and out.exists():
            import json
            job["lyrics"] = json.loads(out.read_text(encoding="utf-8"))
            job["status"] = "done"
        else:
            job["status"] = "error"
    except Exception as e:  # noqa: BLE001
        job["log"].append(f"Server error: {e}")
        job["status"] = "error"


@app.post("/api/lyrics")
def start_lyrics():
    f = request.files.get("audio")
    if not f:
        return jsonify(error="No audio file was sent."), 400
    jid = uuid.uuid4().hex[:12]
    folder = JOBS / jid
    folder.mkdir()
    ext = (Path(f.filename or "song.mp3").suffix or ".mp3").lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,5}", ext):
        ext = ".mp3"
    audio = folder / f"audio{ext}"
    f.save(audio)

    form = request.form
    args = [sys.executable, str(HERE / "make_lyrics.py"), str(audio), "--out", str(folder / "lyrics.json")]
    if form.get("title", "").strip():
        args += ["--title", form["title"].strip()]
    if form.get("artist", "").strip():
        args += ["--artist", form["artist"].strip()]
    try:
        clip_start = float(form.get("clip_start") or 0)
        args += ["--clip-start", str(max(0.0, clip_start))]
    except ValueError:
        pass
    if form.get("mode") == "whisper":
        args.append("--whisper-only")
    model = form.get("model", "large-v3-turbo")
    args += ["--model", model if model in MODELS else "large-v3-turbo"]

    with jobs_lock:
        jobs[jid] = {"status": "running", "log": [], "started": time.time()}
    threading.Thread(target=run_job, args=(jid, args, folder), daemon=True).start()
    return jsonify(id=jid)


@app.get("/api/jobs/<jid>")
def job_status(jid):
    job = jobs.get(jid)
    if not job:
        return jsonify(error="Job not found."), 404
    return jsonify(status=job["status"], stage=stage_from_log(job["log"]),
                   log=job["log"][-12:], lyrics=job.get("lyrics"),
                   elapsed=round(time.time() - job["started"]))


@app.post("/api/jobs/<jid>/cancel")
def job_cancel(jid):
    job = jobs.get(jid)
    if job and job.get("proc") and job["status"] == "running":
        job["cancelled"] = True
        job["proc"].kill()
    return jsonify(ok=True)


# ------------------------------------------------------------------ mp4 conversion
@app.post("/api/mp4")
def to_mp4():
    if not FFMPEG:
        return jsonify(error="ffmpeg is not available on this computer."), 500
    f = request.files.get("video")
    if not f:
        return jsonify(error="No video was sent."), 400
    preset = request.form.get("preset", "best")
    crf, abr = ("20", "192k") if preset == "best" else ("27", "128k")
    folder = JOBS / ("mp4-" + uuid.uuid4().hex[:10])
    folder.mkdir()
    src, dst = folder / "input.webm", folder / "output.mp4"
    f.save(src)
    cmd = ["ffmpeg", "-y", "-i", str(src),
           "-c:v", "libx264", "-preset", "medium", "-crf", crf, "-pix_fmt", "yuv420p",
           "-r", "30", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
           "-c:a", "aac", "-b:a", abr, "-ar", "44100", "-movflags", "+faststart", str(dst)]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0 or not dst.exists():
        return jsonify(error="ffmpeg could not convert the video.", log=res.stderr[-1500:]), 500
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", request.form.get("name", "lyric-video")).strip("-") or "lyric-video"
    return send_file(dst, mimetype="video/mp4", as_attachment=True, download_name=f"{name}.mp4")


# ------------------------------------------------------------------ main
if __name__ == "__main__":
    url = f"http://127.0.0.1:{PORT}"
    print("\n  Lyric Studio is running at", url)
    print("  ffmpeg:", "ready" if FFMPEG else "MISSING", "| Gemini key:", "set" if GEMINI else "not set")
    print("  Keep this window open while you use the page. Close it to stop.\n")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True)
