# COMMS: agent <-> consultant

Append-only channel. Newest entry at the bottom. Never edit an old entry; add a
new one that refers to it. Full rules are in `HANDOFF.md`, section
"Communication protocol". No API keys or tokens in this file, ever.

Entry format:

```
## C-014 | 2026-10-27 | agent -> consultant | BLOCKED | OPEN
Commit: a1b2c3d   Files: cutwright/mlt.py L730-754
Goal: one line.
Tried: numbered, with the exact command or edit each time.
Observed: the real output, trimmed to the lines that matter.
Known / assumed: two short lists, kept apart.
Ask: the one question or decision wanted.
```

Types: `BLOCKED`, `QUESTION`, `REVIEW`, `BREAKTHROUGH`, `ANSWER`, `INFO`.
Status: `OPEN` until the other side replies, then `ANSWERED`.

---

## C-001 | 2026-10-26 | consultant -> agent | INFO | OPEN
Commit: a87f4bf (nothing pushed yet)
Goal: get started with the shared plan.
Tried: n/a. The consultant has read HANDOFF.md and the top of README.md only.
Known: the crossfade shape is designed and written up in HANDOFF.md.
Assumed: the owner's notes about the borrowed repos are accurate; none were read.
Ask:
1. Read `HANDOFF.md` top to bottom, including the protocol sections.
2. Reply here with entry C-002 confirming you can **push** to
   `origin` (`github.com/altzotify-cell/cutwright`). Nothing was pushed at the
   2026-10-24 pause.
3. Start Phase 0. Post a `BREAKTHROUGH` entry when `crossfade` and `gui_xfade`
   both pass, or a `BLOCKED` entry after two failed attempts.
