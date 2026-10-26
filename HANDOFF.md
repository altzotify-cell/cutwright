# Handoff (short working file)

Updated 2026-10-26. This is the only handoff file to read at the start of a task.
Details live in `HANDOFF_FULL.md`; read it **only by section** (see the end).
Three files talk: this one (status and rules), `LOG.md` (progress), `COMMS.md`
(questions between agent and consultant).

## Current status (agent keeps this block up to date)

```
Phase: 0 (not started)
Last green commit: a87f4bf (2026-10-24, nothing pushed)
Next step: Project.to_xml() crossfade edit, then full build of demo_cross
Open COMMS entries: C-001
Latest recorded cost: $6.00 DeepSeek to date (21-25 Oct); log each phase's cost
```

## What the project is

Cutwright turns a JSON plan into a Shotcut `.mlt` project and runs checks proving the
file does what it claims. Standard library only. Windows / PowerShell. The owner's
goal: let an agent drive the whole recap pipeline (RecapStudio) and edit through
Shotcut's own formats, with Cutwright's checks keeping it honest.

## Rules for every step

1. Every write goes through `cutwright/guard.py`.
2. A feature is done only when a check proves it. Quote the check's output as proof.
   `not_run` is not a pass.
3. Read a repo's LICENSE before copying from it. Record sources in `PROVENANCE.md`.
4. Never commit, print, or paste `keys.env`, API keys, `voices/`, `models/`, `venvs/`.
5. **After every breakthrough:** `LOG.md` entry (what changed, what proved it), update
   the status block above, `COMMS.md` entry if a decision or surprise came up, commit
   with `git commit -F`, **push**. Unpushed work does not exist.
6. **Stop after two failed attempts** at the same problem. Write a `BLOCKED` entry in
   `COMMS.md` (commit hash, files, what you tried, real output, one question) and stop.
7. Small targeted edits, not whole-file rewrites. Writes over ~3,000 characters at a
   time time out in the editor.
8. Windows gotchas: no `Set-Content`/`Out-File` (adds a BOM; use
   `[IO.File]::WriteAllText($p,$t,(New-Object Text.UTF8Encoding($false)))`); `git commit
   -m` mangles long messages (use `-F`, confirm with `git log -1 --format=%B`).
9. Cost: each task re-reads its whole context. When context passes ~60%, or a phase
   ends, update the files and tell the owner to start a new session.

## Decisions already made

- Agent: DeepSeek V4 Flash via Cline (owner says it accepts images; unverified for
  Cline, test with one frame). Consultant: Claude in the free web app.
- New RecapStudio **replaces** `vendor/recapstudio/` (Phase 3a).
- Default voice: Edge-TTS, `en-US-ChristopherNeural`, `--engine edge --yes`. Works; no
  test needed. Paid engines only with the owner's explicit approval.
- Footage is mostly English; the tool should handle any kind of English footage
  (dialogue, commentary, music, silent, gameplay, comics).
- Dropped: `dylanler/AI-auto-narrator`; undo/redo from cli-anything-shotcut.
- Do not borrow transitions or envelopes before the crossfade fix lands: Shotcut sets
  `disable=1` on a flat multitrack blend at every Ctrl+S. Borrowed features must
  survive a real Ctrl+S and pass a check.

## Plan (one line each; details in `HANDOFF_FULL.md`)

| Phase | What | Done when |
|---|---|---|
| 0 | Finish the crossfade in `Project.to_xml()`, `check_xml()`, docstring; rebuild `demo_cross` | all nine checks pass; committed |
| 1 | Read-only recon of `shotcut-mcp`, `cli-anything-shotcut`, `NarratoAI`; licences; write `BORROW.md` | every borrow-list row marked copy shape / copy code / reimplement / drop |
| 2 | Coverage sheets: contact sheets at every shot boundary with no dialogue, plus one per N minutes | test clip with a silent stretch gets a sheet; a check fails if removed |
| 2b | Footage with no usable transcript: whisper fallback; visual-only mode; per-stretch modes; test matrix of six English clips | every clip type handled and checked |
| 3 | RecapStudio integration: 3a replace vendor, 3b wrap steps (`RECAP_NONINTERACTIVE=1`, write `project.json` directly, no `init`/`collect`/`--force` unattended), 3c Edge voice, 3d comics, 3e prompt profiles, 3f bridge to `.mlt` | agent goes from input to built project with no human paste step |
| 4 | Borrow from cli-anything-shotcut: ducking first, then blend/opacity/PIP, `--json`, SKILL.md | each passes a check and a real Ctrl+S |
| 5 | Optional NarratoAI borrows (all off by default) | each is a config flag + separate module |
| 6 | Old milestones: J/L cuts, captions, planner, end-to-end run, `REPORT.md` | `REPORT.md` written |

Order: 0, 1, 2, 4 (ducking), 3, then the rest.

## Open questions for the owner

1. Licence of Cutwright itself? (Decides what can be copied in.)
2. Is an agent calling a CLI with `--json` enough for "fully integrate", or is an MCP
   server needed?
3. Is `altzotify-cell/cutwright` public? If private, the consultant sees pasted text only.
4. Can the owner supply a comic or manga file, and the six test clips?

## Where the detail is (`HANDOFF_FULL.md`)

Run `grep -n "^## \|^### " HANDOFF_FULL.md` and read only the lines you need:
"The shape that works" and "The edit to make" (Phase 0); "Second-pass findings from
`recap.py`" (how to drive RecapStudio); "Work plan" (full phase details);
"Versatility target"; "Communication protocol" (COMMS entry format); "Consultant
protocol" (when to escalate); "Measured spend" (cost rules); "Gotchas worth keeping".
