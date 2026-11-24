"""Re-render existing clips in media/edits with the new AI hook and caption writer.

Same source, same time range, same credit and preset; only the hook, captions
(translated to English when needed) and caption text change. The old file and
its caption move to media/edits/_old-hooks, never deleted.

  python regen_hooks.py            redo every clip whose caption still has the placeholder
  python regen_hooks.py --limit 3  try a few first
"""
import argparse, json, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
RAW = os.path.join(ROOT, "media", "raw")
EDITS = os.path.join(ROOT, "media", "edits")
OLD = os.path.join(EDITS, "_old-hooks")
CONFIG = os.path.join(ROOT, "hunter", "config.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    cfg = json.load(open(CONFIG, encoding="utf-8")) if os.path.exists(CONFIG) else {}
    os.makedirs(OLD, exist_ok=True)
    names = sorted(n for n in os.listdir(EDITS) if n.endswith(".mp4") and not n.endswith(".part.mp4"))
    done = failed = 0
    for n, name in enumerate(names, 1):
        if a.limit and done >= a.limit:
            break
        mp4 = os.path.join(EDITS, name)
        txt = mp4[:-4] + ".txt"
        if not os.path.exists(txt):
            continue
        text = open(txt, encoding="utf-8-sig", errors="replace").read()
        if "[1-2 sentences" not in text:
            continue  # already has a real caption (new pipeline or hand-written)
        meta = dict(re.findall(r"^(source|range|permission|credit|preset):[ \t]*(.*)$", text, re.M))
        m = re.match(r"([\d.:]+)\s*to\s*([\d.:]+)", meta.get("range", ""))
        src = os.path.join(RAW, meta.get("source", ""))
        if not m or not os.path.isfile(src):
            print(f"[{n}/{len(names)}] skip {name}: source video or range missing")
            continue
        title = ""
        note = os.path.splitext(src)[0] + ".source.json"
        if os.path.exists(note):
            title = json.load(open(note, encoding="utf-8")).get("title", "")
        cmd = [sys.executable, os.path.join(HERE, "clipmaker.py"), src, "--start", m.group(1), "--end", m.group(2),
               "--permission", meta.get("permission", ""), "--preset", meta.get("preset", "viral") or "viral",
               "--out", EDITS, "--auto-hook", "--source-title", title or name,
               "--whisper-model", cfg.get("whisper_model") or "small",
               "--credit-position", cfg.get("credit_position") or "bottom-center"]
        if meta.get("credit"):
            cmd += ["--credit", meta["credit"]]
        if cfg.get("caption_size"):
            cmd += ["--caption-size", str(cfg["caption_size"])]
        if cfg.get("captions") is False:
            cmd.append("--no-captions")
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           env=dict(os.environ, PYTHONUTF8="1"))
        hook = re.search(r"Hook \((\w+)\): (.+)", r.stdout or "")
        if r.returncode != 0 or "Done:" not in (r.stdout or ""):
            failed += 1
            print(f"[{n}/{len(names)}] FAILED {name}: {(r.stdout + r.stderr)[-300:]}")
            continue
        new = re.search(r"Done: (.+\.mp4)", r.stdout)
        if not os.path.exists(mp4):
            # The original was kept or deleted in the panel while rendering: don't resurrect it.
            orphans = os.path.join(OLD, "_removed-during-regen")
            os.makedirs(orphans, exist_ok=True)
            if new and os.path.exists(new.group(1).strip()):
                for f in (new.group(1).strip(), new.group(1).strip()[:-4] + ".txt"):
                    if os.path.exists(f):
                        shutil.move(f, os.path.join(orphans, os.path.basename(f)))
            print(f"[{n}/{len(names)}] {name} was moved or deleted during the re-render; set the new copy aside")
            continue
        shutil.move(mp4, os.path.join(OLD, name))
        if os.path.exists(txt):
            shutil.move(txt, os.path.join(OLD, os.path.basename(txt)))
        done += 1
        print(f"[{n}/{len(names)}] {name} -> {hook.group(2) if hook else '?'} ({hook.group(1) if hook else ''})", flush=True)
    print(f"\nRe-rendered {done} clips, {failed} failed. Old versions are in {OLD}")


if __name__ == "__main__":
    main()
