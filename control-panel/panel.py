import argparse
import datetime as dt
import hmac
import json
import os
import re
import secrets
import socket
import subprocess
import sys
import urllib.error
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.dont_write_bytecode = True
import pipeline as p
import brand  # noqa: E402  (shown in the window title and substituted into index.html)

HERE = Path(__file__).resolve().parent
TOKEN = secrets.token_urlsafe(32)
ASSETS = {"/": ("index.html", "text/html"), "/app.css": ("app.css", "text/css"),
          "/app.js": ("app.js", "text/javascript")}
WORKERS = {"hunter": p.HUNT, "clip": p.CLIP}


def branded(name, text):
    """Fill the branding placeholders in a served asset."""
    return (text.replace("__APP__", brand.app())
                .replace("__COMPANY__", brand.company())
                .replace("__MARK__", brand.app()[:1].upper())
                .replace("__ACCENT__", brand.accent())
                .replace("__TAGLINE__", brand.tagline()))


class LocalServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def valid_host(self):
        return self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}"

    def send_content(self, data, kind, status=200, **headers):
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for name, value in headers.items():
            self.send_header(name.replace("_", "-"), value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def json(self, data, status=200, **headers):
        self.send_content(json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8", status, **headers)

    def file(self, path):
        with path.open("rb") as file:
            size = os.fstat(file.fileno()).st_size
            start, end, partial = 0, size - 1, False
            request = self.headers.get("Range")
            if request:
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", request)
                if not match or not any(match.groups()) or not size:
                    return self.send_content(b"", "video/mp4", 416, Content_Range=f"bytes */{size}")
                first, last = match.groups()
                if first:
                    start = int(first)
                    end = min(int(last), end) if last else end
                else:
                    start = max(0, size - int(last))
                if start > end:
                    return self.send_content(b"", "video/mp4", 416, Content_Range=f"bytes */{size}")
                partial = True
            self.send_response(206 if partial else 200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("X-Content-Type-Options", "nosniff")
            if partial:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            if self.command != "HEAD":
                file.seek(start)
                remaining = end - start + 1
                while remaining > 0:
                    chunk = file.read(min(131072, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self.valid_host():
            return self.json({"error": "Open the panel at its local address."}, 403)
        route = urlsplit(self.path)
        try:
            if route.path in ASSETS:
                asset, kind = ASSETS[route.path]
                data = (HERE / asset).read_text(encoding="utf-8")
                if route.path == "/":
                    data = branded(asset, data).replace("__PANEL_TOKEN__", TOKEN)
                return self.send_content(data.encode(), kind + "; charset=utf-8")
            if route.path == "/health":
                return self.json({"app": "reelhound-panel", "root": str(p.ROOT.resolve())})
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                return self.json({"error": "Open the panel directly."}, 403)
            params = parse_qs(route.query)
            area = params.get("area", [""])[0]
            if route.path == "/video":
                return self.file(p.clip_path(area, params.get("name", [""])[0]))
            if not hmac.compare_digest(self.headers.get("X-Panel-Token", ""), TOKEN):
                return self.json({"error": "Refresh the panel and try again."}, 403)
            if route.path == "/api/whole":   # outside the lock: it reads 100+ source notes
                return self.json(p.whole_list())
            if route.path == "/api/whole-links":   # outside the lock: asks the phone inbox
                return self.json(p.whole_links())
            with p.LOCK:
                if route.path == "/api/overview":
                    return self.json(p.overview())
                if route.path == "/api/settings":
                    return self.json(p.settings())
                if route.path == "/api/creators":
                    return self.json({"rows": p.creator_list(), "waiting": p.waiting()})
                if route.path == "/api/clips" and area in ("edits", "ready"):
                    return self.json(p.library(area))
                if route.path == "/api/queue":
                    return self.json(p.queue_view())
                if route.path == "/api/scoreboard":
                    return self.json(p.scoreboard())
                if route.path == "/api/export":
                    queue = p.queue_view()
                    return self.json(dict(timezone=p.zone_label(), posts=queue["items"]),
                                     Content_Disposition='attachment; filename="reels-queue.json"')
            self.json({"error": "Page not found."}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (ValueError, OSError) as exc:
            self.json({"error": str(exc)}, 400)

    def do_POST(self):
        if (not self.valid_host() or self.headers.get("Origin") != f"http://{self.headers.get('Host')}"
                or not hmac.compare_digest(self.headers.get("X-Panel-Token", ""), TOKEN)):
            return self.json({"error": "Refresh the panel and try again."}, 403)
        try:
            size = int(self.headers.get("Content-Length", 0))
            if not 0 < size <= 64000 or self.headers.get_content_type() != "application/json":
                raise ValueError("Send a valid form.")
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError("Send a valid form.")
            route = self.path
            action = data.get("action")
            with p.LOCK:
                if route == "/api/worker" and data.get("worker") in WORKERS and type(data.get("enabled")) is bool:
                    worker = WORKERS[data["worker"]]
                    if data["enabled"]:
                        p.require_no_legacy_hunter(self.server.server_port)
                    worker.set(data["enabled"])
                    return self.json(worker.view())
                if route == "/api/settings" and action in ("hunter", "clip"):
                    result = p.save_settings(action, data)
                    WORKERS[action].wake.set()
                    return self.json(result)
                if route == "/api/creators" and action in ("save", "remove"):
                    p.creator_change(action, data)
                elif route == "/api/ai" and action == "run":
                    p.AI.start()
                    return self.json(p.ai_view())
                elif route == "/api/approve":
                    return self.json(p.approve(data["id"]))
                elif route == "/api/review" and action in ("keep", "delete", "caption"):
                    p.review(action, data)
                elif route == "/api/review" and action == "reclip":
                    return self.json({"ok": True, "message": p.redo(data)})
                elif route == "/api/whole" and action == "link":
                    return self.json({"ok": True, "message": p.whole_link(data)})
                elif route == "/api/whole" and action == "link-item":
                    return self.json(p.whole_link_action(data))
                elif route == "/api/whole" and action == "start":
                    return self.json({"ok": True, "message": p.whole_start(data)})
                elif route == "/api/schedule" and action == "settings":
                    p.schedule_save(data)
                elif route == "/api/schedule" and action == "add":
                    p.add_queue(data)
                elif route == "/api/schedule" and action == "remove":
                    cfg = p.schedule()
                    cfg["items"] = [x for x in cfg["items"] if x["name"] != data["name"]]
                    p.write_json(p.SCHEDULE, cfg)
                elif route == "/api/open" and data.get("name") in p.LINKS:
                    target = p.LINKS[data["name"]]
                    if not target.exists():
                        raise ValueError(f"{target.name} does not exist yet.")
                    subprocess.Popen(["explorer.exe", str(target) if target.is_dir() else f"/select,{target}"])
                else:
                    return self.json({"error": "Unknown action."}, 404)
            self.json({"ok": True})
        except PermissionError:
            self.json({"error": "A file is in use or inaccessible. Close it in other apps and try again."}, 409)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self.json({"error": str(exc)}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass


def main():
    args = argparse.ArgumentParser()
    args.add_argument("--port", type=int, default=8875)
    args.add_argument("--no-browser", action="store_true")
    opts = args.parse_args()
    url = f"http://127.0.0.1:{opts.port}"
    try:
        server = LocalServer(("127.0.0.1", opts.port), Handler)
    except OSError as exc:
        try:
            with urllib.request.urlopen(url + "/health", timeout=2) as response:
                existing = json.load(response)
            if existing == {"app": "reelhound-panel", "root": str(p.ROOT.resolve())}:
                if not opts.no_browser:
                    webbrowser.open(url)
                return 0
        except (OSError, ValueError):
            pass
        print(f"Could not open {url}: {exc}")
        print("Another local service may already be using the panel's port.")
        return 1
    with server:
        p.prepare_ffmpeg()
        print(f"{brand.label()} · {url}")
        print("Keep this window open. Use Ctrl+C to stop the panel after current work finishes.", flush=True)
        if not opts.no_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            active = []
            for worker in WORKERS.values():
                worker.set(False)
                if worker.thread:
                    active.append(worker.thread)
            if active:
                print("Finishing the current scan or video. Press Ctrl+C again to exit immediately.", flush=True)
                for thread in active:
                    thread.join()
    return 0


if __name__ == "__main__":
    sys.exit(main())
