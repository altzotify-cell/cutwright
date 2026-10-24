RECAP STUDIO v2 - project folder
================================
Module types: movie_recap, show_recap, nba_minidoc, nba_story, real_story, ranking.
Chosen when you create the project (settings are in project.json; menu item 17 changes them).
Recaps can end as a finished mp4 OR a Premiere XML. Everything else is a ROUGH CUT for Premiere.

QUICK START
  Recap modules : drop the film/episodes in this folder (one film) or in footage\ (many files),
                  1 Extract subtitles -> give the .srt to Claude (PASTE_THIS_TO_CLAUDE.txt)
  Other modules : give Claude the topic, it returns segments.json with "shot" info,
                  13 Collect footage (paste links / drag files) - missing shots become slates
  Then          : paste Claude's JSON into segments.json
                  2  Contact sheets (need_visual) -> Claude finalises
                  15 Export narration sheet -> check/edit text and tags -> 16 Import
                  14 Preview voice (3 segments) -> 3 Generate voice-over
                  4  Build Premiere XML   (or 5 finished video for recaps)

FOLDERS
  footage\   source clips / episodes (collect saves <segment id>.mp4 here)
  images\    stills; music\  tracks for the music bed
  clips\ gfx\ audio_trim\  generated - don't move/rename after importing into Premiere

SEGMENT FIELDS (all optional except id/narration; see PASTE_THIS_TO_CLAUDE.txt)
  src, src_start, src_end, image, caption, keep_audio, rank, chapter, shot, need_visual, subtitle
  Where a segment's picture comes from, in order: image -> src -> footage\<id>.* -> images\<id>.* ->
  the one big video in this folder (needs src_start) -> a SLATE card (missing shot).

PREMIERE OUTPUT (premiere_sequence.xml)
  V1 footage / stills / slates     V2 number + caption graphics (transparent .mov in gfx\)
  A1 voice-over   A2 original sound (only segments with keep_audio)   A3 music bed (music on + file in music\)
  Sequence markers: chapters and MISSING shots.  Also written: recap_subtitles.srt (captions from your
  narration text), recap_onscreen.srt (backup for number/caption text), chapters.txt, shot_manifest.csv.
  Import recap_subtitles.srt AFTER the XML sequence is open (Import, drag onto the timeline).

VIDEOPAD OUTPUT (videopad_project.vpj)   menu 19 / 4d_build_videopad_project.bat
  Same timeline as the Premiere XML, written in VideoPad's own project format. Open it with File > Open Project.
  VideoPad warns "The provided file may be damaged" - that is expected: click Try Load (it can appear twice).
  Tracks: V1 footage, V2 number + caption graphics, A1 voice-over, A2 original sound, A3 music bed.
  NOT carried over: chapter / missing-shot markers (see chapters.txt and shot_manifest.csv).
  If VideoPad will not open the full project: menu 20 / 4e_build_videopad_project_simple.bat writes a V1 + A1
  version (picture and voice muxed into one file per segment in clips_av\) - no graphics, original sound or music.
  The project stores file paths, not media: keep clips\, clips_av\, gfx\ and audio_trim\ where they are.

FOOTAGE FITTING
  Every clip is cut to EXACTLY its voice-over length (longer footage: end cut off; shorter: last frame held).
  Different shape (4:3 old games, vertical) -> config.json "fill": "pad" (black bars) or "blur" (blurred fill).
  Stills get a slow zoom. Original sound is off unless the segment has "keep_audio": true (or 0-1 volume).

VOICE
  tts_mode in project.json: plain | light | heavy. Tags ([excited] etc.) are sent ONLY to ElevenLabs v3 and
  only in light/heavy; Edge/MiniMax and other models always get plain text (tags would be read aloud).
  Names respelled for pronunciation: put the real spelling in "subtitle".
  Re-voicing: edit the text (or voice/engine) and run Generate voice again - only changed segments are redone
  (audio\_manifest.json remembers). "--only" ids or menu 8/9 for forced redo.
  ElevenLabs model/stability: config.json -> tts.elevenlabs_model (eleven_v3), elevenlabs_stability (0 / 0.5 / 1).
  Several keys: use a premade voice (exists on every key). The tool checks it on all keys and logs retries
  and key switches in audio\_retries.log.
  After voicing you get: "target 8:00, actual 9:12, over by 1:12" + the longest segments.

COLLECT (menu 13)
  Shows each missing shot, opens search tabs, then accepts a link with optional range:
      https://youtube.com/watch?v=... 1:42-1:51     (downloads ONLY that part, via yt-dlp)
  or a dragged video/image file. Enter = skip; run again to resume. Long full-video downloads get a
  contact sheet so Claude can give exact timestamps. Source URLs are kept in credits.txt.
  Note: downloading may breach some sites' terms; heavy use of copyrighted clips with thin
  commentary can get claims.

STATE.md is rewritten after every step - paste it into a new Claude chat to resume.
Demo (menu 18) creates synthetic media in a FRESH project to test the pipeline and Premiere import.
