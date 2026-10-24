"""Shotcut project writer: a plan -> .mlt, then proof the file says what it claims.

melt.exe can serialize a working MLT document by itself, and that is not what
this module does. melt's serializer knows nothing about Shotcut's timeline
conventions: the `shotcut` flag on the tractor, the colour producer every
timeline carries underneath, playlists named V1/A1 tagged `shotcut:video` /
`shotcut:audio`, and the per-track mix/blend transitions that make a stack of
tracks composite and sum instead of the top track simply winning. Those
conventions are what make the file open as an editable timeline rather than a
flattened render, so the XML is written here -- but every service name in it is
asked of the installed Shotcut rather than assumed (see query()).

The checks at the bottom are the point of the module. A .mlt that opens is
not the same as a .mlt that edits correctly:

  1. xml      it parses, ids are unique, every reference resolves, and the
              Shotcut/MLT version it records is the installed one
  2. effects  every mlt_service is a name melt.exe itself reports
  3. lengths  every track's frames add up to the tractor's length
  4. render   a small, deliberately ugly render really shows the source frames
              the edit claims -- compared by PSNR against the source, with a
              deliberate mismatch as a control so a passing score means
              something
  5. fade     the head and tail really are dark and the middle is not, frame
              by frame, against the same timeline with the fade taken out
  6. titles   the text is on screen, inside the band the plan named, on the
              frames it was given and no others, against the same timeline
              with the titles taken out

Frame counts are integers everywhere; no timecode strings, no floats in the
XML. "00:00:09.500" is a rounding argument waiting to happen, and the length
check has to be exact to be worth running.
"""
import ctypes
import fractions
import os
import re
import subprocess
import time
import xml.etree.ElementTree as ET

from . import VERSION as CUTWRIGHT_VERSION
from . import guard
from . import probe

MELT = os.path.join(guard.ROOT, "shotcut", "Shotcut", "melt.exe")
SHOTCUT_EXE = os.path.join(guard.ROOT, "shotcut", "Shotcut", "shotcut.exe")

# Used only when the exe cannot be asked (non-Windows, stripped resource).
FALLBACK_SHOTCUT = "26.9.27"

_QUERY_CACHE = {}
CACHE_DIR = os.path.join(guard.OUT, "cache")


class PlanError(ValueError):
    """The plan asks for something that cannot be built or checked."""


def _melt_stamp():
    """Identity of the installed melt: size + mtime of the exe it lives in."""
    try:
        st = os.stat(MELT)
        return "%d-%d" % (st.st_size, int(st.st_mtime))
    except OSError:
        return "?"


# ---------------------------------------------------------------------------
# ask the renderer, never the folder name
# ---------------------------------------------------------------------------
def query(kind, refresh=False, timeout=180):
    """melt's own list of `filters`, `transitions` or `producers`.

    Cached twice: per process because loading 674 plugins takes seconds, and on
    disk keyed by the exe's size and mtime so a second run does not pay for it
    again. A different melt.exe invalidates the cache by itself.
    """
    if not refresh and kind in _QUERY_CACHE:
        return _QUERY_CACHE[kind]
    if not os.path.isfile(MELT):
        return []
    cache_path = os.path.join(CACHE_DIR, "melt-%s.json" % kind)
    stamp = _melt_stamp()
    if not refresh:
        hit = guard.read_json(cache_path)
        if isinstance(hit, dict) and hit.get("stamp") == stamp:
            names = hit.get("names") or []
            if names:
                _QUERY_CACHE[kind] = names
                return names

    r = probe.run([MELT, "-query", kind], timeout=timeout)
    names = []
    for line in ((r.stdout or "") + "\n" + (r.stderr or "")).splitlines():
        line = line.strip()
        if line.startswith("- "):
            name = line[2:].strip()
            if name and name not in names:
                names.append(name)
    if not names:
        return []
    _QUERY_CACHE[kind] = names
    try:
        guard.write_json(cache_path, {"stamp": stamp, "kind": kind,
                                      "melt": melt_version(), "names": names})
    except (guard.GuardError, OSError):
        pass                      # a cache that cannot be written is not fatal
    return names


def melt_version():
    """-> "7.41.0" or None. Ask the binary; a folder name proves nothing."""
    if not os.path.isfile(MELT):
        return None
    try:
        r = subprocess.run([MELT, "--version"], capture_output=True, text=True,
                           timeout=20, errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"melt\.exe\s+(\d+\.\d+\.\d+)",
                  (r.stdout or "") + (r.stderr or ""))
    return m.group(1) if m else "?"


def _pe_product_version(path):
    """Product version out of the exe's own resource, via ctypes (stdlib).

    Shotcut's version is not in its filename and melt.exe knows only MLT's
    version. The version resource is the one place the app states it about
    itself, so read it there instead of trusting a constant in this file.
    """
    if os.name != "nt" or not os.path.isfile(path):
        return None
    try:
        from ctypes import wintypes
        v = ctypes.WinDLL("version")
        v.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR,
                                              ctypes.POINTER(wintypes.DWORD)]
        v.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        v.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                          wintypes.DWORD, ctypes.c_void_p]
        v.GetFileVersionInfoW.restype = wintypes.BOOL
        v.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                     ctypes.POINTER(ctypes.c_void_p),
                                     ctypes.POINTER(wintypes.UINT)]
        v.VerQueryValueW.restype = wintypes.BOOL

        size = v.GetFileVersionInfoSizeW(path, None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not v.GetFileVersionInfoW(path, 0, size, buf):
            return None
        block = ctypes.c_void_p()
        length = wintypes.UINT()
        if not v.VerQueryValueW(buf, "\\", ctypes.byref(block),
                                ctypes.byref(length)):
            return None

        class FixedFileInfo(ctypes.Structure):
            _fields_ = [("signature", wintypes.DWORD),
                        ("struc_version", wintypes.DWORD),
                        ("file_version_ms", wintypes.DWORD),
                        ("file_version_ls", wintypes.DWORD),
                        ("product_version_ms", wintypes.DWORD),
                        ("product_version_ls", wintypes.DWORD),
                        ("flags_mask", wintypes.DWORD),
                        ("flags", wintypes.DWORD),
                        ("os", wintypes.DWORD),
                        ("file_type", wintypes.DWORD),
                        ("subtype", wintypes.DWORD),
                        ("date_ms", wintypes.DWORD),
                        ("date_ls", wintypes.DWORD)]

        info = ctypes.cast(block, ctypes.POINTER(FixedFileInfo)).contents
        parts = [info.product_version_ms >> 16, info.product_version_ms & 0xFFFF,
                 info.product_version_ls >> 16, info.product_version_ls & 0xFFFF]
        while len(parts) > 3 and parts[-1] == 0:
            parts.pop()
        return ".".join(str(p) for p in parts)
    except Exception:               # no version.dll, no resource, no luck
        return None


def shotcut_version():
    """-> the version string written into every project, e.g. "26.9.27"."""
    return _pe_product_version(SHOTCUT_EXE) or FALLBACK_SHOTCUT


# ---------------------------------------------------------------------------
# profile: exact frame rates, kept as rationals
# ---------------------------------------------------------------------------
def _ratio(raw, default=(1, 1)):
    """'30000/1001' or '1:1' -> (num, den). Anything unusable -> default."""
    try:
        num, den = (raw or "").replace(":", "/").split("/")
        num, den = int(num), int(den)
        if num > 0 and den > 0:
            return num, den
    except (ValueError, AttributeError):
        pass
    return default


class Profile(object):
    """Frame size + frame rate as a rational + the display aspect they imply."""

    def __init__(self, width, height, fps_num, fps_den, sar_num=1, sar_den=1,
                 colorspace="709", description=""):
        self.width, self.height = int(width), int(height)
        self.fps_num, self.fps_den = int(fps_num), int(fps_den)
        self.sar_num, self.sar_den = int(sar_num), int(sar_den)
        self.colorspace = str(colorspace)
        self.description = description or "%dx%d" % (self.width, self.height)

    @property
    def fps(self):
        return self.fps_num / float(self.fps_den)

    def frame(self, seconds):
        """Seconds -> frame index. Integer in, integer out, no fractions."""
        return int(float(seconds) * self.fps + 0.5)

    def seconds(self, frames):
        return round(frames / self.fps, 3)

    @property
    def display_aspect(self):
        f = fractions.Fraction(self.width * self.sar_num,
                               self.height * self.sar_den)
        return f.numerator, f.denominator

    def attrs(self):
        dan, dad = self.display_aspect
        return {"description": self.description,
                "width": str(self.width), "height": str(self.height),
                "progressive": "1",
                "sample_aspect_num": str(self.sar_num),
                "sample_aspect_den": str(self.sar_den),
                "display_aspect_num": str(dan),
                "display_aspect_den": str(dad),
                "frame_rate_num": str(self.fps_num),
                "frame_rate_den": str(self.fps_den),
                "colorspace": self.colorspace}

    def write_file(self, path):
        """Write this profile as an MLT .prof file, and return the path.

        melt needs to be told the profile on its own command line. It applies
        the <profile> element in the .mlt to the producers, but filters and the
        consumer run on melt's default -- 25 fps -- unless -profile is given.
        Measured on this project: without it, a hard cut at source time 12.570 s
        landed on render frame 63 instead of 77, so every frame of every proof
        render was sampled 20% late, and a fade written for the last 30 frames
        came out at frames 234-259 followed by half a second of black.
        """
        num, den = self.display_aspect
        lines = ["description=%s" % self.description,
                 "frame_rate_num=%d" % self.fps_num,
                 "frame_rate_den=%d" % self.fps_den,
                 "width=%d" % self.width,
                 "height=%d" % self.height,
                 "progressive=1",
                 "sample_aspect_num=%d" % self.sar_num,
                 "sample_aspect_den=%d" % self.sar_den,
                 "display_aspect_num=%d" % num,
                 "display_aspect_den=%d" % den,
                 "colorspace=%s" % self.colorspace]
        return guard.write_text(path, "\n".join(lines) + "\n")


def profile_for(path):
    """Build a profile from a real file.

    The exact rational frame rate is kept: 30000/1001 is not 29.97, and 60 s of
    it is 1801 frames, not 1798.
    """
    data = probe.ffprobe_json(path)
    video = next((s for s in data.get("streams", []) or []
                  if s.get("codec_type") == "video"), None)
    if not video:
        raise PlanError("%s has no video stream to size a profile from" % path)
    num, den = _ratio(video.get("avg_frame_rate") or video.get("r_frame_rate"),
                      (25, 1))
    sar_num, sar_den = _ratio(video.get("sample_aspect_ratio"), (1, 1))
    height = int(video.get("height") or 0)
    width = int(video.get("width") or 0)
    colorspace = "601" if 0 < height <= 576 else "709"
    return Profile(width, height, num, den, sar_num, sar_den, colorspace,
                   "%dx%d %.2f fps" % (width, height, num / float(den)))


def _props(element, pairs):
    """<property name="k">v</property> children, in the order given."""
    for name, value in pairs:
        ET.SubElement(element, "property", {"name": str(name)}).text = str(value)
    return element


FADE_FLOOR_DB = -60.0      # where a fade begins and ends in sound. `volume.level`
                           # is a dB value, and -60 dB on this material is silence
                           # as far as any measurement here can tell.

# --- titles -----------------------------------------------------------------
# A title is a transparent colour producer on V2 with one `dynamictext` filter
# on it, which is how Shotcut writes "Text: Simple": the filter draws into that
# producer's frame and the track is composited over everything below it with
# alpha, so the picture under the text is still there and still editable. The
# bands are percentages of the frame, in melt's `x/y:w x h:opacity` rect form.
TITLE_BANDS = {"top": ("0%", "8%", "100%", "24%"),
               "middle": ("0%", "38%", "100%", "24%"),
               "lower": ("0%", "68%", "100%", "24%")}
TITLE_TRACK = "V2"         # the track titles live on, above V1 and below A1
TITLE_SIZE = 64            # pixels of font height in the project's own resolution
TITLE_FG = "0xffffffff"    # white text ...
TITLE_OUTLINE = "0x000000ff"   # ... with a black outline, so it reads on any shot
TITLE_OUTLINE_WIDTH = 3


def _title_geometry(position):
    """The rect a title is drawn into, from its band name."""
    x, y, w, h = TITLE_BANDS[position]
    return "%s/%s:%sx%s:100" % (x, y, w, h)


class Project(object):
    """One editable Shotcut timeline: background, V1 for picture, A1 for sound.

    Each clip gets its own producer -- Shotcut does the same, and it keeps the
    clip trimmable in the GUI -- and appears in both playlists. What stops the
    audio from playing twice is `hide`: V1 carries hide="audio" and A1 carries
    hide="video", so each track contributes only the stream it is there for.

    The background producer is not decoration. Shotcut always writes one, and
    the per-track `mix` transitions need a track 0 to mix into.
    """

    def __init__(self, name, profile, shotcut=None, mlt=None, title=""):
        self.name = name
        self.profile = profile
        self.shotcut = shotcut or shotcut_version()
        self.mlt = mlt or melt_version() or "?"
        self.title = title or name
        self.clips = []
        self._lengths = {}
        self.fade = {"in": 0, "out": 0, "audio": True}
        self.titles = []
        # Leave the text off a title, keeping everything else about it -- the
        # transparent producer, its frames on V2, the blend. The titles check
        # renders its control this way: two files that differ by one filter
        # element, not by a track or a compositing path. Both of those change
        # the picture everywhere (cairo shifts colour, and melt skips a blend
        # whose b-frame never arrives), which drowns the frames that are
        # supposed to be silent.
        self.no_title_text = False

    # -- building ---------------------------------------------------------
    def add_clip(self, source, t_in, t_out, label=""):
        """Append one trimmed clip. Seconds in, `out` exclusive, frames stored."""
        source = os.path.abspath(source)
        if not os.path.isfile(source):
            raise PlanError("clip source does not exist: %s" % source)
        start = self.profile.frame(t_in)
        end = self.profile.frame(t_out) - 1        # mlt `out` is inclusive
        if end < start:
            raise PlanError("%s: out (%.3fs) does not come after in (%.3fs)"
                            % (source, t_out, t_in))
        total = self.source_frames(source)
        if end >= total:
            raise PlanError("%s: out lands on frame %d but the file has %d"
                            % (source, end, total))
        clip = {"producer": "producer%d" % (len(self.clips) + 1),
                "source": source, "in": start, "out": end,
                "frames": end - start + 1, "at": self.length,
                "label": label or os.path.basename(source)}
        self.clips.append(clip)
        return clip

    def source_frames(self, source):
        """Frame count of the whole file, from the stream when it reports one."""
        if source not in self._lengths:
            data = probe.ffprobe_json(source)
            video = next((s for s in data.get("streams", []) or []
                          if s.get("codec_type") == "video"), {})
            frames = int(video.get("nb_frames") or 0)
            if not frames:
                duration = float((data.get("format") or {}).get("duration") or 0)
                frames = self.profile.frame(duration)
            self._lengths[source] = frames
        return self._lengths[source]

    @property
    def length(self):
        """Timeline length in frames = the sum of the clip lengths."""
        return sum(c["frames"] for c in self.clips)

    # -- titles -----------------------------------------------------------
    def add_title(self, text, t_in, t_out, size=None, position="lower",
                  colour=None):
        """One text overlay, in seconds on the timeline, on its own track."""
        return self._add_title_frames(text, self.profile.frame(t_in),
                                      self.profile.frame(t_out) - 1,
                                      size, position, colour)

    def _add_title_frames(self, text, start, end, size=None, position="lower",
                          colour=None):
        """The frame half of add_title, so a control can reuse exact frames.

        Frames, as everywhere else. Two titles may not overlap: they share V2,
        and a playlist entry cannot start before the one in front of it ends,
        so asking for that is refused here rather than written and silently
        dropped by the compositor.
        """
        text = (str(text) if text is not None else "").strip()
        if not text:
            raise PlanError("a title with no text is not a title")
        position = str(position or "lower").lower()
        if position not in TITLE_BANDS:
            raise PlanError("title position %r is not one of %s"
                            % (position, ", ".join(sorted(TITLE_BANDS))))
        start, end = int(start), int(end)
        if end - start + 1 < 2:
            raise PlanError("title %r is %d frame(s) long: at this frame rate a "
                            "title needs at least two"
                            % (text[:24], end - start + 1))
        if start < 0 or end > self.length - 1:
            raise PlanError("title %r runs frames %d-%d but the timeline is %d "
                            "frames long" % (text[:24], start, end, self.length))
        for other in self.titles:
            if start <= other["at"] + other["frames"] - 1 and other["at"] <= end:
                raise PlanError("title %r overlaps title %r on %s"
                                % (text[:24], other["text"][:24], TITLE_TRACK))
        title = {"producer": "title%d" % (len(self.titles) + 1),
                 "text": text, "in": start, "out": end,
                 "frames": end - start + 1, "at": start,
                 "size": int(size or TITLE_SIZE), "position": position,
                 "geometry": _title_geometry(position),
                 "colour": str(colour or TITLE_FG)}
        self.titles.append(title)
        return title

    def copy_titles(self, other):
        """Another project's titles, frame for frame -- for control renders."""
        for title in other.titles:
            self._add_title_frames(title["text"], title["at"],
                                   title["at"] + title["frames"] - 1,
                                   title["size"], title["position"],
                                   title["colour"])

    def copy_fade(self, other):
        """Another project's fade, frame for frame -- for control renders."""
        self.fade = dict(other.fade)

    def title_over(self, frame):
        """The title that is on screen at a timeline frame, or None."""
        for title in self.titles:
            if title["at"] <= frame <= title["at"] + title["frames"] - 1:
                return title
        return None

    @property
    def has_titles(self):
        return bool(self.titles)

    # -- fade -------------------------------------------------------------
    def set_fade(self, fade_in=0.0, fade_out=0.0, audio=True):
        """Program fade in and out, in seconds, from black and to black.

        Held as frames, like everything else here: 0.8 s at 29.97 fps is 24
        frames, and 24 is what ends up in the file. A one frame fade is not a
        fade, so it is refused rather than written as a keyframe pair that adds
        up to nothing.
        """
        length = self.length
        frames_in = self.profile.frame(fade_in) if fade_in else 0
        frames_out = self.profile.frame(fade_out) if fade_out else 0
        for name, value in (("in", frames_in), ("out", frames_out)):
            if value < 0:
                raise PlanError("fade %s is %.3f s, negative" % (name, -value))
            if value == 1:
                raise PlanError("fade %s is one frame (%.3f s): at this frame rate "
                                "a fade needs at least two" % (name, 1.0 / self.profile.fps))
        if frames_in + frames_out > length:
            raise PlanError("fade in (%d f) + fade out (%d f) is longer than the "
                            "%d frame timeline" % (frames_in, frames_out, length))
        self.fade = {"in": frames_in, "out": frames_out, "audio": bool(audio)}
        return self.fade

    @property
    def has_fade(self):
        return bool(self.fade["in"] or self.fade["out"])

    def _fade_filters(self):
        """The fade as (attributes, properties) pairs for tractor filters.

        Both filters are animated on `level`, which melt reports as animatable
        for `brightness` (0..15, so 0 is black and 1 is untouched) and for
        `volume` (a dB value, so -60 is silence and 0 is untouched). They sit on
        the tractor rather than on a clip because that is what a program fade
        is: it has to darken whatever the timeline ends up showing, including
        titles on their own track later.

        Keyframe times are relative to the filter's own in-point, so the fade
        out filter starts at the last frame the picture is still full and ramps
        from 0 to n-1 inside itself.
        """
        filters = []
        if not self.has_fade:
            return filters
        fade_in, fade_out = self.fade["in"], self.fade["out"]
        last = self.length - 1
        if fade_in:
            attrs = {"in": "0", "out": str(fade_in - 1)}
            filters.append((attrs, [("mlt_service", "brightness"),
                                    ("level", "0=0;%d=1" % (fade_in - 1)),
                                    ("shotcut:filter", "fadeInBrightness")]))
            if self.fade["audio"]:
                filters.append((attrs, [("mlt_service", "volume"),
                                        ("level", "0=%.1f;%d=0"
                                                  % (FADE_FLOOR_DB, fade_in - 1)),
                                        ("shotcut:filter", "fadeInVolume")]))
        if fade_out:
            attrs = {"in": str(last - fade_out + 1), "out": str(last)}
            filters.append((attrs, [("mlt_service", "brightness"),
                                    ("level", "0=1;%d=0" % (fade_out - 1)),
                                    ("shotcut:filter", "fadeOutBrightness")]))
            if self.fade["audio"]:
                filters.append((attrs, [("mlt_service", "volume"),
                                        ("level", "0=0;%d=%.1f"
                                                  % (fade_out - 1, FADE_FLOOR_DB)),
                                        ("shotcut:filter", "fadeOutVolume")]))
        return filters

    # -- xml --------------------------------------------------------------
    def to_xml(self):
        length = self.length
        last = str(max(length - 1, 0))
        root = ET.Element("mlt", {"LC_NUMERIC": "C",
                                  "version": self.mlt,
                                  "title": "Shotcut version %s" % self.shotcut,
                                  "producer": "tractor0"})
        ET.SubElement(root, "profile", self.profile.attrs())

        bg = ET.SubElement(root, "producer", {"id": "producer0", "in": "0",
                                              "out": last})
        _props(bg, [("length", length), ("eof", "pause"), ("resource", "0"),
                    ("aspect_ratio", "1"), ("mlt_service", "color"),
                    ("mlt_image_format", "rgba"), ("set.test_audio", "0")])

        for clip in self.clips:
            # The producer spans the whole file and the *entry* carries the
            # trim. A producer whose in= is already the trim start double-counts
            # it: entries seek relative to the producer's own in, so clip 2 at
            # source frame 1415 landed at 2830 -- past the end, held on the last
            # frame. Measured: 21.6 dB on the correct clip, 8-14 dB on the two
            # shifted ones.
            total = self.source_frames(clip["source"])
            p = ET.SubElement(root, "producer", {"id": clip["producer"],
                                                 "in": "0",
                                                 "out": str(max(total - 1, 0))})
            _props(p, [("length", total),
                       ("eof", "pause"),
                       ("resource", clip["source"].replace("\\", "/")),
                       ("mlt_service", "avformat"),
                       ("audio_index", "1"), ("video_index", "0"),
                       ("seekable", "1"),
                       ("shotcut:caption", clip["label"]),
                       ("cutwright:source",
                        guard.rel(clip["source"]).replace("\\", "/"))])

        for index, title in enumerate(self.titles):
            # Transparent producer + one text filter, the shape Shotcut writes
            # for "Text: Simple". `resource=0x00000000` with an rgba image
            # format is a frame of nothing, which is what makes the blend below
            # put the text over the picture instead of over a black box.
            span = str(title["frames"] - 1)
            p = ET.SubElement(root, "producer", {"id": title["producer"],
                                                 "in": "0", "out": span})
            _props(p, [("length", title["frames"]),
                       ("eof", "pause"),
                       ("resource", "0x00000000"),
                       ("aspect_ratio", "1"),
                       ("mlt_service", "color"),
                       ("mlt_image_format", "rgba"),
                       ("shotcut:caption", title["text"][:60])])
            # The control render is this same producer with this one element
            # left out, so the two files composite identically and the only
            # thing between them is the text.
            if not self.no_title_text:
                f = ET.SubElement(p, "filter", {"id": "titlefilter%d" % index,
                                                "in": "0", "out": span})
                _props(f, [("argument", title["text"]),
                           ("geometry", title["geometry"]),
                           ("family", "Sans"), ("size", title["size"]),
                           ("weight", "700"), ("style", "normal"),
                           ("fgcolour", title["colour"]),
                           ("olcolour", TITLE_OUTLINE),
                           ("outline", TITLE_OUTLINE_WIDTH),
                           ("halign", "center"), ("valign", "middle"),
                           ("mlt_service", "dynamictext"),
                           ("shotcut:filter", "dynamicText")])

        bglist = ET.SubElement(root, "playlist", {"id": "playlist0"})
        _props(bglist, [("shotcut:name", "Background")])
        ET.SubElement(bglist, "entry", {"producer": "producer0", "in": "0",
                                        "out": last})

        v1 = ET.SubElement(root, "playlist", {"id": "playlist1"})
        _props(v1, [("shotcut:video", "1"), ("shotcut:name", "V1")])
        v2 = None
        if self.titles:
            v2 = ET.SubElement(root, "playlist", {"id": "playlist2"})
            _props(v2, [("shotcut:video", "2"), ("shotcut:name", TITLE_TRACK)])
            # A title sits at a frame, so the track needs blanks for the gaps.
            # Without them every later title would slide to the front.
            cursor = 0
            for title in self.titles:
                if title["at"] > cursor:
                    ET.SubElement(v2, "blank",
                                  {"length": str(title["at"] - cursor)})
                ET.SubElement(v2, "entry",
                              {"producer": title["producer"], "in": "0",
                               "out": str(title["frames"] - 1)})
                cursor = title["at"] + title["frames"]
            if cursor < length:
                ET.SubElement(v2, "blank", {"length": str(length - cursor)})
        a1 = ET.SubElement(root, "playlist",
                           {"id": "playlist2" if v2 is None else "playlist3"})
        _props(a1, [("shotcut:audio", "1"), ("shotcut:name", "A1")])
        for clip in self.clips:
            for playlist in (v1, a1):
                ET.SubElement(playlist, "entry",
                              {"producer": clip["producer"],
                               "in": str(clip["in"]), "out": str(clip["out"])})

        tractor = ET.SubElement(root, "tractor", {"id": "tractor0",
                                                  "in": "0", "out": last})
        _props(tractor, [("shotcut", "1"), ("shotcut:projectAudioChannels", "2"),
                         ("shotcut:projectFolder", "0"),
                         ("cutwright:name", self.name),
                         ("cutwright:shotcut", self.shotcut),
                         ("cutwright:mlt", self.mlt)])

        ET.SubElement(tractor, "track", {"producer": "playlist0",
                                         "hide": "audio"})
        ET.SubElement(tractor, "track", {"producer": "playlist1",
                                         "hide": "audio"})
        if v2 is not None:
            ET.SubElement(tractor, "track", {"producer": "playlist2",
                                             "hide": "audio"})
        ET.SubElement(tractor, "track", {"producer": "playlist3" if v2 is not None
                                                    else "playlist2",
                                         "hide": "video"})

        made = [0]

        def transition(service, b_track, a_track=None, **extra):
            el = ET.SubElement(tractor, "transition",
                               {"id": "transition%d" % made[0]})
            made[0] += 1
            pairs = [("a_track", str(b_track - 1 if a_track is None else a_track)),
                     ("b_track", str(b_track)),
                     ("mlt_service", service), ("always_active", "1")]
            pairs += sorted(extra.items())
            return _props(el, pairs)

        # The pair Shotcut writes for every timeline track. The blend on the
        # bottom video track is disabled, which is what Shotcut does too: V1
        # sits straight on the background, so compositing it is cost with no
        # visible gain -- measured here at 6.9 s vs 4.5 s for 60 frames, and
        # the two differ by 33 dB, i.e. cairo shifts the colour slightly.
        #
        # V2 is the opposite case: its whole job is alpha, so its blend has to
        # run. Without it the transparent producer wins the frame and the
        # picture goes black wherever there is no text.
        #
        # The a-frame has to be the track *immediately below*, not the
        # background. Shotcut writes a_track=0 everywhere, but MLT 7.41 as
        # built here composites that onto the background frame instead of onto
        # the running picture: a three-track probe (black / green / red) with
        # composite a=0 b=2 changed nothing at all, while a=1 b=2 put red over
        # green in the requested half of the frame. Same file, same transition,
        # only a_track differs. With a_track=1 the demo's titles appear (centre
        # band YMAX 195 -> 250) and the frames that carry no title stay
        # identical to the control render, so blanks in the title track are
        # harmless.
        # `mix` sums each track's audio into the background frame, and that is
        # where Shotcut puts it: a_track=0 on every one of these. Audio and
        # picture blend differently -- a video blend wants the running picture
        # as its a-frame, an audio mix wants the accumulating sum -- so these
        # stay at the background and the default below is for the blends.
        transition("mix", 1, a_track=0, sum="1")
        transition("frei0r.cairoblend", 1, disable="1")
        if v2 is not None:
            transition("mix", 2, a_track=0, sum="1")
            transition("frei0r.cairoblend", 2)
        transition("mix", 3 if v2 is not None else 2, a_track=0, sum="1")

        for index, (attrs, pairs) in enumerate(self._fade_filters()):
            filter_el = ET.SubElement(tractor, "filter",
                                      dict(attrs, id="filter%d" % index))
            _props(filter_el, pairs)
        return root

    def text(self):
        root = self.to_xml()
        if hasattr(ET, "indent"):
            ET.indent(root, space="  ")
        body = ET.tostring(root, encoding="unicode")
        header = ('<?xml version="1.0" standalone="no"?>\n'
                  "<!-- Cutwright %s | Shotcut %s | MLT %s | %s -->\n"
                  % (CUTWRIGHT_VERSION, self.shotcut, self.mlt,
                     self.profile.description))
        return header + body + "\n"

    def write(self, path):
        return guard.write_text(path, self.text())


# ---------------------------------------------------------------------------
# check 1: is this actually a file Shotcut can open, and does it tell the truth
# about which Shotcut wrote it
# ---------------------------------------------------------------------------
def _result(name, ok, detail, **extra):
    out = {"name": name, "ok": bool(ok), "detail": detail}
    out.update(extra)
    return out


def _service(element):
    return element.findtext("property[@name='mlt_service']")


def check_xml(path):
    """1. Parses, ids unique, references resolve, recorded versions are real."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return _result("xml", False, "not well-formed: %s" % exc)
    except OSError as exc:
        return _result("xml", False, "cannot read it: %s" % exc)

    problems = []
    if root.tag != "mlt":
        problems.append("root is <%s>, not <mlt>" % root.tag)
    for attr in ("LC_NUMERIC", "version", "title"):
        if not root.get(attr):
            problems.append("root has no %s= attribute" % attr)

    ids, twice = set(), []
    for el in root.iter():
        ident = el.get("id")
        if ident:
            if ident in ids and ident not in twice:
                twice.append(ident)
            ids.add(ident)
    if twice:
        problems.append("duplicate id(s): %s" % ", ".join(twice))

    dangling, refs = [], 0
    for el in root.iter():
        for attr in ("producer", "track"):
            ref = el.get(attr)
            if not ref:
                continue
            refs += 1
            if ref not in ids:
                dangling.append("<%s %s=\"%s\">" % (el.tag, attr, ref))
    if dangling:
        problems.append("reference(s) to nothing: %s" % ", ".join(dangling))

    profile = root.find("profile")
    if profile is None:
        problems.append("no <profile>: the timeline has no shape")
    else:
        try:
            numbers = [int(profile.get(k)) for k in
                       ("width", "height", "frame_rate_num", "frame_rate_den")]
            if min(numbers) <= 0:
                problems.append("profile has a zero size or frame rate")
        except (TypeError, ValueError):
            problems.append("profile is missing size or frame rate")

    tractor = root.find("tractor")
    recorded_shotcut = recorded_mlt = None
    if tractor is None:
        problems.append("no <tractor>: melt would have nothing to render")
    else:
        recorded_shotcut = tractor.findtext("property[@name='cutwright:shotcut']")
        recorded_mlt = tractor.findtext("property[@name='cutwright:mlt']")
        tracks = len(tractor.findall("track"))
        for el in tractor.findall("transition"):
            for key in ("a_track", "b_track"):
                raw = el.findtext("property[@name='%s']" % key)
                try:
                    if not 0 <= int(raw) < tracks:
                        problems.append("%s has %s=%s, outside the %d track(s)"
                                        % (el.get("id"), key, raw, tracks))
                except (TypeError, ValueError):
                    problems.append("%s has no usable %s" % (el.get("id"), key))

    shotcut, mlt = shotcut_version(), melt_version()
    title = root.get("title") or ""
    if shotcut not in title:
        problems.append("title %r does not name Shotcut %s" % (title, shotcut))
    if recorded_shotcut != shotcut:
        problems.append("project records Shotcut %r, the installed exe says %s"
                        % (recorded_shotcut, shotcut))
    if mlt and recorded_mlt != mlt:
        problems.append("project records MLT %r, melt.exe says %s"
                        % (recorded_mlt, mlt))

    if problems:
        return _result("xml", False, "; ".join(problems), problems=problems)
    return _result("xml", True,
                   "%d element(s), %d id(s), %d reference(s) resolve, records "
                   "Shotcut %s / MLT %s"
                   % (len(list(root.iter())), len(ids), refs, shotcut, mlt))


# ---------------------------------------------------------------------------
# check 2: nothing is invented -- every name is in melt's own catalogue
# ---------------------------------------------------------------------------
def check_effects(path):
    """2. Every mlt_service in the file exists in this Shotcut's own lists."""
    catalogue = {"producer": query("producers"), "filter": query("filters"),
                 "transition": query("transitions")}
    if not catalogue["filter"] or not catalogue["transition"]:
        return _result("effects", False,
                       "melt -query returned no filter/transition list, so no "
                       "name can be verified")
    counts = "%d filters / %d transitions / %d producers" % (
        len(catalogue["filter"]), len(catalogue["transition"]),
        len(catalogue["producer"]))

    used, problems = [], []
    for el in ET.parse(path).getroot().iter():
        allowed = catalogue.get(el.tag)
        if allowed is None:
            continue
        name = _service(el)
        if not name:
            problems.append("<%s id=%r> has no mlt_service"
                            % (el.tag, el.get("id")))
            continue
        used.append(name)
        if name not in allowed:
            problems.append("%s %r is not in melt's %s list"
                            % (el.tag, name, el.tag))
    if problems:
        return _result("effects", False, "; ".join(problems), counts=counts,
                       used=sorted(set(used)))
    return _result("effects", True,
                   "%d name(s) -- %s -- all in melt's own lists (%s)"
                   % (len(set(used)), ", ".join(sorted(set(used))), counts),
                   counts=counts, used=sorted(set(used)))


# ---------------------------------------------------------------------------
# check 3: the frames add up, on every track, not just the one you looked at
# ---------------------------------------------------------------------------
def check_lengths(path, clips, profile):
    """3. Every track is exactly as long as the tractor; nothing overruns."""
    root = ET.parse(path).getroot()
    tractor = root.find("tractor")
    if tractor is None:
        return _result("lengths", False, "no <tractor>")
    try:
        total = int(tractor.get("out")) - int(tractor.get("in")) + 1
    except (TypeError, ValueError):
        return _result("lengths", False, "tractor has no usable in/out")

    problems = []
    expected = sum(c["frames"] for c in clips)
    if total != expected:
        problems.append("tractor is %d frames, the plan adds up to %d"
                        % (total, expected))

    producers = {}
    for p in root.findall("producer"):
        try:
            producers[p.get("id")] = int(p.findtext("property[@name='length']"))
        except (TypeError, ValueError):
            producers[p.get("id")] = 0

    per_track = {}
    for playlist in root.findall("playlist"):
        name = (playlist.findtext("property[@name='shotcut:name']")
                or playlist.get("id"))
        frames = 0
        for entry in playlist:
            if entry.tag == "blank":
                # A title track is mostly gap, and the gap is as much a part of
                # the track's length as the entries are: counting only entries
                # would report V2 short by every frame with no text on it.
                try:
                    frames += int(entry.get("length"))
                except (TypeError, ValueError):
                    problems.append("%s has a blank without a length" % name)
                continue
            if entry.tag != "entry":
                continue
            try:
                start, end = int(entry.get("in")), int(entry.get("out"))
            except (TypeError, ValueError):
                problems.append("%s has an entry without in/out" % name)
                continue
            if end < start:
                problems.append("%s has an entry that ends before it starts" % name)
            frames += end - start + 1
            limit = producers.get(entry.get("producer"), 0)
            if limit and end >= limit:
                problems.append("%s entry ends at frame %d, past %s's %d frames"
                                % (name, end, entry.get("producer"), limit))
        per_track[name] = frames
        if frames != total:
            problems.append("%s is %d frames, the tractor is %d"
                            % (name, frames, total))

    v1 = [int(e.get("out")) - int(e.get("in")) + 1
          for e in root.findall("playlist[@id='playlist1']/entry")]
    want = [c["frames"] for c in clips]
    if v1 != want:
        problems.append("V1 entries are %s frames, the plan says %s"
                        % (v1, want))

    if problems:
        return _result("lengths", False, "; ".join(problems), per_track=per_track)
    return _result("lengths", True,
                   "%d frames (%.3f s) = %s; %s"
                   % (total, profile.seconds(total),
                      " + ".join(str(f) for f in want),
                      ", ".join("%s %d" % (k, v) for k, v in sorted(per_track.items()))),
                   per_track=per_track)


# ---------------------------------------------------------------------------
# check 4: render it small and ugly, then prove the frames are the right frames
# ---------------------------------------------------------------------------
MIN_PSNR = 24.0            # same shot through a different encoder and scaler
                           # lands near 30 dB; a different shot lands under 15.
MIN_RENDER_BYTES = 1000    # smaller than this means melt wrote nothing usable
SAMPLE_WINDOW = 21         # frames rendered either side of a sample, so the
                           # +-2 frame search has material to search in


def _profile_for_render(project, near_path):
    """Drop the project's profile next to the render so melt can be told it."""
    folder = os.path.dirname(os.path.abspath(near_path))
    return project.profile.write_file(os.path.join(folder, "profile.prof"))


def _melt_render(path, out_path, opts, limit, first=0, timeout=600, profile=None):
    """One melt pass over a frame range. Returns (ok, detail, seconds)."""
    cmd = [MELT]
    if profile:
        cmd += ["-profile", profile]
    cmd += [path, "in=%d" % first, "out=%d" % limit, "-consumer",
            "avformat:" + out_path] + opts
    started = time.time()
    try:
        r = probe.run(cmd, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "melt did not finish in %d s" % timeout, 0.0
    elapsed = time.time() - started
    if r.returncode != 0:
        tail = ((r.stderr or "") + (r.stdout or "")).strip().splitlines()[-3:]
        return False, "melt exited %d: %s" % (r.returncode, " / ".join(tail)), elapsed
    if not os.path.isfile(out_path) or os.path.getsize(out_path) < MIN_RENDER_BYTES:
        return False, "melt exited 0 but wrote no usable file", elapsed
    return True, "ok", elapsed


def render_video(project, path, out_mp4, width=270, crf=34):
    """Small picture-only render, then check it is as long as the timeline.

    Video and audio are rendered in two passes on purpose. In this build (melt
    7.41.0 / Shotcut 26.9.27) a single pass that encodes a project *with* audio
    reaches the last frame and then never exits -- melt's own serialized XML
    does exactly the same, so it is a property of melt here, not of the shape of
    this file. Split in two, both passes finish in seconds.
    """
    profile = project.profile
    height = int(round(width * profile.height / float(profile.width) / 2.0)) * 2
    ok, detail, elapsed = _melt_render(
        path, out_mp4,
        ["f=mp4", "vcodec=libx264", "crf=%d" % crf, "preset=ultrafast",
         "pix_fmt=yuv420p", "s=%dx%d" % (width, height), "an=1",
         "real_time=-1"],
        project.length - 1, profile=_profile_for_render(project, out_mp4))
    if not ok:
        return False, "video pass: " + detail, {}
    data = probe.ffprobe_json(out_mp4)
    video = next((s for s in data.get("streams", []) or []
                  if s.get("codec_type") == "video"), {})
    produced = int(video.get("nb_frames") or 0)
    if not produced:
        produced = profile.frame(float((data.get("format") or {}).get("duration") or 0))
    return True, detail, {"mp4": out_mp4, "width": width, "height": height,
                          "frames": produced, "seconds": elapsed}


def render_audio(project, path, out_wav):
    """Audio-only pass to PCM, so the level can be measured without a codec."""
    ok, detail, elapsed = _melt_render(
        path, out_wav,
        ["f=wav", "acodec=pcm_s16le", "ar=44100", "channels=2", "vn=0",
         "real_time=-1"],
        project.length - 1, profile=_profile_for_render(project, out_wav))
    if not ok:
        return False, "audio pass: " + detail, {}
    data = probe.ffprobe_json(out_wav)
    stream = next((s for s in data.get("streams", []) or []
                   if s.get("codec_type") == "audio"), None)
    if stream is None:
        return False, "audio pass produced no audio stream", {}
    try:
        seconds = float((data.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        seconds = 0.0
    return True, detail, {"wav": out_wav, "seconds": seconds, "time": elapsed}


def _frame(video, seconds, out_png, size=None):
    """One still, scaled to the render's size so the two are comparable."""
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-ss", "%.3f" % max(seconds, 0.0), "-i", video, "-frames:v", "1", "-an"]
    if size:
        cmd += ["-vf", "scale=%d:%d" % size]
    cmd.append(out_png)
    r = probe.run(cmd, timeout=180)
    return r.returncode == 0 and os.path.isfile(out_png)


def _psnr(a, b):
    """PSNR between two stills, from ffmpeg's own filter. inf == identical."""
    r = probe.run(["ffmpeg", "-hide_banner", "-nostdin", "-i", a, "-i", b,
                   "-lavfi", "psnr", "-f", "null", "-"], timeout=180)
    found = re.findall(r"average:(inf|[0-9.]+)", (r.stderr or ""))
    if not found:
        return None
    last = found[-1]
    return float("inf") if last == "inf" else float(last)


def _loudness(path, start=None, duration=None):
    """mean_volume in dBFS, from ffmpeg's volumedetect."""
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-i", path, "-map", "0:a:0"]
    if start is not None:
        cmd += ["-ss", "%.3f" % start]
    if duration is not None:
        cmd += ["-t", "%.3f" % duration]
    cmd += ["-af", "volumedetect", "-f", "null", "-"]
    r = probe.run(cmd, timeout=300)
    m = re.search(r"mean_volume:\s*(-?[0-9.]+) dB", (r.stderr or ""))
    return float(m.group(1)) if m else None


def _sample_clips(clips, count):
    """Which clips to look at: first, last, and an even spread between."""
    if len(clips) <= count:
        return list(range(len(clips)))
    return sorted({int(round(i * (len(clips) - 1) / float(count - 1)))
                   for i in range(count)})


def _reference_clip(project, index, work_dir, width, crf):
    """Render one sample's source frames, as a one-clip project by this writer.

    Why not melt on the source directly: the real project goes through the RGBA
    compositing path Shotcut uses (background, blend, mix) and a bare source
    render does not. Measured on a clip that was demonstrably at the right
    frames, the two agreed to 45 dB on chroma but only 22.8 dB on luma -- that
    is the pipeline, not the footage, and it left no room above the 13 dB a
    wrong clip scores.

    Building the reference with the same writer puts both sides on the same
    path, so the only thing left to differ is which frames are on screen. A
    timing bug in the writer still cannot hide: this reference starts at a
    different source frame from the clip it is checking.
    """
    clip = project.clips[index]
    mid = clip["in"] + clip["frames"] // 2
    first = max(mid - SAMPLE_WINDOW // 2, 0)
    fps = project.profile.fps
    solo = Project("ref%d" % index, project.profile, project.shotcut, project.mlt,
                   "reference window")
    solo.add_clip(clip["source"], first / fps, (first + SAMPLE_WINDOW) / fps,
                  "reference window")
    path = solo.write(os.path.join(work_dir, "ref_%d.mlt" % index))
    height = int(round(width * project.profile.height /
                       float(project.profile.width) / 2.0)) * 2
    out_mp4 = os.path.join(work_dir, "ref_%d.mp4" % index)
    if os.path.isfile(out_mp4):
        os.remove(out_mp4)
    ok, _detail, _seconds = _melt_render(
        path, out_mp4,
        ["f=mp4", "vcodec=libx264", "crf=%d" % crf, "preset=ultrafast",
         "pix_fmt=yuv420p", "s=%dx%d" % (width, height), "an=1",
         "real_time=-1"],
        solo.length - 1, profile=_profile_for_render(solo, out_mp4))
    if not ok:
        return None, mid
    return (out_mp4, first), mid


def check_render(project, path, work_dir, width=270, crf=34, samples=3):
    """4. A small render whose frames are compared to the source they claim.

    Two things stop this being a rubber stamp. Each sample is scored at offsets
    of 0, +-1 and +-2 frames, so a rounding disagreement cannot fail an edit
    that is otherwise right; and one deliberate mismatch -- a frame from a
    different clip -- is scored the same way. If that control does not come out
    clearly lower, this check is not measuring anything, and the detail says so
    instead of congratulating itself.
    """
    profile = project.profile
    fps = profile.fps
    guard.ensure_dir(work_dir)
    out_mp4 = os.path.join(work_dir, "proof.mp4")
    out_wav = os.path.join(work_dir, "proof.wav")
    for stale in (out_mp4, out_wav):
        if os.path.isfile(stale):
            os.remove(stale)

    ok, detail, info = render_video(project, path, out_mp4, width=width, crf=crf)
    if not ok:
        return _result("render", False, detail)
    ok, detail, sound = render_audio(project, path, out_wav)
    if not ok:
        return _result("render", False, detail)

    problems = []
    produced = info["frames"]
    if abs(produced - project.length) > 1:
        problems.append("picture pass has %d frames, the timeline is %d"
                        % (produced, project.length))
    expected_seconds = profile.seconds(project.length)
    if abs(sound["seconds"] - expected_seconds) > 0.15:
        problems.append("audio pass is %.3f s, the timeline is %.3f s"
                        % (sound["seconds"], expected_seconds))
    size = (info["width"], info["height"])

    shots, rows = [], []
    for index in _sample_clips(project.clips, samples):
        clip = project.clips[index]
        offset = clip["frames"] // 2
        # A title is drawn over the picture, so a frame under one is no longer
        # a frame of the source. Step along the clip to a sample the titles
        # leave alone -- the check is about which source frames are on screen,
        # and it should not be reading text it put there itself.
        for delta in (0, 8, -8, 16, -16, 24, -24, 32, -32):
            candidate = clip["frames"] // 2 + delta
            if (0 <= candidate < clip["frames"]
                    and not project.title_over(clip["at"] + candidate)):
                offset = candidate
                break
        at = (clip["at"] + offset) / fps
        shot = os.path.join(work_dir, "render_%d.png" % index)
        if not _frame(out_mp4, at, shot, size):
            problems.append("could not pull a render frame at %.3f s" % at)
            continue

        reference, mid = _reference_clip(project, index, work_dir, width, crf)
        if not reference:
            problems.append("could not render a reference for clip %d" % index)
            continue
        ref_mp4, first = reference
        shots.append((index, shot, ref_mp4, first))

        best_shift, best_score = 0, None
        for shift in (0, -1, 1, -2, 2):
            expected_png = os.path.join(work_dir,
                                        "ref_%d_%+d.png" % (index, shift))
            if not _frame(ref_mp4, (mid - first + shift) / fps, expected_png,
                          size):
                continue
            score = _psnr(shot, expected_png)
            if score is not None and (best_score is None or score > best_score):
                best_shift, best_score = shift, score
        if best_score is None:
            problems.append("could not compare clip %d against its reference" % index)
            continue
        rows.append({"clip": index, "at_s": round(at, 3),
                     "source_frame": mid, "offset_frames": best_shift,
                     "psnr": None if best_score == float("inf")
                             else round(best_score, 2)})
        if best_score < MIN_PSNR:
            problems.append("clip %d at %.2f s only scores %.1f dB against the "
                            "same source frames -- that is the wrong footage"
                            % (index, at, best_score))

    control = None
    if len(shots) >= 2:
        last = len(project.clips) - 1
        reference, mid = _reference_clip(project, last, work_dir, width, crf)
        if reference:
            ref_mp4, first = reference
            other_png = os.path.join(work_dir, "control.png")
            if _frame(ref_mp4, (mid - first) / fps, other_png, size):
                control = _psnr(shots[0][1], other_png)

    heard = []
    for index, clip in enumerate(project.clips):
        span = clip["frames"] / fps
        got = _loudness(out_wav, clip["at"] / fps, span)
        want = _loudness(clip["source"], clip["in"] / fps, span)
        if got is None or want is None:
            continue
        heard.append((got, want))
        if got > want + 4.0:
            problems.append("clip %d measures %.1f dB in the render against "
                            "%.1f dB in the source -- that is the same audio "
                            "playing twice" % (index, got, want))

    scores = [r["psnr"] for r in rows if r["psnr"] is not None]
    detail = "%d/%d frames, %.3f s of audio" % (produced, project.length,
                                                sound["seconds"])
    if scores:
        detail += ", " + ", ".join("%.1f dB" % s for s in scores)
    if control is not None:
        detail += ", control %.1f dB" % control
        if scores and control > min(scores) - 3.0:
            detail += " (weak: cannot tell these shots apart)"
    if heard:
        detail += (", audio %.1f dB vs source %.1f dB"
                   % (sum(g for g, _w in heard) / len(heard),
                      sum(w for _g, w in heard) / len(heard)))
    detail += ", %.1f s to render at %dx%d" % (info["seconds"] + sound["time"],
                                               info["width"], info["height"])

    if problems:
        return _result("render", False, "; ".join(problems) + " [" + detail + "]",
                       samples=rows, control=control)
    return _result("render", True, detail, samples=rows, control=control,
                   mp4=out_mp4, wav=out_wav)


# ---------------------------------------------------------------------------
# check 5: the fade, measured on the rendered picture and the rendered sound
# ---------------------------------------------------------------------------
FADE_BLACK = 0.05           # level at or under this still reads as black
FADE_FULL = 0.90            # ... and at or over this reads as full brightness
FADE_MID_RANGE = (0.25, 0.75)   # where the half-way frame has to land. melt
                                # eases in and out of an animated property, so
                                # the half-way frame sits near the middle of the
                                # range, not on a straight line to it.
FADE_AUDIO_DROP = 20.0      # dB the first moments of sound have to sit below the
                            # middle of the timeline before it counts as a fade


def _luma_curve(video, size=None):
    """Mean luma (YAVG, 0-255) of every frame, in order, from signalstats."""
    cfilter = "signalstats,metadata=print:file=-"
    if size:
        cfilter = "scale=%d:%d,%s" % (size[0], size[1], cfilter)
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-i", video, "-an",
           "-vf", cfilter, "-f", "null", "-"]
    r = probe.run(cmd, timeout=600)
    return [float(v) for v in re.findall(r"YAVG=([0-9.]+)",
                                        (r.stdout or "") + (r.stderr or ""))]



def check_fade(project, path, work_dir, proof=None, wav=None, width=140, crf=36):
    """5. Dark at both ends, a ramp in between, measured frame by frame.

    The same project is rendered twice: once as written, once with the fade
    taken out by this same writer. Frame n of one against frame n of the other
    gives the level the fade applied at that frame -- same footage, same
    compositing path, same encoder -- so the check never has to assume what the
    shot was supposed to look like. An earlier version compared the head against
    the middle of the timeline and read a different, brighter shot as "the
    picture"; this one cannot make that mistake.

    What it asserts is the shape, not the curve: black at the outer frame, full
    at the frame just outside the fade, an eased ramp landing between the two at
    the half-way frame, and full brightness everywhere in between. A filter that
    is written but not applied, or applied at the wrong frames, fails all four.
    """
    if not project.has_fade:
        return _result("fade", False,
                       "the plan has no fade, so there is nothing to measure here")

    fps = project.profile.fps
    length = project.length
    guard.ensure_dir(work_dir)
    problems, rows = [], []

    if not (proof and os.path.isfile(proof)):
        proof = os.path.join(work_dir, "fade.mp4")
        if os.path.isfile(proof):
            os.remove(proof)
        ok, detail, _info = render_video(project, path, proof, width=width, crf=crf)
        if not ok:
            return _result("fade", False, "no picture to measure: " + detail)

    # The control: this project with the fade removed, so both renders differ in
    # exactly one thing.
    plain = Project(project.name + "_no_fade", project.profile, project.shotcut,
                    project.mlt, "same timeline, no fade")
    for clip in project.clips:
        plain.add_clip(clip["source"], clip["in"] / fps,
                       (clip["out"] + 1) / fps, clip["label"])
    plain.copy_titles(project)     # the fade has to darken text too, so the
                                  # control keeps the titles and drops only the fade
    plain_path = plain.write(os.path.join(work_dir, plain.name + ".mlt"))
    plain_mp4 = os.path.join(work_dir, plain.name + ".mp4")
    if os.path.isfile(plain_mp4):
        os.remove(plain_mp4)
    ok, detail, _info = render_video(plain, plain_path, plain_mp4, width=width,
                                     crf=crf)
    if not ok:
        return _result("fade", False, "no control picture to compare against: "
                                      + detail)

    size = (int(width), int(round(width * project.profile.height /
                                 float(project.profile.width) / 2.0)) * 2)
    faded = _luma_curve(proof, size)
    control = _luma_curve(plain_mp4, size)
    if len(faded) < length - 1 or len(control) < length - 1:
        return _result("fade", False,
                       "could not read both renders in full: %d and %d frames "
                       "against a %d frame timeline"
                       % (len(faded), len(control), length))

    level = []
    for index in range(length):
        a = faded[index]
        b = control[index]
        # Below 17 there is no light to divide: a black frame either way.
        level.append((a - 16.0) / (b - 16.0) if b > 17.0 else 1.0)

    def measure(label, frame):
        frame = max(0, min(frame, length - 1))
        value = round(level[frame], 3)
        rows.append({"what": label, "frame": frame,
                     "at_s": round(frame / fps, 3), "level": value})
        return value

    def want(label, frame, low, high):
        value = measure(label, frame)
        if not low <= value <= high:
            problems.append("%s measures %.2f of full brightness, wanted %.2f-%.2f"
                            % (label, value, low, high))
        return value

    if project.fade["in"]:
        n = project.fade["in"]
        want("first frame", 0, 0.0, FADE_BLACK)
        want("half way into the fade in", (n - 1) // 2, FADE_MID_RANGE[0],
             FADE_MID_RANGE[1])
        want("first frame after the fade in", n, FADE_FULL, 1.02)

    if project.fade["out"]:
        n, last = project.fade["out"], length - 1
        start = last - n + 1
        want("last frame before the fade out", start - 1, FADE_FULL, 1.02)
        want("half way into the fade out", start + (n - 1) // 2,
             FADE_MID_RANGE[0], FADE_MID_RANGE[1])
        want("last frame", last, 0.0, FADE_BLACK)

    # The middle has to be untouched, or a fade is just the visible part of a
    # timeline that is dimmed somewhere it should not be.
    for frame in (project.fade["in"] + 1,
                  length // 2,
                  length - project.fade["out"] - 2):
        if 0 <= frame < length:
            want("frame %d, inside the edit" % frame, frame, FADE_FULL, 1.02)

    heard = None
    if project.fade["audio"] and project.fade["in"]:
        span = min(0.15, project.fade["in"] / fps)
        mine = False
        if not (wav and os.path.isfile(wav)):
            mine = True
            wav = os.path.join(work_dir, "fade.wav")
            if os.path.isfile(wav):
                os.remove(wav)
            ok, detail, _info = render_audio(project, path, wav)
            if not ok:
                problems.append("no sound to measure: " + detail)
                wav = None
        if wav:
            first_db = _loudness(wav, 0.0, span)
            mid_db = _loudness(wav, project.profile.seconds(length // 2), span)
            if first_db is not None and mid_db is not None:
                heard = (first_db, mid_db)
                if first_db > mid_db - FADE_AUDIO_DROP:
                    problems.append("the first %.2f s of sound measures %.1f dB "
                                    "against %.1f dB in the middle -- the sound "
                                    "does not fade with the picture"
                                    % (span, first_db, mid_db))
        if mine and wav and os.path.isfile(wav):
            os.remove(wav)

    detail = ", ".join("%s %.2f" % (row["what"], row["level"]) for row in rows)
    if heard:
        detail += (", sound %.1f dB at the head against %.1f dB in the middle"
                   % heard)
    if problems:
        return _result("fade", False, "; ".join(problems) + " [" + detail + "]",
                       samples=rows)
    return _result("fade", True, "level " + detail, samples=rows)


# ---------------------------------------------------------------------------
# check 6: the text is on screen, in the band the plan named, only when it says
# ---------------------------------------------------------------------------
TITLE_PSNR_MIN = 15.0     # a title changes a lot of pixels ...
TITLE_PSNR_MAX = 45.0     # ... but the shot under it is still most of the frame
TITLE_QUIET_PSNR = 50.0   # outside its window the two renders are one picture
TITLE_BAND_MARGIN = 2.5   # dB the named band has to change more than the frame
TITLE_MIN_LUMA = 20.0     # mean luma of the shot under the text, of 255


def _crop(src, out, box):
    """Cut a still down to a rectangle of itself, in pixels."""
    x, y, w, h = box
    r = probe.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src,
                   "-frames:v", "1", "-vf", "crop=%d:%d:%d:%d" % (w, h, x, y),
                   out], timeout=180)
    return r.returncode == 0 and os.path.isfile(out)


def _still_luma(png):
    """Mean luma of one still, 0-255."""
    r = probe.run(["ffmpeg", "-hide_banner", "-nostdin", "-i", png, "-vf",
                   "signalstats,metadata=print:file=-", "-f", "null", "-"],
                  timeout=180)
    found = re.findall(r"YAVG=([0-9.]+)", (r.stdout or "") + (r.stderr or ""))
    return float(found[-1]) if found else None


def check_titles(project, path, work_dir, width=270):
    """6. Text on screen, in the band the plan chose, only inside its window.

    Both sides are rendered by this writer: the project as planned, and the
    same timeline with the text filters left off. Frame n of one against frame
    n of the other is then the text and nothing else -- same footage, same
    producer, same track, same compositing path, same encoder -- so nothing
    here has to guess what the shot looked like. Every other way of building
    the control changes the picture everywhere: dropping V2 drops the blend
    with it, and melt skips a blend whose b-frame never arrives, while cairo
    on its own shifts colour slightly; an empty V2 is a third path again. Any
    of those moves every frame in the timeline, which is indistinguishable from
    a title that never starts or stops on time. The two renders are lossless
    for the same reason: a lossy codec carries a bright title a little way into
    the frames after it.
    Per title it asserts three things: the frame changed (a title is visible at
    all), the change sits in the band the plan named rather than spread over
    the whole frame (it is where it was asked to be), and the frames just
    outside the window are untouched (it starts and stops on the frames the
    plan gave it). A title written into the file but never drawn fails the
    first; one drawn over the whole frame fails the second; one at the wrong
    time fails the third.
    """
    if not project.has_titles:
        return _result("titles", False,
                       "the plan has no titles, so there is nothing to measure here")

    fps = project.profile.fps
    guard.ensure_dir(work_dir)
    problems, rows, quiet = [], [], []

    # Both sides are rendered here, lossless. A lossy codec smears a frame that
    # did change into the frames after it -- a title is bright, the frames just
    # past its out point then read 33 dB instead of identical, and a check that
    # cannot tell drift from a late title is no check. crf=0 costs about 8 MB
    # and a few seconds a side at this width.
    planned_mp4 = os.path.join(work_dir, project.name + "_titles.mp4")
    if os.path.isfile(planned_mp4):
        os.remove(planned_mp4)
    ok, detail, _info = render_video(project, path, planned_mp4, width=width,
                                     crf=0)
    if not ok:
        return _result("titles", False, "no picture to measure: " + detail)

    plain = Project(project.name + "_no_titles", project.profile, project.shotcut,
                    project.mlt, "same timeline, no titles")
    for clip in project.clips:
        plain.add_clip(clip["source"], clip["in"] / fps,
                       (clip["out"] + 1) / fps, clip["label"])
    plain.copy_fade(project)       # only the titles come out, so the fade stays
    plain.no_title_text = True     # ...and so does the text's producer and track
    plain_path = plain.write(os.path.join(work_dir, plain.name + ".mlt"))
    plain_mp4 = os.path.join(work_dir, plain.name + ".mp4")
    if os.path.isfile(plain_mp4):
        os.remove(plain_mp4)
    ok, detail, _info = render_video(plain, plain_path, plain_mp4, width=width,
                                     crf=0)
    if not ok:
        return _result("titles", False,
                       "no control picture to compare against: " + detail)

    size = (int(width), int(round(width * project.profile.height /
                                  float(project.profile.width) / 2.0)) * 2)

    def at(label, frame, box=None):
        """PSNR between the two renders at one frame: whole frame, or one band."""
        a = os.path.join(work_dir, "title_a.png")
        b = os.path.join(work_dir, "title_b.png")
        for stale in (a, b):
            if os.path.isfile(stale):
                os.remove(stale)
        if not (_frame(planned_mp4, frame / fps, a, size)
                and _frame(plain_mp4, frame / fps, b, size)):
            problems.append("%s: could not pull frame %d from both renders"
                            % (label, frame))
            return None
        if box:
            ca = os.path.join(work_dir, "title_a_band.png")
            cb = os.path.join(work_dir, "title_b_band.png")
            if not (_crop(a, ca, box) and _crop(b, cb, box)):
                problems.append("%s: could not crop the title band" % label)
                return None
            a, b = ca, cb
        return _psnr(a, b)

    for index, title in enumerate(project.titles):
        band = TITLE_BANDS[title["position"]]
        top, down = band[1], band[3]
        box = (0,
               int(round(size[1] * float(top.rstrip("%")) / 100.0)),
               size[0],
               max(int(round(size[1] * float(down.rstrip("%")) / 100.0)), 2))
        start = title["at"]
        end = start + title["frames"] - 1
        for label, frame in (("first frame", min(start + 1, end)),
                             ("middle frame", (start + end) // 2),
                             ("last frame", max(end - 1, start))):
            whole = at("title %d %s" % (index + 1, label), frame)
            if whole is None:
                continue
            band_db = at("title %d %s band" % (index + 1, label), frame, box)
            rows.append({"title": index + 1, "what": label, "frame": frame,
                         "whole_psnr": round(whole, 2),
                         "band_psnr": None if band_db is None else round(band_db, 2)})
            if whole < TITLE_PSNR_MIN:
                problems.append("title %d: the %s (frame %d) is %.1f dB from the "
                                "same frame without it -- the picture was replaced"
                                % (index + 1, label, frame, whole))
            elif whole > TITLE_PSNR_MAX:
                problems.append("title %d: the %s (frame %d) is %.1f dB from the "
                                "same frame without it, i.e. nothing visible "
                                "changed" % (index + 1, label, frame, whole))
            if band_db is not None and band_db >= whole - TITLE_BAND_MARGIN:
                problems.append("title %d: the %s changes the whole frame and its "
                                "%s band by about the same (%.1f vs %.1f dB), so "
                                "the text is not confined to that band"
                                % (index + 1, label, title["position"], band_db,
                                   whole))

        # Outside the window nothing may be drawn: one frame before the title
        # starts and one after it ends, unless another title is on screen there.
        for frame in (start - 2, end + 1):
            if not 0 <= frame < project.length:
                continue
            if project.title_over(frame) not in (None, title):
                continue
            value = at("title %d quiet frame" % (index + 1), frame)
            if value is None:
                continue
            quiet.append({"title": index + 1, "frame": frame,
                          "whole_psnr": round(value, 2)})
            if value < TITLE_QUIET_PSNR:
                problems.append("title %d is on screen at frame %d (%.1f dB from "
                                "the same frame without it), outside its window "
                                "%d-%d" % (index + 1, frame, value, start, end))

        # A title over a black frame would pass everything above and still be
        # wrong: the shot has to be there under the text.
        under, mid = os.path.join(work_dir, "title_under.png"), (start + end) // 2
        if _frame(plain_mp4, mid / fps, under, size):
            luma = _still_luma(under)
            if luma is not None and luma < TITLE_MIN_LUMA:
                problems.append("the shot under title %d measures %.1f of 255 "
                                "luma at frame %d: the text is over a black frame"
                                % (index + 1, luma, mid))

    detail = "; ".join(
        "title %d frames %d-%d: %s"
        % (index + 1, title["at"], title["at"] + title["frames"] - 1,
           ", ".join("%s band %.1f / frame %.1f dB"
                     % (row["what"], row["band_psnr"], row["whole_psnr"])
                     for row in rows if row["title"] == index + 1))
        for index, title in enumerate(project.titles))
    if quiet:
        detail += ", clear outside the window at frame(s) %s" % ", ".join(
            "%d (%.1f dB)" % (row["frame"], row["whole_psnr"]) for row in quiet)
    if problems:
        return _result("titles", False, "; ".join(problems) + " [" + detail + "]",
                       samples=rows + quiet)
    return _result("titles", True, detail, samples=rows + quiet)


# ---------------------------------------------------------------------------
# plan -> project -> checks, in one place so the CLI stays thin
# ---------------------------------------------------------------------------
def _resolve(raw, base):
    """Absolute, else relative to the fork root, else relative to the plan."""
    if os.path.isabs(raw):
        return os.path.abspath(raw)
    for root in (guard.ROOT, base):
        candidate = os.path.abspath(os.path.join(root, raw))
        if os.path.isfile(candidate):
            return candidate
    return os.path.abspath(os.path.join(guard.ROOT, raw))


def load_plan(path):
    """Read a plan and refuse it early, before anything is written."""
    plan = guard.read_json(path)
    if not isinstance(plan, dict):
        raise PlanError("%s is not a JSON object" % path)
    raw_clips = plan.get("clips")
    if not isinstance(raw_clips, list) or not raw_clips:
        raise PlanError("%s needs a non-empty \"clips\" list" % path)
    base = os.path.dirname(os.path.abspath(path))
    clips = []
    for index, raw in enumerate(raw_clips):
        if not isinstance(raw, dict) or not raw.get("source"):
            raise PlanError("clip %d has no \"source\"" % index)
        try:
            start, end = float(raw.get("in", 0.0)), float(raw.get("out", 0.0))
        except (TypeError, ValueError):
            raise PlanError("clip %d has a non-numeric in/out" % index)
        if end <= start:
            raise PlanError("clip %d: out (%s) has to come after in (%s)"
                            % (index, end, start))
        clips.append({"source": _resolve(str(raw["source"]), base),
                      "in": start, "out": end,
                      "label": str(raw.get("label") or "")})
    raw_fade = plan.get("fade") or {}
    if not isinstance(raw_fade, dict):
        raise PlanError("\"fade\" has to be an object like {\"in\": 0.8, \"out\": 1.0}")
    fade = {}
    for key in ("in", "out"):
        try:
            fade[key] = float(raw_fade.get(key, 0.0) or 0.0)
        except (TypeError, ValueError):
            raise PlanError("fade %s is not a number: %r" % (key, raw_fade.get(key)))
        if fade[key] < 0:
            raise PlanError("fade %s is negative (%.3f s)" % (key, fade[key]))
    fade["audio"] = bool(raw_fade.get("audio", True))
    raw_titles = plan.get("titles") or []
    if not isinstance(raw_titles, list):
        raise PlanError("\"titles\" has to be a list of "
                        "{\"text\": ..., \"in\": 0.5, \"out\": 2.5} objects")
    titles = []
    for index, raw in enumerate(raw_titles):
        if not isinstance(raw, dict) or not str(raw.get("text") or "").strip():
            raise PlanError("title %d has no \"text\"" % index)
        try:
            start, end = float(raw.get("in", 0.0)), float(raw.get("out", 0.0))
        except (TypeError, ValueError):
            raise PlanError("title %d has a non-numeric in/out" % index)
        if end <= start:
            raise PlanError("title %d: out (%s) has to come after in (%s)"
                            % (index, end, start))
        try:
            size = int(raw.get("size") or 0)
        except (TypeError, ValueError):
            raise PlanError("title %d has a non-numeric size: %r"
                            % (index, raw.get("size")))
        titles.append({"text": str(raw["text"]).strip(), "in": start, "out": end,
                       "size": size or None,
                       "position": str(raw.get("position") or "lower"),
                       "colour": str(raw.get("colour") or "").strip() or None})
    name = str(plan.get("name") or
               os.path.splitext(os.path.basename(path))[0])
    return {"name": name, "title": str(plan.get("title") or ""),
            "clips": clips, "fade": fade, "titles": titles,
            "path": os.path.abspath(path)}


def build(plan_path, out_root=None, width=270, crf=34, samples=3, checks=None):
    """Plan -> .mlt -> the checks that apply -> a record of all of it on disk.

    `checks` can name a subset while a feature is being added, so a half-built
    feature does not have to pass every gate to be looked at. A check left out
    is recorded as not run, never as passed.
    """
    plan = load_plan(plan_path)
    profile = profile_for(plan["clips"][0]["source"])
    project = Project(plan["name"], profile, title=plan["title"])
    for clip in plan["clips"]:
        project.add_clip(clip["source"], clip["in"], clip["out"], clip["label"])
    if plan["fade"]["in"] or plan["fade"]["out"]:
        project.set_fade(plan["fade"]["in"], plan["fade"]["out"],
                         plan["fade"]["audio"])
    for title in plan["titles"]:
        project.add_title(title["text"], title["in"], title["out"],
                          title["size"], title["position"], title["colour"])
    folder = guard.ensure_dir(os.path.join(out_root or guard.PROJECTS,
                                          project.name))
    path = project.write(os.path.join(folder, project.name + ".mlt"))

    order = ["xml", "effects", "lengths", "render"]
    if project.has_fade:
        order.append("fade")
    if project.has_titles:
        order.append("titles")
    wanted = [c.lower() for c in (checks or order)]
    unknown = [name for name in wanted if name not in order]
    if unknown:
        raise PlanError("no such check(s): %s (this build has %s)"
                        % (", ".join(sorted(set(unknown))), ", ".join(order)))
    skipped = [name for name in order if name not in wanted]
    results = []
    if "xml" in wanted:
        results.append(check_xml(path))
    if "effects" in wanted:
        results.append(check_effects(path))
    if "lengths" in wanted:
        results.append(check_lengths(path, project.clips, profile))
    if "render" in wanted:
        results.append(check_render(project, path, os.path.join(folder, "check"),
                                    width=width, crf=crf, samples=samples))
    if "fade" in wanted:
        # Reuse the render check's own files when they are there: same frames,
        # same encoder, so the two checks cannot disagree about the picture.
        rendered = next((c for c in results if c["name"] == "render" and c["ok"]),
                        {})
        results.append(check_fade(project, path, os.path.join(folder, "check"),
                                  proof=rendered.get("mp4"), wav=rendered.get("wav"),
                                  width=width, crf=crf))
    if "titles" in wanted:
        results.append(check_titles(project, path, os.path.join(folder, "check"),
                                    width=width))

    result = {"plan": plan, "project": project, "path": path, "folder": folder,
              "checks": results, "skipped": skipped}
    guard.write_json(os.path.join(folder, "checks.json"), {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "plan": guard.rel(plan["path"]), "project": guard.rel(path),
        "shotcut": project.shotcut, "mlt": project.mlt,
        "frames": project.length, "skipped": skipped,
        "clips": [{"source": guard.rel(c["source"]), "in": c["in"],
                   "out": c["out"], "frames": c["frames"],
                   "label": c["label"]} for c in project.clips],
        "titles": [{"text": t["text"], "in": t["in"], "out": t["out"],
                    "frames": t["frames"], "position": t["position"],
                    "size": t["size"]} for t in project.titles],
        "checks": results})
    guard.write_text(os.path.join(folder, "digest.txt"), _digest(result))
    return result


def _digest(result):
    plan, project, path = result["plan"], result["project"], result["path"]
    fps = project.profile.fps
    lines = ["cutwright %s  build record" % CUTWRIGHT_VERSION,
             "plan           %s" % guard.rel(plan["path"]),
             "plan sha256    %s" % guard.sha256_file(plan["path"]),
             "project        %s" % guard.rel(path),
             "project sha256 %s" % guard.sha256_file(path),
             "shotcut        %s   (shotcut.exe product version)"
             % project.shotcut,
             "mlt            %s   (melt.exe --version)" % project.mlt,
             "profile        %dx%d, %d/%d fps, colorspace %s"
             % (project.profile.width, project.profile.height,
                project.profile.fps_num, project.profile.fps_den,
                project.profile.colorspace),
             "timeline       %d frames, %.3f s, %d clip(s)"
             % (project.length, project.profile.seconds(project.length),
                len(project.clips))]
    if project.has_fade:
        lines.append("fade           in %d f (%.3f s), out %d f (%.3f s)%s"
                     % (project.fade["in"],
                        project.profile.seconds(project.fade["in"]),
                        project.fade["out"],
                        project.profile.seconds(project.fade["out"]),
                        "" if project.fade["audio"] else ", picture only"))
    lines += ["", "clips"]
    for index, clip in enumerate(project.clips):
        lines.append("  %d  %-11s %-42s %7.3f-%-7.3f frames %d-%d  %d f  %s"
                     % (index, clip["producer"], guard.rel(clip["source"]),
                        clip["in"] / fps, (clip["out"] + 1) / fps,
                        clip["in"], clip["out"], clip["frames"], clip["label"]))
    if project.titles:
        lines += ["", "titles"]
        for index, title in enumerate(project.titles):
            lines.append("  %d  %-11s %-29r frames %d-%d  %d f  %s, %d px, %s"
                         % (index, title["producer"], title["text"],
                            title["at"], title["at"] + title["frames"] - 1,
                            title["frames"], title["position"], title["size"],
                            title["colour"]))
    lines.append("")
    lines.append("checks")
    for check in result["checks"]:
        lines.append("  [%s] %-8s %s" % ("+" if check["ok"] else "!",
                                         check["name"], check["detail"]))
    for name in result["skipped"]:
        lines.append("  [ ] %-8s not run" % name)
    return "\n".join(lines) + "\n"
