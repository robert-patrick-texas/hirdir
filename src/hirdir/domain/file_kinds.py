"""The kinds of file a reference may be, and the check that a file is what it says (P-159).

The kinds that are taken are a setting, `reference_file_types`, a list of extensions an
Admin may change. What hirdir knows of an extension is here: the media type it is
served as, whether a browser shows it in the page, and how its content begins. An
extension an Admin adds that is not known here is kept and served as
`application/octet-stream`, and is downloaded. A web page, a script or a program is
never taken, whatever the setting says, and neither is a file whose content begins as
one does, whatever its name.

This module reads nothing from the database, so that the settings may use it.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

OCTET_STREAM = "application/octet-stream"
# An extension is letters and digits, up to ten of them.
EXTENSION = re.compile(r"[a-z0-9]{1,10}")
# How much of the start of a file the checks read.
HEAD_BYTES = 512


def _starts(*marks: bytes) -> Callable[[bytes], bool]:
    return lambda head: head.startswith(marks)


def _webp(head: bytes) -> bool:
    return head[:4] == b"RIFF" and head[8:12] == b"WEBP"


HEIF_BRANDS = (b"heic", b"heix", b"heim", b"heis", b"hevc", b"hevx", b"mif1", b"msf1", b"avif")


def _heif(head: bytes) -> bool:
    return head[4:8] == b"ftyp" and head[8:12] in HEIF_BRANDS


def _text(head: bytes) -> bool:
    return b"\x00" not in head


ZIP = _starts(b"PK\x03\x04", b"PK\x05\x06")
# The compound file of the Office of before 2007: doc, xls, ppt and vsd.
COMPOUND = _starts(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")


@dataclass(frozen=True)
class Known:
    """What hirdir knows of one extension."""

    media_type: str
    # Whether a browser shows it in the page, as a picture in an <img>.
    shown: bool
    # Whether the start of a file is what this kind of file begins with.
    begins: Callable[[bytes], bool]
    # How the kind is named in a refusal: "a PDF".
    named: str


KNOWN: dict[str, Known] = {
    "jpg": Known("image/jpeg", True, _starts(b"\xff\xd8\xff"), "a JPEG picture"),
    "jpeg": Known("image/jpeg", True, _starts(b"\xff\xd8\xff"), "a JPEG picture"),
    "png": Known("image/png", True, _starts(b"\x89PNG\r\n\x1a\n"), "a PNG picture"),
    "gif": Known("image/gif", True, _starts(b"GIF87a", b"GIF89a"), "a GIF picture"),
    "webp": Known("image/webp", True, _webp, "a WebP picture"),
    "heic": Known("image/heic", False, _heif, "a HEIC picture"),
    "heif": Known("image/heif", False, _heif, "a HEIF picture"),
    "tif": Known("image/tiff", False, _starts(b"II*\x00", b"MM\x00*"), "a TIFF picture"),
    "tiff": Known("image/tiff", False, _starts(b"II*\x00", b"MM\x00*"), "a TIFF picture"),
    "pdf": Known("application/pdf", False, _starts(b"%PDF-"), "a PDF"),
    "doc": Known("application/msword", False, COMPOUND, "a Word document"),
    "docx": Known(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        False,
        ZIP,
        "a Word document",
    ),
    "xls": Known("application/vnd.ms-excel", False, COMPOUND, "an Excel workbook"),
    "xlsx": Known(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        False,
        ZIP,
        "an Excel workbook",
    ),
    "ppt": Known("application/vnd.ms-powerpoint", False, COMPOUND, "a PowerPoint presentation"),
    "pptx": Known(
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        False,
        ZIP,
        "a PowerPoint presentation",
    ),
    "vsd": Known("application/vnd.visio", False, COMPOUND, "a Visio drawing"),
    "vsdx": Known("application/vnd.ms-visio.drawing", False, ZIP, "a Visio drawing"),
    "dwg": Known("image/vnd.dwg", False, _starts(b"AC10", b"AC1."), "a DWG drawing"),
    "dxf": Known(
        "image/vnd.dxf",
        False,
        lambda head: _text(head) or head.startswith(b"AutoCAD Binary DXF"),
        "a DXF drawing",
    ),
    "txt": Known("text/plain", False, _text, "a text file"),
    "csv": Known("text/csv", False, _text, "a text file"),
    "log": Known("text/plain", False, _text, "a text file"),
    "zip": Known("application/zip", False, ZIP, "a ZIP archive"),
}

DEFAULT_TYPES: tuple[str, ...] = tuple(KNOWN)

# A web page, a script or a program: never taken (P-159).
REFUSED: tuple[str, ...] = (
    "htm",
    "html",
    "shtml",
    "xhtml",
    "mht",
    "mhtml",
    "svg",
    "svgz",
    "xml",
    "xsl",
    "xslt",
    "js",
    "mjs",
    "cjs",
    "wasm",
    "swf",
    "exe",
    "msi",
    "msp",
    "dll",
    "com",
    "scr",
    "pif",
    "bat",
    "cmd",
    "ps1",
    "psm1",
    "vbs",
    "vbe",
    "wsf",
    "wsh",
    "hta",
    "jar",
    "apk",
    "app",
    "dmg",
    "deb",
    "rpm",
    "sh",
    "php",
    "py",
    "pl",
    "rb",
    "lnk",
    "reg",
    "msc",
    "cpl",
)

# How a program and a web page begin, whatever their name says. A web page is looked
# for after any byte-order mark and white space, without regard to case.
PROGRAM_MARKS = (b"MZ", b"\x7fELF", b"#!", b"\xca\xfe\xba\xbe", b"\xcf\xfa\xed\xfe")
PAGE_MARKS = (b"<!doctype html", b"<html", b"<script", b"<svg", b"<?xml", b"<head", b"<body")


def extension_of(file_name: str) -> str:
    """Return the extension of a file name, in lower case, or '' where it has none."""
    stem, dot, extension = file_name.rpartition(".")
    return extension.lower() if dot and stem else ""


def media_type(extension: str) -> str:
    """Return the media type a file of this extension is kept and served as."""
    known = KNOWN.get(extension)
    return known.media_type if known else OCTET_STREAM


def shown(extension: str) -> bool:
    """Say whether a file of this extension is a picture the browser shows in the page."""
    known = KNOWN.get(extension)
    return bool(known and known.shown)


def looks_like_a_program_or_a_page(head: bytes) -> str | None:
    """Return what the start of a file says it is, where that is a program or a web
    page, and otherwise None."""
    if head.startswith(PROGRAM_MARKS):
        return "a program"
    text = head.removeprefix(b"\xef\xbb\xbf").lstrip().lower()
    if text.startswith(PAGE_MARKS):
        return "a web page"
    return None


def wrong_content(extension: str, head: bytes) -> str | None:
    """Return why a file of this extension cannot have content that begins with head,
    or None where it may."""
    found = looks_like_a_program_or_a_page(head)
    if found:
        return f"its content is {found}, which is never taken"
    known = KNOWN.get(extension)
    if known and not known.begins(head):
        return f"its content is not {known.named}, as its name says"
    return None
