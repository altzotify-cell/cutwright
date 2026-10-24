"""Write guard + provenance helpers.

Every file Cutwright creates passes through write_text / write_json, so the one
invariant that actually matters is enforced in exactly one place:

  * nothing is ever written inside either ORIGINAL project folder
  * nothing is ever written outside this fork

The originals are read-only inputs. They may be read, hashed, probed and
referenced by absolute path. They are never modified, and no media is ever
copied out of them -- footage is always referenced where it already lives.

This mirrors the house pattern in recap.py (ROOT is self-derived, relative
dirs, plain os.path) with one addition: recap.py chdir()s into its own folder,
which is fine for a single-project engine but wrong for a tool that is handed
absolute paths to files elsewhere. So Cutwright never chdir()s; it resolves
everything against ROOT explicitly.
"""
import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Absolute paths of the two projects this fork was taken from. Read only.
ORIGINALS = (
    r"C:\Users\user\Downloads\RecapStudio_v2_ui_videopad",
    r"C:\Users\user\Downloads\videopad",
)

VENDOR = os.path.join(ROOT, "vendor")
OUT = os.path.join(ROOT, "out")
PROJECTS = os.path.join(ROOT, "projects")
MANIFEST = os.path.join(VENDOR, "MANIFEST.sha256")


class GuardError(PermissionError):
    """Raised when something tries to write outside the fork or into an original."""


def norm(path):
    return os.path.normcase(os.path.abspath(path))


def is_inside(path, parent):
    p, q = norm(path), norm(parent)
    return p == q or p.startswith(q.rstrip(os.sep) + os.sep)


def rel(path):
    """Path relative to ROOT when it is inside it, else the absolute path."""
    try:
        if is_inside(path, ROOT):
            return os.path.relpath(os.path.abspath(path), ROOT)
    except ValueError:
        pass
    return os.path.abspath(path)


def assert_writable(path):
    """The invariant. Returns the absolute path, or raises GuardError."""
    for original in ORIGINALS:
        if is_inside(path, original):
            raise GuardError(
                "refusing to write inside an original project folder: %s" % path)
    if not is_inside(path, ROOT):
        raise GuardError(
            "refusing to write outside the Cutwright folder (%s): %s" % (ROOT, path))
    return os.path.abspath(path)


def ensure_dir(path):
    assert_writable(path)
    os.makedirs(path, exist_ok=True)
    return os.path.abspath(path)


def write_text(path, text, encoding="utf-8"):
    assert_writable(path)
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding=encoding, newline="\n") as f:
        f.write(text)
    return os.path.abspath(path)


def write_bytes(path, data):
    """Byte-for-byte write, for artifacts that must stay identical to what a
    tool produced (a transcript copy, for instance). Same guard, no newline
    normalisation."""
    assert_writable(path)
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return os.path.abspath(path)


def write_json(path, data):
    return write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


# ---------------------------------------------------------------------------
# provenance: hash code/text fully, media by size + mtime only (a 4 GB film
# would take minutes to hash and would tell us nothing new)
# ---------------------------------------------------------------------------
def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sig(path):
    """(size, mtime_ns) -- cheap identity for media that must not be copied."""
    st = os.stat(path)
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns}


def build_manifest(folder, exts=None):
    """[{sha256, rel, size}] for every file under folder."""
    rows = []
    for dirpath, _dirs, files in os.walk(folder):
        for name in sorted(files):
            full = os.path.join(dirpath, name)
            if exts and os.path.splitext(name)[1].lower() not in exts:
                continue
            if name == "MANIFEST.sha256":
                continue
            rows.append({"sha256": sha256_file(full),
                         "rel": os.path.relpath(full, folder).replace("\\", "/"),
                         "size": os.path.getsize(full)})
    rows.sort(key=lambda r: r["rel"])
    return rows
