"""ReelHound profile: one small JSON file drives every name, handle, watermark,
time zone and posting destination in the tool.

Copy ``brand.example.json`` to ``brand.json`` and edit it, or run
``python reelhound.py init``. ``brand.json`` is git-ignored, so your real handle
never lands in a public repo.

    from brand import credit_for, watermark, destinations, tz
"""
from __future__ import annotations

import datetime as dt
import json
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
BRAND = os.path.join(ROOT, "brand.json")

DEFAULTS = {
    "app": "ReelHound",
    "company": "BridgesTech",
    "tagline": "Find it. Clip it. Post it.",
    "handle": "",
    "channel": "",
    "niche": "short-form clips",
    "watermark": "",
    "accent": "#f0b429",
    "timezone": "",
    "destinations": ["Instagram Reels", "Facebook Reels", "TikTok", "YouTube Shorts"],
    "caption_hashtags": "#reels #shorts",
}

_cache = {}


def load(refresh=False):
    """Every branding setting, with defaults filled in for anything left blank."""
    if _cache and not refresh:
        return _cache["data"]
    data = dict(DEFAULTS)
    try:
        with open(BRAND, encoding="utf-8-sig") as file:
            saved = json.load(file)
    except (OSError, ValueError):
        saved = {}
    if isinstance(saved, dict):
        for key, value in saved.items():
            if value is None or value == "":
                continue  # blank means "use the default"
            data[key] = value
    if not isinstance(data.get("destinations"), list) or not data["destinations"]:
        data["destinations"] = list(DEFAULTS["destinations"])
    _cache["data"] = data
    return data


def save(changes):
    """Merge changes into brand.json and return the reloaded settings."""
    data = load(refresh=True)
    data.update({key: value for key, value in changes.items() if value is not None})
    with open(BRAND, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.write("\n")
    _cache.clear()
    return load()


def text(key):
    return str(load().get(key) or "").strip()


def app():
    return text("app") or DEFAULTS["app"]


def company():
    return text("company") or DEFAULTS["company"]


def label():
    """'ReelHound by BridgesTech' - used in window titles and the panel banner."""
    return f"{app()} by {company()}"


def tagline():
    return text("tagline") or DEFAULTS["tagline"]


def handle():
    return text("handle")


def channel():
    """The page/channel name that permission messages mention."""
    return text("channel") or handle() or app()


def niche():
    """What the channel is about, in a few words. Used in AI prompts."""
    return text("niche") or DEFAULTS["niche"]


def watermark():
    """Burn-in text for clips. Empty string = no watermark."""
    return text("watermark")


def accent():
    return text("accent") or DEFAULTS["accent"]


def destinations():
    return tuple(str(x).strip() for x in load()["destinations"] if str(x).strip())


def hashtags():
    """Normalised '#tag #tag' string from a list or a plain string."""
    value = load().get("caption_hashtags")
    tags = value if isinstance(value, list) else str(value or "").split()
    out = []
    for tag in tags:
        tag = str(tag).strip().lstrip("#")
        if tag and "#" + tag not in out:
            out.append("#" + tag)
    return " ".join(out)


def tz():
    """The system time zone, or the IANA name set in brand.json when it loads."""
    name = text("timezone")
    if name and name.lower() not in ("local", "system"):
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(name)
        except Exception:
            pass  # no IANA data on this Python; fall back to the system zone
    return dt.datetime.now().astimezone().tzinfo


def local(moment):
    """Convert an aware UTC datetime to the user's local time zone."""
    return moment.astimezone(tz())


def clock():
    return dt.datetime.now().strftime("%H:%M:%S")


def credit_for(creator, permission=""):
    """The on-screen credit for a source.

    Your own footage gets no credit; everyone else gets '@' plus their name with
    the spaces removed ('Official Trailers' -> '@OfficialTrailers').
    """
    creator = (creator or "").strip()
    if not creator or (permission or "").strip().lower() == "own":
        return ""
    handle = "".join(creator.split())
    return handle if handle.startswith("@") else "@" + handle


def configured():
    """True once the user has put their own handle in (the setup wizard's job)."""
    return bool(handle() or text("channel"))
