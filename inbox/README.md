# inbox/

Clip from your phone: paste a link or drop a video, and the PC downloads it, checks permission, cuts it
and puts the result in `media/edits`.

```
python reelhound.py inbox
```

Double-click `Open Phone Inbox.bat` for the full experience: it starts `tailscale serve` (tailnet only,
never the public internet) and then the server, so the page is reachable from your phone at
`https://YOUR-PC-NAME.YOUR-TAILNET.ts.net`.

## What happens to a link

1. The page posts the link (and whether it is **yours** or **someone else's**) to the inbox.
2. The PC downloads it with yt-dlp into `media/raw/phone-inbox`.
3. The creator is looked up in `hunter/creators.csv`:
   - `own` / `yes` / `official` → written a `.source.json` note and clipped.
   - `unknown` → held in `media/raw/phone-inbox/_held` with a draft message; **nothing is sent**.
   - `no` → skipped.
4. The clips appear on the phone page (and in `media/edits`), ready to review, re-clip, or send to ready.

A video longer than ~90 s gets a question instead of a guess: one clip, split into parts, or the first 90 s.

## Configuration

Create `inbox/config.json` from `config.example.json` (git-ignored):

| Key | Meaning |
|---|---|
| `port` | Server port, default `8876`. |
| `my_accounts` | Your own handles per platform, so links to your own posts count as `own`. |
| `cookies_from_browser` | Browser to borrow cookies from when Instagram/YouTube refuses. |
| `short_clip_max_seconds` | Above this the page asks one-clip / parts / first-90-s. |

Files: `inbox.py` (server + worker), `page.html` (the phone page), `items.json` (queue state, git-ignored).

## Safety

- Binds to `127.0.0.1`; `tailscale serve` puts it on your tailnet only.
- Requests from outside the tailnet/localhost are refused.
- It never posts anything and never messages a creator.
