> **REFERENCE COPY. Do not read this whole file.** The short working file is
> `HANDOFF.md`. Open this one only for a specific section: run `grep -n "^## \|^### "
> HANDOFF_FULL.md`, then read just the lines of the section you need (for Phase 0,
> "The shape that works -- in both engines" and "The edit to make").

# Handoff

**Updated 2026-10-26. Read this top section first; the 2026-10-24 crossfade handoff
is kept unchanged below it.**

## Status of this update

Nothing in the code was changed. This section is a plan, written before any work
starts, so that it survives running out of free-plan credits. Any agent (Cline,
Claude Code, a chat model) can pick it up from here.

Two limits on how far to trust it:

- The consultant session (Claude, chat, free plan) had **no network and no way to
  clone repos**. Every statement below about `shotcut-mcp`, `cli-anything-shotcut`,
  NarratoAI and RecapStudio comes from the owner's own notes, not
  from reading those repos. Phase 1 exists to fix that.
- Licences were **not checked**. "Apache 2.0, so copying is clean" is the owner's
  note about cli-anything-shotcut and is unverified. Shotcut itself is GPL. Do not
  copy code out of any repo until its LICENSE file has been read (Phase 1).

## What the owner wants (restated from the 2026-10-26 prompt)

1. **Stop hand-building editor controls.** Shotcut's CLI wrappers already implement
   clips, trims, splits, moves, transitions, text overlays and filters, rendered
   through `melt` as a subprocess and emitting native `.mlt` files that open in the
   Shotcut GUI. Copy their approach instead of designing each control in Cutwright.
   Sources named: `NoBanks/shotcut-mcp`, `mltframework/shotcut`, and the
   `cli-anything-shotcut` package.
2. **Integrate RecapStudio fully** (`github.com/altzotify-cell/RecapStudio`) so the
   agent calls its tools directly. Today a human pastes `PASTE_THIS_TO_CLAUDE_*.txt`
   into a chat; the agent should replace that step.
3. **Better perception than NarratoAI.** Today the AI reads transcript/subtitles,
   emits a JSON, a script runs ffmpeg for screenshots where the AI was unsure. Two
   blind spots to close:
   - *Silent stretches*: no dialogue means no signal, so nothing gets tagged.
   - *Confident-but-wrong*: the transcript says "let's go to the beach", the scene
     shows a spaceship, and no uncertainty tag fires.
   Proposed fix: **coverage sheets**. Cutwright already detects shot changes with
   ffmpeg, so drop one contact sheet at every shot boundary that has no overlapping
   dialogue, plus a floor of one per few minutes.
4. **Keep verification.** Every feature added must come with a check. That is what
   distinguishes Cutwright from the tools it borrows from.
5. Reference repo also named: `linyqh/NarratoAI`.

## Borrow list (from the owner's notes; effort estimates are theirs)

From `cli-anything-shotcut`:

| Borrow | Gives Cutwright | Effort |
|---|---|---|
| Ducking + volume envelopes | Music under voice, the biggest gap | Low: copy the MLT XML shape, wrap in dB checks |
| Transitions (add/remove/set; luma/mix/composite) | Crossfades, dissolves | Low-med |
| Blend modes / opacity / PIP | Overlays, watermarks, insets | Low |
| Preview bundles, live preview, trajectory | Agent can see the rough cut | Medium |
| SKILL.md format + `npx skills install` | One-command adoption by any agent | Low |
| `--json` on everything | Machine-readable output | Low |
| Undo/redo session model | Try, check, undo, retry | Medium, or skip |

From NarratoAI:

| Borrow | Gives Cutwright | Effort |
|---|---|---|
| Sonilo BGM/SFX API | Royalty-free music and effects | Low-med |
| Tavily plot-search pre-step | More accurate scripts | Low |
| Subtitle mask (percent-positioned blur) | Recaps over hardsubbed footage | Medium |
| Keyframe batching (interval/batch/concurrency) | Coverage sheets at scale | Low |
| TwelveLabs Pegasus option | Motion-aware understanding (fights) | Low, needs key |
| Gemini Flash Lite / SiliconFlow Qwen-VL | Cheap hosted captioning | Config only |

## Consultant's adjustments to that list

- **Do not borrow transitions or envelopes before the crossfade edit lands.** The
  2026-10-24 work found that Shotcut sets `disable=1` on V1's `frei0r.cairoblend`
  on every Ctrl+S, silently killing any flat multitrack `luma`/opacity dissolve.
  Borrowed transitions will very likely be exactly that shape. Every borrowed
  transition, blend or envelope must survive a real Ctrl+S and pass `gui_xfade`
  or an equivalent, or it is not borrowed, only imported.
- **Skip undo/redo.** A plan is JSON and `build` regenerates the project; that is
  already a clean retry loop.
- **Network-dependent borrows (Sonilo, Tavily, TwelveLabs, hosted captioners) are
  optional and default off.** The README says Cutwright is standard library only,
  and the owner is credit-sensitive. Put them behind a config flag and a separate
  module so the core stays dependency-free.
- **Confident-but-wrong needs one more mechanism than silent coverage.** Coverage
  sheets at shot boundaries catch silence. To catch the beach/spaceship case, also
  sample a small, fixed fraction of dialogue beats that were *not* flagged and
  attach a sheet to them. This is the consultant's suggestion, not the owner's;
  keep it only if it proves cheap.
- **Define "integrate fully" before building it.** Cheapest version: RecapStudio's
  numbered steps become Cutwright subcommands with `--json`, and the agent calls the
  CLI. An MCP server can wrap that later. Do not start with the MCP server.

## Ground rules for every step

1. Each step is independently shippable. Finish, run checks, commit, then stop or go on.
2. Every write goes through `cutwright/guard.py`. No exceptions, including RecapStudio
   integration code.
3. A borrowed feature gets a Cutwright check before it counts as done.
4. Read the LICENSE of a source repo before copying from it. If unclear, copy the
   MLT XML *shape* (a file format) and write the code fresh.
5. Record every borrowed file, its repo, commit and licence in `PROVENANCE.md`.
6. Gotchas from the old handoff still apply (no BOM, `git commit -F`, small editor
   writes, `not_run` is not `pass`).

## Communication protocol (agent <-> consultant)

Three files, three jobs. Do not merge them.

| file | job | changes |
|---|---|---|
| `HANDOFF.md` | The plan, the rules, and a short **Current status** block. The source of truth for "where are we". | Rarely; the status block after each breakthrough |
| `LOG.md` (exists) | Running log. One dated entry per breakthrough *and* per dead end. | Often, append-only |
| `COMMS.md` (new) | The channel between agent and consultant: questions, blockers, review requests, answers. | Often, append-only |

Why `COMMS.md` is separate from `HANDOFF.md`: a channel grows every time someone
speaks, and the consultant has to re-read whatever file it is given. Mixing them
buries the plan under chatter and makes the one file everyone must read the
longest. Keep the plan short; let the channel be long.

### How messages travel

The consultant (Claude, in a chat) cannot write to GitHub or touch the repo. The
owner is the relay.

- **Agent to consultant:** the agent appends an entry to `COMMS.md`, commits and
  **pushes**. The owner pastes into the consultant chat either the entry text
  (always works) or the raw link to it, on its own line with a space after it.
  Link to a specific commit, not `main`, so the text cannot change or lag.
- **Consultant to agent:** the consultant replies in chat in the same entry
  format. The owner pastes it at the end of `COMMS.md` (or tells the agent to)
  and commits.

Limits to know about (as of 2026-10-26, not all tested):

- The consultant's fetch tool only opens URLs it was given cleanly in a message
  or found by search. A first test on the RecapStudio URL failed: the link was
  stuck to the next word in the message, and a search did not find the repo, so it
  may be private. **A private repo cannot be fetched at all. Paste the text.**
- Raw GitHub content can lag a few minutes after a push.
- Never put API keys or tokens in `COMMS.md`, `LOG.md` or any pushed file.

### Entry format for `COMMS.md`

```
## C-014 | 2026-10-27 | agent -> consultant | BLOCKED | OPEN
Commit: a1b2c3d   Files: cutwright/mlt.py L730-754
Goal: one line.
Tried: numbered, with the exact command or edit each time.
Observed: the real output, trimmed to the lines that matter.
Known / assumed: two short lists, kept apart.
Ask: the one question or decision wanted.
```

Types: `BLOCKED`, `QUESTION`, `REVIEW` (please check this diff or design),
`BREAKTHROUGH` (for the record), `ANSWER`, `INFO`. Status is `OPEN` until the
other side replies, then `ANSWERED`. IDs only go up. Never edit an old entry;
add a new one that refers to it.

### After every breakthrough (agent, always, before anything else)

1. Add a dated entry to `LOG.md`: what changed, what proved it (the check output
   or measurement), what it unblocks.
2. Update the **Current status** block below (phase, last green commit, next step).
3. If a decision or surprise came up, add a `BREAKTHROUGH` entry to `COMMS.md`.
4. Commit with `git commit -F`, then **push**. Nothing was pushed at the
   2026-10-24 pause; unpushed work is invisible to the consultant and lost if the
   session dies.
A step is not finished until its log entry is pushed.

### Current status (agent keeps this block up to date)

```
Phase: 0 (not started)
Last green commit: a87f4bf (2026-10-24, nothing pushed)
Next step: Project.to_xml() crossfade edit, then full build of demo_cross
Open COMMS entries: C-001
```

## Consultant protocol (for when things get hard)

### When the agent must stop and escalate

Write a `BLOCKED` or `QUESTION` entry instead of trying again when any of these is
true:

- The same problem has survived **two** attempts that each changed something.
- A check fails and the cause is not clear from its own output.
- A choice has real trade-offs (licence, dependency, interface shape, whether to
  copy code or reimplement).
- A refactor would touch more than one phase's files.
- A check passed that the agent did not expect to, or failed in a way that does
  not match the theory.
- Credits or context are running low: write the entry *before* stopping.

Stopping early is cheaper than a fifth attempt. When blocked, do these first:
change one variable per attempt, keep the path to the failing artifact, and if the
tree has become confusing, return to the last green commit rather than stack more
edits on it.

### What the consultant does

1. Restates the problem in one line and separates **known** from **assumed**.
2. Gives at most three hypotheses, ranked, each with **one cheap test that
   distinguishes it** (a command, and what output means yes or no).
3. Recommends one next action, the smallest that moves things. Says what not to
   do (for example, "do not re-run the 90-second `luma_window_test.py`").
4. When attempts keep failing, questions the premise: is the goal right, is there a
   simpler shape, is a check measuring the wrong thing?
5. Proposes a stop-loss when a path has cost too much: cut scope, take the
   fallback, or park it with a note.
6. Reviews claims against evidence. "The check passes" needs the check output.
   `not_run` is not a pass.

### What the consultant cannot do

It cannot run melt, Shotcut, git or anything on the owner's machine, and it has no
network inside its sandbox. Every answer is a hypothesis until the agent runs it.
**The agent must post the result back as a new entry**, pass or fail, so the next
reader (the consultant, or a fresh session) is not guessing.

### Style of replies

Short, numbered, the recommended action first. Reasoning after, only as long as it
needs to be.

---

## Decisions so far (owner + consultant, 2026-10-26)

- **Execution agent:** DeepSeek V4 Flash through Cline, on the owner's machine. The
  owner reports it accepts images. **Unverified**: test by sending Cline one frame
  or contact sheet and asking what is in it, before building Phase 2 around vision.
- **Consultant:** Claude in the free web app. No Claude API spend for now.
- **Budget:** start with about $5 of DeepSeek credit and hold the rest. Measure what
  Phase 0 and Phase 1 actually cost, then top up. Check refund terms and minimums
  before paying. Revisit a Claude API balance only if the image test fails.
- **Channel:** `COMMS.md` for agent <-> consultant, `LOG.md` for progress, this file
  for plan and status.
- **Dropped:** `dylanler/AI-auto-narrator`; undo/redo from cli-anything-shotcut.
- **RecapStudio:** the new tree **replaces** `vendor/recapstudio/` (owner decision).
- **Default voice engine:** Edge-TTS, voice `en-US-ChristopherNeural`. The owner reports it
  works, so no test step is planned. Paid engines only with explicit approval and the
  owner's own keys.

## Measured spend so far (DeepSeek usage export, 2026-10-20 to 2026-10-26)

Source: `usage_data_2026-10-20_2026-10-26.zip` from the owner (two CSVs; API key
name `CLINE1`). Remaining balance is not in the export and is unknown.

- **Total $6.00** over five active days (21 to 25 Oct): `deepseek-flash` $3.89,
  `deepseek-v4-pro` $2.11.
- **Heaviest day, 24 Oct: $3.05**, 3,063 requests, 323 M input tokens (98% cache
  hits), 2.15 M output tokens. That is the day of the crossfade work in the
  2026-10-24 handoff.
- **Unit prices in the export, per million tokens.** flash: cache miss $0.15, cache hit
  $0.003, output $0.60. v4-pro: cache miss $0.66, cache hit $0.022, output $1.98.
- **Cost per request:** about $0.001 on flash, $0.007 to $0.010 on v4-pro (7 to 10
  times). v4-pro was 6% of requests but 35% of spend.
- **Where the flash money goes (24 Oct):** output tokens $1.29 (42%), cache-hit input
  $0.96 (31%), cache-miss input $0.80 (26%). Re-sending context is cheap because
  98% of it hits the cache; generating text is the biggest line.

Rules that follow from this:

1. **Default to flash.** Use v4-pro only after a `BLOCKED` entry in `COMMS.md` says a
   problem needs it. The consultant (free) is the first escalation, not v4-pro.
2. **Prefer small targeted edits over rewriting whole files.** Output tokens cost the
   most per token, and rewrites also hit the editor's size limits.
3. **Keep the start of a long task's context stable.** Cache hits depend on a repeated
   prefix; restructuring it forces expensive misses.
4. **Expect $1 to $3 for a heavy flash day.** Phase 0 should cost well under that if it
   does not thrash. The two-failed-attempts escalation rule is also the cost cap.
5. Log each phase's cost in `LOG.md` (from the dashboard export), so the plan's
   estimates get replaced by measurements.

## RecapStudio as of 2026-10-26 (read from the owner's upload `RecapStudio_github.zip`)

Read by the consultant, first pass: README.md, COMIC_RECAP_GUIDE.txt, voices/README.txt,
keys.env.example, config.json, project.json, segments.json, the comic prompt, MENU.bat,
the module and engine lists in `studio.py`, headers of `tts_worker.py` and
`setup_engines.py`. Second pass (owner asked for a deep read): in `recap.py`, the
constants and config defaults, every interactive prompt, `step_subs`, `step_sheets`,
`step_index`, `step_tts` and its manifest logic, `step_say`, `make_edge`, `seg_media`,
`build_items`, `status_lines` / `step_check`, `step_comic`; in `studio.py`, project
creation and the HTTP routes.
**Still not read:** `step_collect` (yt-dlp download flow), the Premiere XML and VideoPad
writers, the comic geometry and camera code (`comic_detect`, `render_comic_clip`), the
other engines' internals, `app.js`. **Nothing was run.** Treat every statement about what
works as "documented", not "tested".

### The copy in `vendor/recapstudio/` is out of date

Same project, much bigger. `recap.py` went from 130 KB to 194 KB (1,434 changed
lines), `studio.py` +214 changed lines, `web/app.js` +482. New files: `README.md`,
`.gitignore`, `COMIC_RECAP_GUIDE.txt`, `_template/1_import_comic.bat`,
`_template/PASTE_THIS_TO_CLAUDE_comic_recap.txt`, `keys.env.example`,
`setup_engines.py`, `tts_worker.py`, `voices/README.txt`. `vendor/MANIFEST.sha256`
describes the old files. Re-vendoring or referencing the new tree is a Phase 3 decision
(see below); either way, record the commit and hashes in `PROVENANCE.md`.

### What is new

**Voices.** Six engines, chosen per project in `config.json` (`tts.engine`) or with
`--engine`:

| engine | runs | cloning | notes |
|---|---|---|---|
| Edge-TTS | online, free | no | several named voices |
| Kokoro | offline, CPU | no | about 350 MB; many US/UK voices |
| Pocket TTS | offline, CPU | yes | English |
| Chatterbox | offline | yes | four variants (nano, turbo, english, multilingual); `[laugh]` style tags; output carries Resemble AI's Perth watermark |
| ElevenLabs | online, paid | - | multi-key support |
| MiniMax | online, paid | - | multi-key support |

- Chatterbox and Pocket run in their **own virtualenvs** (`venvs/`) through
  `tts_worker.py`, which speaks JSON lines over stdin/stdout (`load`, `say`, `quit`),
  so PyTorch cannot break the main tool.
- `setup_engines.py` (standard library only, has `--dry-run`) installs engines and
  models and writes `models/engines.json`. Models and venvs are gitignored and several
  GB.
- Voice cloning uses reference clips in `voices/` (gitignored). Only clone voices
  the owner has the right to use.
- Per-segment `speed` (0.6 to 1.4) for Kokoro, Chatterbox and Pocket.
- `project.json` `tts_mode`: `plain`, `light`, `heavy`, `kokoro`, `chatterbox`/`pocket`
  (these change how the script is written: tags, contractions, segment length under
  about 60 words).
- API keys live in `keys.env` (gitignored; template `keys.env.example`).

**Comic / manga module (`comic_recap`).** Input is `.cbz`, `.cbr`, `.pdf` or a zip of
page images, not a video.
1. `recap.py comic --file <path>` unpacks pages to `pages/pNNN.png`, saves page sizes
   and panels (`pages/panels.json`), and writes review PDFs
   `comic_review/comic_for_claude_partNN_pNNN-pNNN.pdf`: clean pages with a 0.0 to 1.0
   ruler grid and a "PAGE N" header, 30 pages per PDF.
2. **A vision model looks at the PDF and decides the panels**, giving each shot as a box
   `[x0,y0,x1,y1]` in page fractions (config `comic.panel_mode`: `claude` or `auto`).
   Reading direction `rtl` for manga.
3. Segment fields: `page`, `focus` (list of box stops, or `"page"`), `motion` (`auto`,
   `push_in`, `pull_out`, `drift`, `still`, `pan_left/right/up/down`, `shake`),
   `zoom`, `anchor`, `enter`, `caption`, `chapter`, plus the usual `narration`,
   `subtitle`, `speed`.
4. Each clip is cut to its voice-over length; the camera moves over the panels
   (`render_comic_clip`). 16:9 and 9:16 (TikTok) both supported.
- Documented limits: a speech balloon crossing the gutter can merge two panels;
  `.cbr` needs 7-Zip or Windows tar; captions are not burned into the mp4 (use the
  Premiere XML); rendering takes roughly 1x to 2x real time per CPU core.

**Modules now:** `movie_recap`, `show_recap`, `comic_recap`, `nba_minidoc`,
`nba_story`, `real_story`, `ranking`. Each has its own `PASTE_THIS_TO_CLAUDE_<module>.txt`.
`project.json` also has `style` (`retell`, `commentary`, `mixed`), `target_length`,
`platform`, `voice_card`, `fact_check`, `music`, `captions`.

### What this means for the agent integration

- **`recap.py` is already a command-line tool.** Its steps are: `init`, `module`,
  `subs`, `index`, `sheets`, `say`, `comic`, `collect`, `tts`, `review`, `premiere`,
  `videopad`, `video`, `srt`, `tiktok`, `check`, `demo`, `missing`, `collect_one`.
  Useful flags: `--engine`, `--only <ids>`, `--preview`, `--force`, `--yes`,
  `--file`, `--text-file`, `--tts-file`, `--out`. So Phase 3 should **call these steps
  from Cutwright**, not port them. Which steps still stop to ask a human (engine pick,
  guided `collect`) and need non-interactive flags is unknown; the agent must find out.
- **The manual step to remove** is "attach one PDF and paste the prompt into a chat".
  The agent reads the images itself and writes `segments.json`. For comics that means
  up to 30 page images per part: look once, write the panel boxes to a file, and work
  from the file afterwards (see cost control above).
- **Output formats differ.** RecapStudio produces Premiere XML, VideoPad `.vpj`, or a
  finished mp4 via ffmpeg. Cutwright produces Shotcut `.mlt`. A bridge from
  `segments.json` plus the generated audio to a Cutwright plan is new work (Phase 3f).
- **Keys and secrets.** `keys.env` must never be committed, printed into `LOG.md` or
  `COMMS.md`, or pasted to the consultant. Check that Cutwright's `.gitignore` also
  ignores `keys.env`, `voices/`, `models/` and `venvs/`.
- **Licences.** The README says each engine and model has its own licence and to check
  before redistributing audio or models; Chatterbox adds a watermark. Cutwright must
  not bundle models or voices.

### Second-pass findings from `recap.py` (how to drive it from an agent)

1. **Each project folder carries its own copy of `recap.py`.** `studio.py` creates a
   project with `shutil.copytree(_template, Projects/<name>)`, and `recap.py` starts with
   `os.chdir(<its own folder>)`. So the call is `python <project>\recap.py <step>`, and a
   project's copy can go stale when `_template/recap.py` changes (the studio has a
   "refresh engine" route that overwrites it). Cutwright must check which copy it is
   running.
2. **Non-interactive mode exists: `RECAP_NONINTERACTIVE=1`.** It makes `ask_text` and
   `ask_choice` return their defaults and stops `get_keys` from prompting. What it does
   **not** cover: the guided `collect` loop (an `input()` per shot, plus a yes/no on
   failed downloads), and MiniMax's "Enter voice_id" prompt. `tts` needs `--engine <name>`
   and `--yes` to run without questions. Consequence: **do not use `init`** (with the env
   var it only writes defaults). The agent writes `project.json` itself; its fields are
   `module`, `topic`, `style`, `target_length`, `platform`, `tts_mode`, `voice_card`,
   `fact_check`, `music`, `captions`, and `reading` (`ltr`/`rtl`) for comics.
3. **Side effects to expect.** Several steps call `reveal()`, which opens an Explorer
   window on Windows. `step_tts` rewrites `config.json` (it saves the chosen engine).
   `tts --force` deletes every `audio/*.mp3`. `comic --force` deletes the imported pages
   and re-detects panels, **destroying hand edits in `pages/panels.json`**. The agent
   must not pass `--force` without a COMMS entry.
4. **Everything is files by convention.** In: `segments.json`, `project.json`,
   `config.json`, `footage/`, `images/`, `music/`, `subs/`, `keys.env`. Made: `sheets/`,
   `audio/` (plus `audio/_manifest.json`), `audio_preview/`, `clips/` (plus
   `_cache.json`), `gfx/`, `premiere_sequence.xml`, `recap_final.mp4`,
   `recap_subtitles.srt`, `chapters.txt`, `shot_manifest.csv`, `credits.txt`,
   `review_sheet.csv`, `tiktok_out/`, `STATE.md`.
5. **`segments.json` shape:** `{"youtube": [segments], "tiktok": {"part1": [segments]}}`.
   Segment fields found in the code: `id` (required, unique), `narration`, `src_start`,
   `src_end`, `src`, `image`, `need_visual`, `keep_audio`, `subtitle`, `caption`, `rank`,
   `chapter`, `shot`, `speed`, and the comic fields (`page`, `focus`, `panel(s)`,
   `motion`, `zoom`, `anchor`, `enter`, `shake`).
   **Picture lookup order:** `image`, then `src`, then a footage file named after the
   segment id, then an image named after the id, then the one big source video (needs
   `src_start`), else a **slate**.
6. **A missing picture does not fail the build; it renders a slate card** saying why.
   So "the build finished" proves little. Cutwright checks must list slates and fail
   on them. `status_lines` (`check`) already counts "segments without footage".
7. **Voice length drives the picture, not the reverse.** `build_items` fits the audio
   first, then trims the footage or holds the last frame to match, and prints
   "perfect fit", "footage trimmed by Ns" or "last frame held Ns". It warns when a
   rendered clip differs from the voice by more than 1.5 frames. Clips are cached by a
   key of source signature, range, frames, size and fill, so re-runs are incremental.
   TTS is incremental too: `audio/_manifest.json` stores a text hash and an engine
   signature per segment, so only new or edited lines are re-voiced; changing the
   engine or voice triggers a "re-voice the others?" question that `--yes` answers
   yes to.
8. **`check` writes `STATE.md`**, described in the code as "paste this into a new chat to
   resume". It is RecapStudio's own handoff mechanism. The agent should read it before
   acting and run `check` after each step. `check` also reports which tools and Python
   modules are missing (`ffmpeg`, `ffprobe`, `yt-dlp`, `requests`, `edge_tts`, and for
   comics `PIL`, `numpy`, `fitz`).
9. **Overlap with Cutwright, and where Phase 2 plugs in.**
   - RecapStudio's `subs` extracts every text track to `subs/*.srt` (and `.ass`),
     skips picture-based tracks (PGS, DVD: "needs OCR"), picks the English track, and
     for several episodes writes `subs/ALL_EPISODES_for_claude.txt`. It does none of
     Cutwright's validation. **Cutwright's `subs` gate should own subtitle trust**; its
     cleaned transcript is what the agent reads.
   - RecapStudio's sheets: `index` makes up to 8 contact sheets per file (4x4 tiles,
     timestamps burned in, roughly one sheet per five minutes), and `sheets` makes one
     per segment flagged `need_visual`. That is coarse. **Phase 2's shot-boundary
     coverage sheets slot in here** as a better `index`, and the agent's `need_visual`
     flags remain the second route.
   - Picture-based subtitle tracks are an unsolved case (OCR); it is the same gap noted
     under burned-in subtitles in Phase 2b.
10. **`studio.py` is a local web server** (`ThreadingHTTPServer` on 127.0.0.1, with a
    host allow-list) exposing `/api/projects`, `/api/jobs`, `/api/keys`, `/api/tools`,
    `/api/voicelab/say` and others. It is the UI's backend. The agent should use the
    command line, not this server. Never expose its port.
11. **Edge-TTS** needs the `edge_tts` Python module and an internet connection. The
    default voice is `en-US-ChristopherNeural`, rate `+0%`. The owner confirms it works.
    If it ever stops (it depends on an online service), Kokoro is the offline fallback.
12. **API keys:** `load_env` reads `keys.env` from the project folder, `Projects/`, or the
    studio folder, and a `KeyPool` rotates through comma-separated keys. Keys are only
    ever read from the environment; nothing in Cutwright should print them.

## Work plan

### Phase 0: finish the crossfade (already designed, smallest step)

Do "The edit to make" in the section below. Rebuild `projects/demo_cross`, get
`crossfade` and `gui_xfade` green, record the Ctrl+S copy in `PROVENANCE.md`.
**Why first:** it is fully specified, it unblocks Phase 4, and it leaves the repo
in a state where the existing checks mean something.
Done when: all nine checks pass on `demo_cross`; committed.

### Phase 1: read-only reconnaissance (no code, cheapest, prevents waste)

Clone and read: `shotcut-mcp`, `cli-anything-shotcut`, `NarratoAI`,
`altzotify-cell/RecapStudio`. Also compare RecapStudio with the
copy already in `vendor/recapstudio/` (hashes in `vendor/MANIFEST.sha256`).
Produce one file, `BORROW.md`, with for each repo: licence, the exact files and
functions for each item in the borrow list, and anything the owner's notes got wrong.
Done when: `BORROW.md` exists and every borrow-list row is marked *copy shape*,
*copy code*, *reimplement* or *drop*.

### Phase 2: coverage sheets (highest value, cheap, uses what exists)

- Take shot boundaries from the existing ffmpeg shot detection in `frames.py`.
- Take dialogue spans from the gated transcript (`subs.py` / `moments.py`).
- For each boundary with no overlapping cue, make a contact sheet; add a floor of one
  sheet per N minutes (default 3, configurable).
- Tag these in `moments.json` as a new status (for example `silent_unexplained`) so
  the agent knows they need a look. Optional: the spot-check sample from the
  adjustments above.
- Use an interval/batch/concurrency config in the NarratoAI style so large videos
  do not hammer one process.
- Add a `verify` check: every silent shot with no sheet is an error.
Done when: on a test clip with a known silent stretch, the sheet appears, is tagged,
and the check fails if it is removed.

### Phase 2b: footage with no usable transcript (extends Phase 2)

Nothing here is built. The consultant read only the README's description of
`transcribe.py`, not the code; the agent must read it before relying on this.

The agent picks a mode from the result of `subs` (per video first; per stretch once
the versatility target below is in scope), and **says which mode it chose**
in the digest. The existing rule stays: it stops and tells the owner before
switching to a fallback, rather than substituting one quietly.

1. **Speech, no subtitles.** Use the whisper.cpp fallback in `transcribe.py`, gated
   like any transcript. Cautions: `models/ggml-small.en.bin` is English only, so
   other languages need another model (owner to decide); whisper invents text over
   music and silence, so the gate must stay on.
2. **Little or no speech** (silent film, gameplay, music, b-roll): add a
   **visual-only mode**. No transcript. Beats are groups of shots from ffmpeg scene
   detection, ranked by shot-change density and loudness changes (ffmpeg loudness or
   silence detection). Because there is no text to trust, **every** beat gets a
   contact sheet, not only silent ones. `moments.json` gets `source: visual_only`
   and the digest states that no dialogue exists. The agent writes `expected` from
   the sheets, and the existing `verify` grading still applies.
3. **Burned-in subtitles** are pixels, not a text track, so `subs` finds nothing.
   OCR could read them. Not planned; park unless the owner has such footage.

Cost control (applies to Phase 2 and 2b): run all detection in plain code first;
downscale sheets; the agent looks at each sheet once and saves its reading to a
file; later turns read the file, not the image.

Done when: a clip with no subtitles and no speech goes from video to a candidate
moments file with sheets, and a check fails if any beat lacks a sheet; and a clip
with speech but no subtitles goes through whisper and the gate.

### Versatility target: English footage of any kind

Owner decision 2026-10-26: footage is mostly English, and the tool should work
across *kinds* of English footage, not only dialogue-heavy.

**Design rule:** coverage (sheets) is the base layer; a transcript is an optional
signal on top. Decide per *stretch* of a video, not per video. A stretch is
dialogue (transcript trusted), mixed, or no-speech (sheets only). One episode can
contain all three.

| footage type | speech | what carries the meaning | handling |
|---|---|---|---|
| shows, films, anime | yes, subs likely | transcript, plus sheets at silent shots | existing path + Phase 2 |
| commentary-driven (sport, gameplay with voiceover, reviews) | yes | the picture; words describe opinion, not events | transcript is low-trust for "what happened"; sample more sheets |
| narrated documentary | yes | narration and footage together | transcript usually aligned with picture |
| music video, concert | lyrics only | picture and audio energy | whisper transcribes songs poorly; treat as low-trust |
| silent, ambient, b-roll | none | picture | visual-only mode (2b) |
| gameplay without commentary | none | picture, motion | visual-only mode (2b) |
| comics, manga (images, not video) | none | the pages | RecapStudio `comic_recap`; vision model reads ruler-grid PDFs (Phase 3d) |

Commentary-driven footage is the "confident but wrong" case at full scale: the
transcript is fluent and says nothing about what is on screen. Do not trust it for
events without sheets.

**Test matrix (owner supplies the clips; `testclips/` is gitignored):** one short
English clip of each type above. Done when, for every clip, the pipeline chooses a
mode per stretch, produces moments with sheets, and passes its checks, with the
result recorded in `LOG.md`. Build and test on the dialogue clip and the silent clip
first; they are the two extremes.

**Not yet:** genre presets. RecapStudio's existing prompts (`movie_recap`,
`show_recap`, `nba_minidoc`, `nba_story`, `ranking`, `real_story`) become prompt
profiles in Phase 3, after the core modes pass the matrix.

### Phase 3: RecapStudio integration (replaces the paste step)

Depends on Phase 1 (read the new tree properly) and the section "RecapStudio as of
2026-10-26" above. Split so each piece can ship alone:

- **3a. Replace the vendored copy (decided).** Replace `vendor/recapstudio/RecapStudio/`
  with the new tree (60 files, about 0.46 MB; the zip holds no secrets, only
  `keys.env.example`). Regenerate `vendor/MANIFEST.sha256`, update the README's layout
  counts (it says 89 files, 0.68 MB), record the source and hashes in `PROVENANCE.md`,
  and extend `doctor` to report RecapStudio's engines (`models/engines.json`), 7-Zip,
  ffmpeg, and the Python modules `check` lists. Writes stay inside the Cutwright
  folder, so `guard.py` allows this. Commit the replacement on its own, before any
  wrapper code, so it can be reverted cleanly.
- **3b. Wrap the steps.** `python -m cutwright recap <step> --json`, calling the
  project's own `recap.py` as a subprocess (see second-pass findings 1 to 3: set
  `RECAP_NONINTERACTIVE=1`, write `project.json` directly, never `init`, `collect` or
  `--force` unattended). Start with the non-interactive,
  cheap ones: `subs`, `sheets`, `index`, `check`, `missing`, `say --text-file`.
  Every write still goes through `guard.py`.
- **3c. Voice.** Wrap `tts` as `recap.py tts --engine edge --yes` with
  `RECAP_NONINTERACTIVE=1`. Edge-TTS is the default (owner-confirmed working). Use
  `--preview` (first three segments) and `--only <ids>` for cheap re-takes. Checks: an
  audio file exists for every segment with narration, its duration is plausible for the
  word count (about 150 words a minute), loudness is within range (reuse Cutwright's dB
  checks), and `audio/_manifest.json` has no stale entries. Kokoro is the offline
  fallback; Chatterbox and Pocket come later (own virtualenvs, voice cloning); paid
  engines (ElevenLabs, MiniMax) only with explicit approval and the owner's keys.
- **3d. Comic module.** Wrap `comic` (import) and the render. The agent reads the
  review PDFs or page images and writes `segments.json`. Needs `PIL`, `numpy` and `fitz` (check with `recap.py check`). Never `--force` the
  import after hand-editing `pages/panels.json`. Checks: every `page` exists,
  every box lies within 0 to 1, no segment has empty narration, rendered clip length is
  close to its voice length, ids unique and increasing. Needs a test comic from the
  owner (rights are the owner's responsibility).
- **3e. Prompt profiles.** Turn the seven `PASTE_THIS_TO_CLAUDE_<module>.txt` files
  into profiles the agent loads by `project.json` `module`. Do this after the core
  modes pass the versatility matrix.
- **3f. Bridge to Shotcut.** Segments plus audio to a Cutwright `plan.json`, then
  `build` to `.mlt`. Decide first whether comic camera moves stay in RecapStudio's
  ffmpeg render (simplest) or get a native `.mlt` form later (optional).

Done when: an agent, given only a video path (or a comic file) and the CLI, can run
from input to a built project with no human paste step, on both a video and a comic.

### Phase 4: borrow from cli-anything-shotcut

In this order:
1. Volume envelopes and ducking (music under voice). Check: render and measure dB at
   voice and no-voice points; also survive Ctrl+S.
2. Blend modes, opacity, PIP. Check: render a frame and measure.
3. `--json` on every subcommand. Check: parses with `json.loads`.
4. A `SKILL.md` describing the CLI for other agents.
5. Preview bundles. Only if steps 1-4 went smoothly.
Skip: undo/redo.

### Phase 5: borrow from NarratoAI (all optional, default off)

Order by value per credit: keyframe batching (done in Phase 2), subtitle mask,
Sonilo BGM/SFX, Tavily plot search, TwelveLabs, hosted captioners. Each is a config
flag plus a separate module; none may become a hard dependency.

### Phase 6: the milestone chain already in the old handoff

Music dipping (now Phase 4 step 1) -> J/L cuts -> per-line captions -> the planner
(bundle plus JSON-schema validation) -> an end-to-end run on a short clip ->
`REPORT.md`.

## Suggested order against a limited budget

| Step | Cost | Stop here and the repo is... |
|---|---|---|
| Phase 0 | small | consistent and green |
| Phase 1 | small, no code | informed; every later step is cheaper |
| Phase 2 | small-medium | better at perception than before |
| Phase 4 steps 1-3 | medium | able to duck music and overlay |
| Phase 3 | medium-large | agent-driven end to end |
| Phase 5 | optional | extended |

## Open questions for the owner

1. Licence of Cutwright itself? (Decides what can be copied in.)
2. Does an agent calling a CLI with `--json` satisfy "fully integrate", or is an MCP
   server required now?
3. Is `altzotify-cell/cutwright` (and RecapStudio) public? If private, the consultant can only see pasted text.
4. ~~Which execution agent?~~ Answered: DeepSeek V4 Flash via Cline (see Decisions).
5. ~~Footage and language?~~ Answered: mostly English; wants versatility across kinds of English footage (see Versatility target).
6. ~~Replace the vendored RecapStudio?~~ Answered: yes, the new tree replaces it (Phase 3a).
7. ~~Default voice engine?~~ Answered: Edge-TTS; no test needed; paid engines only with approval.
8. Can the owner supply a comic or manga file to test with?

## Session log (what the consultant actually did on 2026-10-26)

- Listed the zip. Read `HANDOFF.md` and the first 120 lines of `README.md`.
- Did **not** read: `LOG.md`, `REPORT.md`, `PROVENANCE.md`, any `.py` file, the
  RecapStudio vendor files, or any GitHub repo.
- Read the uploaded `RecapStudio_github.zip` in two passes (docs and structure, then the
  main parts of `recap.py` and `studio.py`; no code run) and recorded the findings above.
- Wrote this plan. No code, `.mlt` file or project was changed.
- Added the communication and consultant protocols, and `COMMS.md`. A test fetch of the
  RecapStudio URL failed and a search did not find the repo; fetching from GitHub is
  unverified.
- Removed `dylanler/AI-auto-narrator` at the owner's request: it was listed with no
  stated purpose and is not needed.

## Start here (for whichever agent picks this up)

1. Read this section (including the two protocol sections), then "The edit to make" below.
   Open `COMMS.md` and answer C-001.
2. Run `python -m cutwright doctor` and confirm what is present.
3. Do Phase 0. Commit with `git commit -F`.
4. Do Phase 1 and write `BORROW.md` before touching anything else.
5. After every breakthrough: LOG.md entry, update Current status, commit, push.

---

## Previous handoff (2026-10-24, unchanged)


State of the crossfade work at the pause on 2026-10-24, what is proven, what is
left, and how to pick it up. `LOG.md` is the running log, `REPORT.md` describes
the finished projects, `README.md` is the reference; this file is the one to
read first.

**The short version: the dissolve is solved and the answer is written down below.
It is not yet in `Project.to_xml()`.** The code emits the second-best shape, one
that Shotcut keeps but melt mis-times, so `projects\demo_cross` currently fails
its `gui_xfade` check. The next session's first job is a single edit to
`to_xml` (see "The edit to make"), then re-running the build.

## What the problem was

A crossfade that renders in melt did not render in Shotcut. `projects\demo_cross`
read magenta -- the outgoing colour alone -- in Shotcut's preview where melt
rendered a pink mix.

Cause, established by diffing what Shotcut writes on a real Ctrl+S: Shotcut sets
`disable=1` on V1's `frei0r.cairoblend` every time it saves. Every flat
multitrack dissolve -- a `luma` with `a_track=0`, an opacity ramp on the incoming
track -- depends on that blend running. So they all die the moment the project
is opened and saved, silently.

Consequence: the dissolve must not depend on any transition outside itself, and
must not be a multitrack transition at all, because a multitrack transition is
exactly the thing Shotcut reconsiders.

## The shape that works -- in both engines

A `.mlt` fragment, measured rather than guessed (`out\scratch\xfade6_probe.py`):

```xml
<producer id="head" in="0" out="14">          <!-- the incoming clip's first 15 -->
  <property name="length">15</property>
  <property name="eof">pause</property>
  <property name="resource">0xffffffff</property>
  <property name="mlt_service">color</property>
  <property name="mlt_image_format">rgba</property>
  <filter id="fade" in="0" out="14">
    <property name="alpha">0=0;14=1</property>       <!-- ramp, keyed to the
                                                          producer's own frames -->
    <property name="mlt_service">brightness</property>
  </filter>
</producer>
<playlist id="tail"><entry producer="producer1" in="34" out="48"/></playlist>
<playlist id="headpl"><entry producer="head" in="0" out="14"/></playlist>
<tractor id="dissolve1" in="0" out="14">
  <property name="shotcut:transition">lumaMix</property>
  <track producer="tail" hide="audio"/>          <!-- track 0: outgoing tail -->
  <track producer="headpl" hide="audio"/>        <!-- track 1: incoming head -->
  <transition id="inner_blend">
    <property name="a_track">0</property><property name="b_track">1</property>
    <property name="mlt_service">frei0r.cairoblend</property>
    <property name="always_active">1</property>
  </transition>
</tractor>
```

and V1 plays it as one entry between the two clip bodies:

```xml
<entry producer="producer1" in="0" out="33"/>    <!-- outgoing, less its tail -->
<entry producer="dissolve1" in="0" out="14"/>    <!-- the dissolve -->
<entry producer="producer2" in="15" out="33"/>   <!-- incoming, less its head -->
```

Three things make this work, and each of them was measured the hard way:

1. **The blend is inside the tractor.** Shotcut disables blends it finds on the
   multitrack, but it does not reach inside a producer it treats as a
   `lumaMix` transition. Nothing outside can turn this one off.
2. **The ramp is `brightness`'s `alpha`, keyed to the head producer's own
   frames**, not a window on the tractor. `luma` inside a nested tractor ramps
   over a length of its own choosing -- a 15-frame tractor with `in="0"
   out="14"`, with `in="34" out="48"`, with a `progressive=1` marker, and with
   both playlists padded to the parent's length all produced the *same* roughly
   ten-frame ramp in the wrong place (measurements in
   `out\scratch\luma_window_test.py`). An alpha ramp is not position-dependent
   at all: it says "frame 0 transparent, frame 14 opaque" and travels with the
   clip.
3. **Nothing depends on the timeline position of the tractor.** The tractor is
   15 frames long and sits wherever V1 puts it.

### The measurements

| where | frame | measured | wanted |
| --- | --- | --- | --- |
| melt (`x6_alpha_nested.mp4`) | 34 | (214, 0, 234) magenta | magenta |
| melt | 40 | (229, 55, 239) | 43% of the way |
| melt | 48 | (252, 255, 252) white | white |
| Shotcut preview, seek 0.25 | ~17 | (255, 0, 254) | magenta |
| Shotcut preview, seek 0.60 | ~40 | (253, 108, 253) | ~43% of the way |
| Shotcut preview, seek 0.85 | ~58 | (255, 255, 255) | white |

Green climbs 0, 1, 5, 27, 55, 79, 103, 128, 151, 178, 203, 228, 255 across the
window in the render: linear, the full 15 frames, no doubling.

After a real Ctrl+S, Shotcut's copy keeps the head producer's `brightness`
filter with its `alpha` keyframes (it adds `start=1`), the inner `cairoblend`
(it adds `version=0.1`), the tractor, and the three V1 entries. That is the
proof this is the shape the editor understands, rather than one it tolerates.

## What is in the tree right now

| file | state |
| --- | --- |
| `cutwright/mlt.py` | +545 lines. `crossfade()`, `dissolves()`, `v1_body()` rewritten around the nested tractor, `_main_tractor()` helper added, per-track and V1 length checks fixed, colour producers grown to cover the borrowed tail, frame-sample window narrowed. **Emits `luma` inside the tractor -- the shape that must be replaced.** |
| `cutwright/gui.py` | +184 lines. Block and picture detectors, `_picture_mean`, `check_crossfade`, `_powershell(save=...)`. |
| `cutwright/tools/shotcut_window.ps1` | `-Save` switch (`keybd_event` Ctrl+S), seek correction `0.3965`. |
| `cutwright/cli.py` | `crossfade` in the `--checks` help and in the build summary. |
| `projects/demo_cross/` | `plan.json`, plus `demo_cross.mlt`, `checks.json`, `digest.txt` **from an earlier `--checks gui_xfade` run against the flat layout**. `demo_cross.mlt` on disk still has the flat `luma`s, so all four want regenerating by a full build. `check\` is gitignored. |

`projects\demo_cross\checks.json` therefore records a failure that says nothing
about the current code: it is the flat layout, judged by the GUI.

## The edit to make

In `Project.to_xml()`, `cutwright/mlt.py` lines 730-754 -- the dissolve loop.
The spans it emits are right; only how the two sides are joined changes.

1. Instead of the incoming producer itself on the head track, emit a **clone** of
   it under `<dissolve>_in` (copy the element, change `id`, and change nothing
   else -- `length`, `eof`, `resource`, `mlt_image_format`, `shotcut:hash`,
   `shotcut:caption` all have to come along) carrying:
   ```xml
   <filter id="<dissolve>_fade" in="0" out="<frames-1>">
     <property name="alpha">0=0;<frames-1>=1</property>
     <property name="mlt_service">brightness</property>
   </filter>
   ```
   It has to be a clone: a filter on the producer would ramp the clip's own body
   on V1 as well. The side playlist for the head then points at the clone.
2. Replace the `luma` transition with `frei0r.cairoblend`, `a_track=0`,
   `b_track=1`, `always_active=1`, id `<dissolve>_blend`.
3. `check_xml()` (lines ~1124-1185) asserts "exactly one `luma` between tracks 0
   and 1". Change that to assert the inner blend between 0 and 1 *and* the
   `brightness` `alpha` filter on the head, since those are now what the shape
   means. A dissolve missing its ramp would otherwise pass.
4. `crossfade()`'s docstring (lines 443-479) describes the `luma` shape and the
   measurements behind it. Rewrite it -- it is the only prose in the code that
   says why, and it is now wrong.

Then regenerate and rebuild:

```
python -m cutwright build projects\demo_cross\plan.json
```

Expect `crossfade` (melt) and `gui_xfade` (Shotcut's preview) to pass, with the
picture going magenta -> pink -> white across the 15 frames and measuring
roughly 43% at frame 40 of 68. The rest of the checks should be unaffected by
the change; if `lengths` or `xml` complains, the clone or the V1 entries are
wrong.

## Tools for the next session

Everything below is in `out\scratch\` (gitignored, but cheap to rewrite from
this description):

- `xfade6_probe.py` -- builds the proven shape from scratch and prints frame
  colours. The reference; copy from it when editing `to_xml`.
- `luma_window_test.py` -- takes the failing file and rewrites the tractor in
  ten ways (`as_written`, `windowed`, `progressive`, `windowed_progressive`,
  `tractor_progressive`, `sides_progressive`, `timecode_window`,
  `double_window`, `absolute`, `absolute_padded`), printing the ramp for each.
  It is the evidence that `luma` cannot be positioned inside a nested tractor.
  Slow -- about 90 s for all variants -- so start it with `Start-Process ...
  -RedirectStandardOutput` and poll; do not run it in the foreground.
- `shoot.py <project> <fraction>...` -- opens a `.mlt` in Shotcut at a seek
  fraction and prints the mean of the picture block. This is how the GUI was
  measured.
- `rewrite_probe.py <project> <fraction>` -- opens, Ctrl+S, screenshots, then
  dumps what Shotcut wrote back. **Its save runs before the screenshot**, so the
  "Saved" toast covers the frame and the preview reads frame 0; use `shoot.py`
  to photograph and `rewrite_probe.py` only to inspect the rewrite.
- `seek_cal.py` -- the calibration behind `0.3965`: seeks of 0.25 / 0.50 / 0.75
  land on 0.233 / 0.484 / 0.736 of the timeline.

## Gotchas worth keeping

- **Shotcut's seek is about 0.016 short**, measured over three fractions. The
  correction lives in `shotcut_window.ps1`; do not re-derive it per test.
- **Do not write a file with `Set-Content` or `Out-File`** -- a BOM got into
  `mlt.py` that way once and made a clean diff look dirty. Use
  `[IO.File]::WriteAllText($path, $text, (New-Object Text.UTF8Encoding($false)))`.
- **`git commit -m` from PowerShell mangles long messages.** Write the message
  to a file the same way and use `git commit -F`, then confirm with
  `git log -1 --format=%B`.
- **Editor writes over ~6000 characters time out.** Split into chunks of three
  thousand or fewer.
- **`gui_xfade` and `gui` report `not_run`, never pass**, when there is no
  interactive desktop. That is deliberate: a check that cannot be made must not
  look like one that was.
- **A `luma` with no window ramps as if it holds the whole timeline**; that is
  why the first nested attempt looked like an 8-frame-early 2x-speed ramp. It is
  not worth more time -- the alpha ramp sidesteps the question.

## Order of work from here

1. The edit above, then a full build of `projects\demo_cross`, all checks green.
2. A real Ctrl+S of `demo_cross.mlt` and a `shoot.py` either side of the middle,
   recorded in `PROVENANCE.md` beside the other Shotcut-saved copies.
3. `REPORT.md` section for the project, `README.md` check table (nine checks
   now), `LOG.md` entries, `PROVENANCE.md` hashes.
4. Commit and push; tag with a name the user approves (`v0.3.3-xfade` was the
   suggestion, and nothing has been tagged since `v0.3.2`).
5. Then the milestone chain the summary lays out: music dipping under voice ->
   J/L cuts -> per-line captions -> the planner (bundle plus JSON-schema
   validation) -> an end-to-end run on a short clip -> `REPORT.md`.

## Repo state at the pause

Branch `main`, remote `origin https://github.com/altzotify-cell/cutwright.git`.
Last commit before this handoff: `a87f4bf An eighth check, which looks at
Shotcut's own preview`. Nothing pushed, nothing tagged. `shotcut\`, `models\`,
`bin\`, `testclips\`, `out\` and every `projects\*\check\` are gitignored: the
first four are 1.2 GB of other people's binaries and footage, described in
`PROVENANCE.md`.

