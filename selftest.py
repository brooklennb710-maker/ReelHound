"""ReelHound self-test: prove the install actually renders a clip.

    python reelhound.py selftest
    python selftest.py

It builds a small test video with FFmpeg, runs the real clip maker on it
(no captions, so Whisper is not needed), checks the result with ffprobe, and
cleans up after itself. Nothing in media\\edits is touched.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import brand  # noqa: E402


def which(*names):
    return all(shutil.which(name) for name in names)


def run(command, cwd=None, timeout=300):
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout,
                          env=dict(os.environ, PYTHONUTF8="1"))


def say(level, message):
    print(f"[{level}] {message}")


def probe(path):
    result = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    if result.returncode != 0:
        return None
    info = json.loads(result.stdout)
    video = next((s for s in info["streams"] if s.get("codec_type") == "video"), {})
    return dict(duration=float(info["format"].get("duration", 0)),
                width=video.get("width"), height=video.get("height"),
                has_audio=any(s.get("codec_type") == "audio" for s in info["streams"]))


def main():
    print(f"\n{brand.label()} self-test\n" + "-" * 46)
    failures = 0

    if sys.version_info < (3, 10):
        say("FAIL", f"Python {sys.version.split()[0]} is too old (need 3.10+)")
        return 1
    say("OK", f"Python {sys.version.split()[0]}")

    if not which("ffmpeg", "ffprobe"):
        say("FAIL", "FFmpeg is not on PATH. Run setup.bat, then try again.")
        return 1
    say("OK", "FFmpeg and FFprobe")

    for module in ("brand", "doctor"):
        try:
            __import__(module)
        except Exception as error:  # noqa: BLE001 - any import error is the point
            say("FAIL", f"importing {module} failed: {error}")
            failures += 1
    if not failures:
        say("OK", "core modules import")

    # The hunter needs 'requests' at import time; check it without starting a scan.
    try:
        subprocess.run([sys.executable, "-c", "import requests"], capture_output=True, check=True)
        say("OK", "requests (hunter)")
    except subprocess.CalledProcessError:
        say("WARN", "requests is missing - the hunter will not run. pip install requests")

    work = Path(tempfile.mkdtemp(prefix="reelhound-selftest-"))
    source, output = work / "test_source.mp4", work / "out"
    try:
        make = run(["ffmpeg", "-y", "-v", "error",
                    "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                    "-t", "8", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(source)])
        if make.returncode != 0 or not source.exists():
            say("FAIL", "could not build the test video:\n" + (make.stderr or "")[-600:])
            return 1
        say("OK", "built an 8 second test video")

        clip = run([sys.executable, str(ROOT / "clipmaker" / "clipmaker.py"), str(source),
                    "--start", "0", "--end", "6", "--hook", "SELF TEST PASSED",
                    "--permission", "own", "--preset", "clean", "--no-captions",
                    "--no-watermark", "--out", str(output)], cwd=str(ROOT / "clipmaker"))
        if clip.returncode != 0:
            say("FAIL", "the clip maker failed:\n" + (clip.stdout + clip.stderr)[-1500:])
            return 1
        clips = list(output.glob("*.mp4")) if output.exists() else []
        if not clips:
            say("FAIL", "the clip maker did not write an MP4")
            return 1
        info = probe(clips[0])
        if not info:
            say("FAIL", "ffprobe could not read the clip")
            return 1
        if not 5 <= info["duration"] <= 7:
            say("FAIL", f"clip length is {info['duration']:.1f}s, expected about 6s")
            return 1
        if (info["width"], info["height"]) != (1080, 1920):
            say("FAIL", f"clip is {info['width']}x{info['height']}, expected 1080x1920")
            return 1
        say("OK", f"rendered a {info['duration']:.1f}s 1080x1920 clip")
        caption = clips[0].with_suffix(".txt").exists()
        say("OK" if caption else "WARN", "caption draft written" if caption else "no caption draft sidecar")
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print("-" * 46)
    print("Everything works. Next:  python reelhound.py panel\n")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
