"""ReelHound doctor: check that this PC can run every part of the tool, and say
exactly what to fix when something is missing.

    python reelhound.py doctor
    python doctor.py            (same thing)
    python doctor.py --fix-path (also adds the winget FFmpeg folder to this window's PATH)

Nothing is installed or changed by default: it only looks and reports.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OK, WARN, FAIL = "OK", "WARN", "FAIL"

PACKAGES = [
    ("requests", "hunter: YouTube, Reddit and Instagram lookups", "requests"),
    ("yt_dlp", "hunter + phone inbox: downloads", "yt-dlp"),
    ("faster_whisper", "clip maker: burned-in captions", "faster-whisper"),
    ("numpy", "clip maker: audio analysis for best moments", "numpy"),
]

PORTS = [(8875, "control panel"), (8765, "hunter finds page"), (8876, "phone inbox")]


def line(level, name, detail="", fix=""):
    return dict(level=level, name=name, detail=detail, fix=fix)


def ffmpeg_folder():
    """The winget-installed FFmpeg folder, when it is not on PATH (common after install)."""
    profile = Path(os.environ.get("USERPROFILE", ""))
    for folder in [profile / "AppData/Local/Microsoft/WinGet/Links",
                   *(p.parent for p in (profile / "AppData/Local/Microsoft/WinGet/Packages").glob("*FFmpeg*/*/bin/ffmpeg.exe"))]:
        if (folder / "ffmpeg.exe").is_file() and (folder / "ffprobe.exe").is_file():
            return folder
    return None


def check_python():
    version = sys.version_info
    if version >= (3, 10):
        return line(OK, "Python", f"{version.major}.{version.minor}.{version.micro}")
    return line(FAIL, "Python", f"{version.major}.{version.minor} is too old",
                "Install Python 3.10 or newer from python.org, or run setup.bat.")


def check_ffmpeg():
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        folder = ffmpeg_folder()
        if folder:
            return line(WARN, "FFmpeg", "found, but not on PATH",
                        f"Close and reopen your terminal, or run setup.bat. (Folder: {folder})")
        return line(FAIL, "FFmpeg", "not found",
                    "Run setup.bat, or install it with: winget install Gyan.FFmpeg")
    try:
        out = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=10).stdout
        first = (out.splitlines() or ["ffmpeg"])[0]
    except (OSError, subprocess.SubprocessError):
        return line(FAIL, "FFmpeg", "could not run it", "Reinstall: winget install Gyan.FFmpeg")
    return line(OK, "FFmpeg", first[:70])


def check_ytdlp_module():
    if importlib.util.find_spec("yt_dlp") is None:
        return line(FAIL, "yt-dlp (module)", "not installed", "pip install -U yt-dlp")
    return line(OK, "yt-dlp (module)", "installed")


def check_packages():
    out = []
    for module, why, package in PACKAGES:
        if importlib.util.find_spec(module) is not None:
            out.append(line(OK, package, why))
        else:
            out.append(line(WARN, package, f"missing - {why}", f"pip install {package}"))
    return out


def ollama_models(timeout=1.5):
    import urllib.request

    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=timeout) as response:
            return [m["name"] for m in json.loads(response.read()).get("models", [])]
    except Exception:
        return None


def check_ollama():
    models = ollama_models()
    if models is None:
        return [line(WARN, "Ollama (optional)", "not running",
                     "For AI hooks and clip scoring: install ollama.com, then run 'ollama serve'. Everything else works without it.")]
    out = [line(OK, "Ollama (optional)", f"running, {len(models)} model(s)")]
    try:
        config = json.loads((ROOT / "hunter" / "config.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        config = {}
    wanted = {"hook model": config.get("hook_model") or "qwen3.5:9b",
              "review model": config.get("review_model") or "gemma4:12b"}
    for label, model in wanted.items():
        found = any(name == model or name.startswith(model + ":") for name in models)
        out.append(line(OK if found else WARN, label, model,
                        "" if found else f"ollama pull {model}"))
    return out


def check_brand():
    try:
        import brand

        data = brand.load(refresh=True)
    except Exception as exc:  # a broken brand.json must not stop the doctor
        return [line(FAIL, "brand.json", f"could not read it ({exc})", "Fix the JSON, or delete brand.json to use defaults.")]
    if brand.configured():
        return [line(OK, "brand.json", f"{brand.channel()} ({brand.handle() or 'no handle'})")]
    return [line(WARN, "brand.json", "not set up yet",
                 "Run: python reelhound.py init (adds your handle, niche and watermark)")]


def check_config():
    path = ROOT / "hunter" / "config.json"
    if not path.exists():
        return [line(WARN, "hunter/config.json", "missing",
                     "Run setup.bat, or: copy hunter\\config.example.json hunter\\config.json")]
    try:
        config = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        return [line(FAIL, "hunter/config.json", f"invalid JSON ({exc})", "Fix it or start again from config.example.json.")]
    out = [line(OK, "hunter/config.json", f"{len(config.get('keywords', []))} keyword(s)")]
    if not str(config.get("youtube_api_key", "")).strip().startswith("PASTE"):
        out.append(line(OK, "YouTube API key", "saved"))
    else:
        out.append(line(WARN, "YouTube API key", "not set",
                        "Keyword search needs one (free): console.cloud.google.com > YouTube Data API v3. "
                        "Channels in creators.csv are checked without a key."))
    if config.get("keywords"):
        out.append(line(OK, "search keywords", f"{len(config['keywords'])} set"))
    else:
        out.append(line(WARN, "search keywords", "empty", 'Add search terms in hunter/config.json or run init.'))
    return out


def check_folders():
    wanted = ["media/raw", "media/edits", "media/ready", "hunter", "clipmaker", "control-panel", "inbox", "reviewer"]
    missing = [name for name in wanted if not (ROOT / name).is_dir()]
    if not missing:
        return [line(OK, "folders", "all present")]
    return [line(FAIL, "folders", "missing: " + ", ".join(missing), "Re-download the repo, or create them.")]


def check_data_files():
    out = []
    for name, sample in [("hunter/creators.csv", "creators.sample.csv"),
                         ("hunter/finds.csv", "finds.sample.csv"),
                         ("control-panel/schedule.json", "schedule.example.json"),
                         ("scoreboard.csv", "scoreboard.sample.csv")]:
        if (ROOT / name).exists():
            out.append(line(OK, name, "present"))
        else:
            out.append(line(WARN, name, "not created yet", f"Run setup.bat (copies {sample}), or copy it yourself."))
    return out


def check_ports():
    out = []
    for port, what in PORTS:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.3)
            busy = sock.connect_ex(("127.0.0.1", port)) == 0
        out.append(line(OK if not busy else WARN, f"port {port}", what + (" - in use (fine if ReelHound is already open)" if busy else " - free")))
    return out


def check_disk():
    try:
        free = shutil.disk_usage(str(ROOT)).free / 2**30
    except OSError:
        return [line(WARN, "disk space", "could not read it")]
    if free >= 20:
        return [line(OK, "disk space", f"{free:.0f} GB free")]
    return [line(WARN, "disk space", f"only {free:.1f} GB free", "Clips are 5-30 MB each; free up some space.")]


def run_all():
    results = [check_python(), check_ffmpeg(), check_ytdlp_module()]
    results += check_packages()
    results += check_brand()
    results += check_config()
    results += check_folders()
    results += check_data_files()
    results += check_ollama()
    results += check_ports()
    results += check_disk()
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="Check this PC is ready for ReelHound.")
    parser.add_argument("--fix-path", action="store_true", help="add a winget FFmpeg folder to this process's PATH")
    parser.add_argument("--quiet", action="store_true", help="only show problems")
    args = parser.parse_args(argv)

    if args.fix_path:
        folder = ffmpeg_folder()
        if folder:
            os.environ["PATH"] = str(folder) + os.pathsep + os.environ["PATH"]
            print(f"Added {folder} to PATH for this window.")

    results = run_all()
    problems = [r for r in results if r["level"] != OK]
    if not args.quiet:
        print(f"\n{'=' * 58}\n ReelHound doctor\n{'=' * 58}")
    for r in results:
        if args.quiet and r["level"] == OK:
            continue
        print(f"[{r['level']:4}] {r['name']}: {r['detail']}")
        if r["fix"]:
            print(f"         fix: {r['fix']}")
    failures = [r for r in results if r["level"] == FAIL]
    print()
    if failures:
        print(f"{len(failures)} thing(s) need fixing before everything works. See the fix lines above.")
        return 1
    if problems:
        print(f"Ready to use. {len(problems)} optional/setup item(s) above (WARN) - see the fix lines.")
    else:
        print("Everything checks out. Try:  python reelhound.py panel")
    return 0


if __name__ == "__main__":
    sys.exit(main())
