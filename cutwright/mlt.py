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

The four checks at the bottom are the point of the module. A .mlt that opens is
not the same as a .mlt that edits correctly:

  1. xml      it parses, ids are unique, every reference resolves, and the
              Shotcut/MLT version it records is the installed one
  2. effects  every mlt_service is a name melt.exe itself reports
  3. lengths  every track's frames add up to the tractor's length
  4. render   a small, deliberately ugly render really shows the source frames
              the edit claims -- compared by PSNR against the source, with a
              deliberate mismatch as a control so a passing score means
              something

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

        bglist = ET.SubElement(root, "playlist", {"id": "playlist0"})
        _props(bglist, [("shotcut:name", "Background")])
        ET.SubElement(bglist, "entry", {"producer": "producer0", "in": "0",
                                        "out": last})

        v1 = ET.SubElement(root, "playlist", {"id": "playlist1"})
        _props(v1, [("shotcut:video", "1"), ("shotcut:name", "V1")])
        a1 = ET.SubElement(root, "playlist", {"id": "playlist2"})
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
        ET.SubElement(tractor, "track", {"producer": "playlist2",
                                         "hide": "video"})

        made = [0]

        def transition(service, b_track, **extra):
            el = ET.SubElement(tractor, "transition",
                               {"id": "transition%d" % made[0]})
            made[0] += 1
            pairs = [("a_track", "0"), ("b_track", str(b_track)),
                     ("mlt_service", service), ("always_active", "1")]
            pairs += sorted(extra.items())
            return _props(el, pairs)

        # The pair Shotcut writes for every timeline track. The blend on the
        # bottom video track is disabled, which is what Shotcut does too: V1
        # sits straight on the background, so compositing it is cost with no
        # visible gain -- measured here at 6.9 s vs 4.5 s for 60 frames, and
        # the two differ by 33 dB, i.e. cairo shifts the colour slightly.
        transition("mix", 1, sum="1")
        transition("frei0r.cairoblend", 1, disable="1")
        transition("mix", 2, sum="1")
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
        for entry in playlist.findall("entry"):
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


def _melt_render(path, out_path, opts, limit, first=0, timeout=600):
    """One melt pass over a frame range. Returns (ok, detail, seconds)."""
    cmd = [MELT, path, "in=%d" % first, "out=%d" % limit, "-consumer",
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
        project.length - 1)
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
        project.length - 1)
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
        solo.length - 1)
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
    name = str(plan.get("name") or
               os.path.splitext(os.path.basename(path))[0])
    return {"name": name, "title": str(plan.get("title") or ""),
            "clips": clips, "path": os.path.abspath(path)}


def build(plan_path, out_root=None, width=270, crf=34, samples=3, checks=None):
    """Plan -> .mlt -> the four checks -> a record of all of it on disk.

    `checks` can name a subset while a feature is being added, so a half-built
    feature does not have to pass every gate to be looked at. A check left out
    is recorded as not run, never as passed.
    """
    plan = load_plan(plan_path)
    profile = profile_for(plan["clips"][0]["source"])
    project = Project(plan["name"], profile, title=plan["title"])
    for clip in plan["clips"]:
        project.add_clip(clip["source"], clip["in"], clip["out"], clip["label"])
    folder = guard.ensure_dir(os.path.join(out_root or guard.PROJECTS,
                                          project.name))
    path = project.write(os.path.join(folder, project.name + ".mlt"))

    order = ["xml", "effects", "lengths", "render"]
    wanted = [c.lower() for c in (checks or order)]
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
                len(project.clips)),
             "",
             "clips"]
    for index, clip in enumerate(project.clips):
        lines.append("  %d  %-11s %-42s %7.3f-%-7.3f frames %d-%d  %d f  %s"
                     % (index, clip["producer"], guard.rel(clip["source"]),
                        clip["in"] / fps, (clip["out"] + 1) / fps,
                        clip["in"], clip["out"], clip["frames"], clip["label"]))
    lines.append("")
    lines.append("checks")
    for check in result["checks"]:
        lines.append("  [%s] %-8s %s" % ("+" if check["ok"] else "!",
                                         check["name"], check["detail"]))
    for name in result["skipped"]:
        lines.append("  [ ] %-8s not run" % name)
    return "\n".join(lines) + "\n"
