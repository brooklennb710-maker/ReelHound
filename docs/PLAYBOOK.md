# ReelHound — playbook

The rules that keep a clipping page alive: **permission, credit, and posting what the clip actually shows.**
ReelHound enforces what it can in code; this page is the part that needs your judgement.

---

## 1. The permission ladder

Every source you clip must sit on one of these rungs. There are no other rungs.

| Rung | In `creators.csv` | What it means |
|---|---|---|
| **Yours** | `own` | You shot it. Clip freely, no credit needed (a credit never hurts). |
| **Official** | `official` | The brand/publisher's own channel and their own media. Clip it, credit it, never imply you are them. |
| **Said yes** | `yes` | You asked and they replied yes. Keep the message. Credit on screen and in the caption. |
| **Asked** | `asked` | Waiting. Do not publish until they answer. |
| **No** | `no` | Never. Not "just this once", not with a bigger credit. |
| **Unknown** | missing | Treat as "no" until you have asked. |

**Credit is not permission.** A big credit line does not make an unapproved clip okay.
**Permission is not immunity either:** a creator can say yes today and ask you to take it down next
month. Respect that without arguing — remove it, keep the relationship.

### How to ask

Short, specific, easy to say yes to. ReelHound drafts one for you on the finds page and the Creators
page; it reads like this:

> Hey @creator! Love your video "…". I run @yourpage, a … page. Ok if we cut a short clip from it
> with full credit to you on screen and in the caption? Happy to tag you. No worries if not!

What makes answers come back positive:

- Say exactly what you will do (a clip, a credit, a tag, a link).
- No pressure, no "I'll post it anyway".
- One message. No follow-ups every day.
- When they say yes, screenshot it and note the date in `creators.csv` (`notes`).

---

## 2. Credit

- **On screen:** `via @handle`, in every clip of third-party footage. ReelHound adds it automatically
  when you pass `--credit`.
- **In the caption:** the same handle, on its own line.
- Official media: credit the publisher's handle, and say nothing that sounds like an announcement from them.
- Never crop out a creator's watermark to replace it with yours.

---

## 3. What earns a post

A clip gets published when it has **all four**:

1. **A reason to watch in the first second.** The interesting thing is already happening, or the hook
   text states it plainly. No intros, no logos, no menus.
2. **One payoff.** A trick, a reveal, a result, a joke that lands, a moment of skill. If you cannot say
   what the payoff is in one sentence, it is not a clip yet.
3. **Clean framing.** Fills a 9:16 frame, text readable on a phone, no letterbox bars, no facecam
   covering the action, no cut-off captions.
4. **A stranger could follow it.** No "as I said earlier", no context that only the original audience has.

Length: **15–60 seconds** is the sweet spot. Up to ~90 s for a guide, a chase or a story that needs it.
Under 8 s rarely lands; over 90 s needs a reason.

### Hooks

- 2–6 words, a complete phrase, never ending on a dangling word ("…IN", "…WISH I").
- Specific to *this* clip, not to the topic in general.
- Never promise what the clip does not show. That is the one rule that kills accounts.
- No spoilers for story-driven content, no numbers you have not verified, no "official".

### Captions

- Sentence case, 1–2 sentences of actual value: the tip, the setting, the joke, the result.
- At most one emoji. Hashtags go on their own line (ReelHound appends `caption_hashtags`).
- Do not write "this clip" or "this video".

---

## 4. Posting rhythm

- **Quality beats volume.** Three good clips a week beat three mediocre clips a day.
- Pick a small set of slots and keep them (`schedule.json`). The panel assigns the next free slot.
- Post the best thing you have; keep a small backlog in `media/ready`, never a big one — trends age fast.
- Watch the first 24 hours: if a clip is flat at 3 hours, the hook or the first frame is the problem.
- Log every post in `scoreboard.csv` (views 12/24/72 h, shares, saves). After 20 posts your own data will
  be worth more than any general advice, including this page.

---

## 5. When someone objects

1. Remove the post or clip within a day. No negotiation, no "but I credited you".
2. Reply once, briefly, without defensiveness: "Removed it — thanks for telling me."
3. Mark them `no` in `creators.csv` so the hunter never queues them again.
4. If it was a paid or licensed source, check the terms before reusing anything else from it.

---

## 6. Hard lines

- No content you know is false, manipulated to mislead, or an unverified "leak" presented as fact.
- No private individuals, no doxxing, no harassment.
- No sexual content involving minors, no hate speech, no glorified violence.
- No selling third-party footage, no "official" claims, no fake giveaways.
- Follow the platform terms of every destination you post to. ReelHound cannot check them for you.

---

## 7. The checklist before you press publish

- [ ] Permission recorded (`own`, `official` or `yes`)
- [ ] Credit on screen **and** in the caption
- [ ] Hook is true to the clip
- [ ] First frame is interesting, not a logo or a menu
- [ ] Captions are readable on a phone
- [ ] Length is right for the payoff
- [ ] Allowed on every destination (some platforms have stricter rules)
- [ ] Nothing personal or unverified in the caption
