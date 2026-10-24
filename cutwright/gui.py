"""The check that reads Shotcut's own preview instead of asking melt.

Why this module exists. `melt` is the renderer and Shotcut is the editor, and
for one release they disagreed: a title that melt drew on every frame the plan
asked for was buried under V1 in Shotcut's window. Every check in mlt.py passed
while the thing the user actually looks at was wrong, because every check in
mlt.py asked melt. melt is not the witness for "what does the editor show".

So this asks the editor. A probe project is written by the same Project class
that writes the real one -- a solid colour clip with one title over it -- and
opened in a throwaway Shotcut by tools/shotcut_window.ps1, which photographs the
window and closes itself. The title probe types, clicks nothing and seeks
nowhere: the probe's title starts on frame 0, which is the frame Shotcut paints
on load, so the measurement does not depend on a pointer landing in the right
place.

The dissolve probe is the exception, because a dissolve is only visible in the
middle of one. It clicks Shotcut's own scrub bar to a fraction of the probe and
photographs there -- once in the middle of the dissolve and once past it, since
a single photograph cannot tell a missing dissolve from a playhead that never
moved.

The probe's colour is the ruler. Shotcut scales the 1080x1920 frame down into a
~166-pixel-wide preview, so the picture is found as the largest connected block
of that colour in the screenshot and the title as the white pixels inside it.
The band the title was asked for is a percentage of the frame, so it is a
percentage of that block, and the two can be compared without knowing where the
window sits, how big the display is, or what DPI it runs at.

The control is the same file with the two `dynamictext` filters left out: same
producer, same track, same everything. White pixels inside the picture are then
the title and nothing else. A title Shotcut does not draw reads zero; one drawn
in the wrong band reads a centre outside the band.
"""
import json
import os
import subprocess

from . import guard
from . import mlt
from . import probe

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools",
                      "shotcut_window.ps1")

# MLT colour literals are 0xRRGGBBAA. This one is opaque magenta, which does not
# occur anywhere in Shotcut's chrome -- a grey probe is indistinguishable from
# the panel background, and 0x808080 is not even grey.
PROBE_COLOUR = "0xff00ffff"
PROBE_FRAMES = 45          # 1.5 s at 29.97, enough for a still and a filter window
PROBE_MIN_WHITE = 40       # pixels of white inside the picture that count as text
WHITE = 205                # per channel; the outline keeps the text crisp at any scale
BAND_SLACK = 0.06          # how far outside the band the text centre may sit


def _powershell(project_path, png, timeout, seek=None, save=False):
    """Run the window script once. Returns its JSON, or a failure to report.

    `seek` is a fraction of the project: the script clicks the player's scrub
    bar there before photographing. Only pass it when the frame matters; on
    load Shotcut shows frame 0, which is what most probes want. `save` presses
    Ctrl+S first, so the file on disk is replaced by Shotcut's own copy of the
    timeline -- the only way to see what the editor made of what it was given.
    """
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
           "-File", SCRIPT, "-Project", project_path, "-Out", png,
           "-TimeoutSeconds", str(int(timeout))]
    if seek is not None:
        cmd += ["-SeekFraction", "%.3f" % float(seek)]
    if save:
        cmd += ["-Save"]
    try:
        done = subprocess.run(cmd, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                              timeout=timeout + 60)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "the window script did not return in %d s"
                                      % (timeout + 60)}
    text = (done.stdout or b"").decode("utf-8", "replace").strip()
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    tail = (done.stderr or b"").decode("utf-8", "replace").strip().splitlines()
    return {"ok": False, "error": "the window script printed nothing usable: %s"
                                  % (tail[-1][:200] if tail else "<no output>")}


def _decode(png):
    """width, height and raw rgb24 of a PNG, decoded by the ffmpeg we already use."""
    size = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                           "-show_entries", "stream=width,height", "-of", "csv=p=0",
                           png], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          stdin=subprocess.DEVNULL)
    dims = size.stdout.decode().strip().split(",")
    if len(dims) < 2:
        raise ValueError("cannot read the size of %s" % png)
    width, height = int(dims[0]), int(dims[1])
    raw = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", png,
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL).stdout
    if len(raw) < width * height * 3:
        raise ValueError("ffmpeg decoded %d bytes of a %dx%d picture"
                         % (len(raw), width, height))
    return width, height, raw


def _bbox(points):
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _block(width, height, raw, matches, step=2):
    """The largest connected block of pixels `matches` accepts, as a bounding box.

    Connected, not just "all of it": the timeline thumbnail is the same colour
    as the preview, and a box around both would be the whole window.
    """
    seen, best = set(), []

    def found(x, y):
        return matches(raw, (y * width + x) * 3)

    for y in range(0, height, step):
        for x in range(0, width, step):
            if (x, y) in seen or not found(x, y):
                continue
            block, stack = [], [(x, y)]
            seen.add((x, y))
            while stack:
                cx, cy = stack.pop()
                block.append((cx, cy))
                for nx, ny in ((cx - step, cy), (cx + step, cy),
                               (cx, cy - step), (cx, cy + step)):
                    if (0 <= nx < width and 0 <= ny < height
                            and (nx, ny) not in seen and found(nx, ny)):
                        seen.add((nx, ny))
                        stack.append((nx, ny))
            if len(block) > len(best):
                best = block
    return _bbox(best)


def _magenta_block(width, height, raw, step=2):
    """The largest connected block of the probe colour."""
    def matches(pixels, i):
        return pixels[i] > 140 and pixels[i + 2] > 140 and pixels[i + 1] < 110
    return _block(width, height, raw, matches, step)


def _picture_block(width, height, raw, aspect=None, slack=0.35, step=2):
    """The largest bright block, if it is shaped like the picture.

    Used where the picture is not one known colour: a dissolve runs magenta ->
    pink -> white, and pink is neither of the ends. Brightness separates every
    one of those from Shotcut's chrome (panels sit near 33/255); the aspect
    check separates them from bright things that are not the picture, and says
    so instead of measuring the title bar.
    """
    def lit(pixels, i):
        return (pixels[i] + pixels[i + 1] + pixels[i + 2]) / 3.0 > 60
    rect = _block(width, height, raw, lit, step)
    if not rect:
        return None
    if aspect:
        w, h = rect[2] - rect[0], rect[3] - rect[1]
        if h <= 0 or not (1 - slack) <= (w / float(h)) / aspect <= (1 + slack):
            return None
    return rect

def _white_inside(width, height, raw, rect, inset=3):
    """White pixels inside the picture, and their bounding box.

    The `inset` keeps the picture's own edge -- where a border or a half-covered
    pixel lives -- from being read as text.
    """
    x0, y0, x1, y1 = rect
    found = []
    for y in range(max(y0 + inset, 0), min(y1 - inset, height - 1) + 1):
        row = y * width * 3
        for x in range(max(x0 + inset, 0), min(x1 - inset, width - 1) + 1):
            i = row + x * 3
            if raw[i] > WHITE and raw[i + 1] > WHITE and raw[i + 2] > WHITE:
                found.append((x, y))
    return found


def _measure(png):
    """Picture rect, white pixels, and where their centre sits inside the rect."""
    width, height, raw = _decode(png)
    rect = _magenta_block(width, height, raw)
    if not rect:
        return {"rect": None, "white": 0, "white_bbox": None, "band": None,
                "size": (width, height)}
    white = _white_inside(width, height, raw, rect)
    box = _bbox(white)
    band = None
    if box and rect[3] > rect[1]:
        band = ((box[1] + box[3]) / 2.0 - rect[1]) / float(rect[3] - rect[1])
    return {"rect": rect, "white": len(white), "white_bbox": box, "band": band,
            "size": (width, height)}


def _probe(project, work_dir, title):
    """Two projects: a colour clip with the title on frame 0, and without it."""
    made = {}
    for wanted in (True, False):
        name = "%s_gui%s" % (project.name, "" if wanted else "_plain")
        probe_project = mlt.Project(
            name, project.profile, project.shotcut, project.mlt,
            "GUI probe: %s" % ("the title on frame 0" if wanted else "no title"))
        probe_project.add_colour(PROBE_COLOUR, PROBE_FRAMES, "probe colour")
        probe_project.add_title(str(title["text"])[:16], 0.0,
                                probe_project.profile.seconds(PROBE_FRAMES - 1),
                                title["size"], title["position"])
        probe_project.no_title_text = not wanted
        made[wanted] = probe_project.write(os.path.join(work_dir, name + ".mlt"))
    return made[True], made[False]


def check(project, work_dir, timeout=120):
    """Open the probe in Shotcut, photograph it, and read the title back."""
    name = "gui"
    if not project.has_titles:
        return {"name": name, "ok": False, "ran": False,
                "detail": "the plan has no titles, so Shotcut has no title to "
                          "show here"}

    guard.ensure_dir(work_dir)
    title = project.titles[0]
    band = mlt.TITLE_BANDS[title["position"]]
    low = float(band[1].rstrip("%")) / 100.0
    high = low + float(band[3].rstrip("%")) / 100.0

    try:
        planned, plain = _probe(project, work_dir, title)
    except (mlt.PlanError, OSError) as exc:
        return {"name": name, "ok": False,
                "detail": "could not write the probe: %s" % exc}

    planned_png = os.path.join(work_dir, "gui_shotcut.png")
    plain_png = os.path.join(work_dir, "gui_shotcut_plain.png")
    shot = _powershell(planned, planned_png, timeout)
    if not shot.get("ok"):
        return {"name": name, "ok": False, "ran": False,
                "detail": "Shotcut's window could not be photographed: %s"
                          % shot.get("error", "no reason given")}
    control = _powershell(plain, plain_png, timeout)

    try:
        seen = _measure(planned_png)
    except (ValueError, OSError) as exc:
        return {"name": name, "ok": False, "ran": True,
                "detail": "could not read the screenshot: %s" % exc}
    if not seen["rect"]:
        return {"name": name, "ok": False, "ran": True,
                "detail": "Shotcut opened the probe but the picture is not in the "
                          "screenshot: no %s pixels anywhere in the %dx%d window"
                          % (PROBE_COLOUR, seen["size"][0], seen["size"][1]),
                "png": planned_png,
                "control_png": plain_png if control.get("ok") else None}

    problems = []
    if seen["white"] < PROBE_MIN_WHITE:
        problems.append("Shotcut drew %d white pixels inside the picture at frame 0: "
                        "the title is in the file and not on the screen"
                        % seen["white"])
    elif seen["band"] is None or not (low - BAND_SLACK <= seen["band"] <= high + BAND_SLACK):
        problems.append("Shotcut drew the title at %.3f of the picture's height, not "
                        "in the %s band (%.2f-%.2f)"
                        % (seen["band"] if seen["band"] is not None else -1,
                           title["position"], low, high))

    control_white = None
    if control.get("ok"):
        try:
            without = _measure(plain_png)
        except (ValueError, OSError):
            without = None
        if without and without["rect"]:
            control_white = without["white"]
            if without["white"] > max(20, seen["white"] // 5):
                problems.append(
                    "the same file without the text shows %d white pixels inside "
                    "the picture: this is not reading the title" % without["white"])

    detail = ("Shotcut's own preview, frame 0: %d white pixels inside the %dx%d "
              "picture, centred %.3f of its height (the %s band is %.2f-%.2f); the "
              "same file without the text has %s"
              % (seen["white"], seen["rect"][2] - seen["rect"][0],
                 seen["rect"][3] - seen["rect"][1],
                 seen["band"] if seen["band"] is not None else -1,
                 title["position"], low, high,
                 "not been photographed" if control_white is None
                 else "%d white pixels there" % control_white))
    return {"name": name, "ok": not problems, "ran": True,
            "detail": detail if not problems else "; ".join(problems) + " [" + detail + "]",
            "samples": [{"what": "shotcut preview at frame 0",
                         "rect": seen["rect"], "white": seen["white"],
                         "band": seen["band"], "control_white": control_white}],
            "png": planned_png,
            "control_png": plain_png if control.get("ok") else None,
            "seconds": round(sum(float(s.get("seconds") or 0)
                                 for s in (shot, control)), 1)}


def _picture_mean(png, aspect):
    """The picture rectangle and its mean rgb, or None and the window's size."""
    width, height, raw = _decode(png)
    rect = _picture_block(width, height, raw, aspect=aspect)
    if not rect:
        return None, None, (width, height)
    # An inset keeps the picture's edge -- a border, a half-covered pixel, the
    # letterbox -- from being counted as the picture.
    space = max(4, int(min(rect[2] - rect[0], rect[3] - rect[1]) * 0.12))
    x0, y0 = rect[0] + space, rect[1] + space
    x1, y1 = rect[2] - space, rect[3] - space
    total, count = [0, 0, 0], 0
    for y in range(max(y0, 0), min(y1, height - 1) + 1):
        row = y * width * 3
        for x in range(max(x0, 0), min(x1, width - 1) + 1):
            i = row + x * 3
            total[0] += raw[i]
            total[1] += raw[i + 1]
            total[2] += raw[i + 2]
            count += 1
    if not count:
        return None, None, (width, height)
    return rect, tuple(t // count for t in total), (width, height)


def check_crossfade(project, work_dir, timeout=120):
    """The dissolve, as Shotcut's own preview draws it, at two playhead positions.

    melt renders the file; the editor re-reads it and builds its own timeline
    from what it understands, which is how the titles were once lost. So the
    dissolve gets the same treatment: a probe of two solid colours, opened in
    Shotcut, the playhead clicked to the middle of the dissolve and to the far
    side of it, and the colour of the picture read back.

    Two photographs, because one cannot tell "the dissolve is missing" from "the
    playhead never moved". The far side has to be the incoming colour; if it is
    not, nothing here is about the dissolve, and the check says that instead of
    blaming the blend.
    """
    name = "gui_xfade"
    frames = project.transition
    if not project.has_crossfade:
        return {"name": name, "ok": False, "ran": False,
                "detail": "the plan asks for no crossfades, so Shotcut has no "
                          "dissolve to show here"}

    guard.ensure_dir(work_dir)
    run = max(frames * 2 + 4, 24)
    probe_project = mlt.crossfade_probe("%s_gui_xfade" % project.name,
                                        project.profile, project.shotcut,
                                        project.mlt, frames)
    try:
        path = probe_project.write(os.path.join(work_dir,
                                                "%s_gui_xfade.mlt" % project.name))
    except (mlt.PlanError, OSError) as exc:
        return {"name": name, "ok": False, "ran": False,
                "detail": "could not write the probe: %s" % exc}

    # Where the two frames of interest sit on the scrub bar, as fractions of the
    # probe's own length: the middle of the dissolve, and well past it.
    fractions = {"middle": (run + frames // 2) / float(2 * run - 1), "past": 0.9}
    aspect = project.profile.width / float(project.profile.height)

    shots, means = {}, {}
    for label in ("middle", "past"):
        png = os.path.join(work_dir, "%s_gui_xfade_%s.png" % (project.name, label))
        out = _powershell(path, png, timeout, seek=fractions[label])
        if not out.get("ok"):
            return {"name": name, "ok": False, "ran": False,
                    "detail": "Shotcut's window could not be photographed: %s"
                              % out.get("error", "no reason given")}
        try:
            rect, mean, size = _picture_mean(png, aspect)
        except (ValueError, OSError) as exc:
            return {"name": name, "ok": False, "ran": True,
                    "detail": "could not read the screenshot: %s" % exc}
        if not rect:
            return {"name": name, "ok": False, "ran": True,
                    "detail": "the picture is not in the %dx%d window at %.2f of "
                              "the probe: no bright %s-shaped block anywhere in it"
                              % (size[0], size[1], fractions[label],
                                 "portrait" if aspect < 1 else "landscape"),
                    "png": png}
        shots[label] = png
        means[label] = mean

    # Green is the channel the two probe colours disagree about: magenta 0,
    # white 255. Both are bright, so brightness alone cannot tell them apart.
    mixed, far = means["middle"][1], means["past"][1]
    problems = []
    if far < 225:
        problems.append(
            "at %.0f%% of the probe, past the dissolve, the picture measures "
            "green %d -- not the incoming colour, so the playhead did not go "
            "where it was sent and nothing here is about the dissolve"
            % (100 * fractions["past"], far))
    elif mixed <= 12:
        problems.append(
            "at the middle of the dissolve the picture measures green %d: "
            "Shotcut is showing the outgoing colour alone, with no ramp at all"
            % mixed)
    elif mixed >= 240:
        problems.append(
            "at the middle of the dissolve the picture measures green %d: "
            "Shotcut is showing the incoming colour already, with no ramp"
            % mixed)

    detail = ("Shotcut's own preview: green %d at the middle of the %d-frame "
              "dissolve (magenta 0, white 255), %d past it"
              % (mixed, frames, far))
    samples = [{"what": label, "mean": list(means[label]),
                "fraction": round(fractions[label], 3)}
               for label in ("middle", "past")]
    if problems:
        return {"name": name, "ok": False, "ran": True,
                "detail": "; ".join(problems) + " [" + detail + "]",
                "samples": samples, "png": shots["middle"]}
    return {"name": name, "ok": True, "ran": True, "detail": detail,
            "samples": samples, "png": shots["middle"], "past_png": shots["past"]}

