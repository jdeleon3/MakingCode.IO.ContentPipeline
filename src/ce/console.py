"""Console output helpers.

Deliberately dependency-free and defensive about Windows terminals.

Two things bite on Windows and both are handled here:

1. Encoding. A legacy `cmd.exe` runs cp1252 and raises UnicodeEncodeError on
   check marks. We detect the stream encoding and fall back to ASCII glyphs.
2. Colour. ANSI sequences are only honoured on Windows once virtual terminal
   processing is enabled. We try to enable it; if that fails, colour is off.

Nothing here should ever raise. Output helpers that can crash a CLI are worse
than plain text.
"""

from __future__ import annotations

import os
import sys
from typing import TextIO

# --------------------------------------------------------------------------
# Capability detection
# --------------------------------------------------------------------------


def _enable_windows_vt() -> bool:
    """Turn on ANSI escape handling for the current console. Returns success."""
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        # -11 = STD_OUTPUT_HANDLE, 0x4 = ENABLE_VIRTUAL_TERMINAL_PROCESSING
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x4))
    except Exception:
        return False


def supports_unicode(stream: TextIO | None = None) -> bool:
    stream = stream or sys.stdout
    if os.environ.get("CE_ASCII"):
        return False
    encoding = (getattr(stream, "encoding", None) or "").lower()
    return "utf" in encoding


def supports_color(stream: TextIO | None = None) -> bool:
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR") or os.environ.get("CE_NO_COLOR"):
        return False
    if not hasattr(stream, "isatty") or not stream.isatty():
        return False
    return _enable_windows_vt()


UNICODE = supports_unicode()
COLOR = supports_color()

# --------------------------------------------------------------------------
# Glyphs and colour
# --------------------------------------------------------------------------

OK = "✓" if UNICODE else "OK"
FAIL = "✗" if UNICODE else "XX"
WARN = "△" if UNICODE else "!!"
BULLET = "•" if UNICODE else "-"
ARROW = "→" if UNICODE else "->"

_CODES = {
    "green": "\033[32m",
    "red": "\033[31m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "dim": "\033[2m",
    "bold": "\033[1m",
    "reset": "\033[0m",
}


def paint(text: str, color: str) -> str:
    if not COLOR or color not in _CODES:
        return text
    return f"{_CODES[color]}{text}{_CODES['reset']}"


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

_VERBOSE = False


def set_verbose(value: bool) -> None:
    global _VERBOSE
    _VERBOSE = value


def is_verbose() -> bool:
    return _VERBOSE


def _write(stream: TextIO, text: str) -> None:
    """Write, degrading to ASCII rather than raising on a hostile codepage.

    Flushes every line. stdout is block-buffered when piped while stderr is
    not, so without this the summary written to stderr appears *above* the
    report written to stdout whenever output is redirected.
    """
    try:
        print(text, file=stream, flush=True)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"), file=stream, flush=True)


def out(text: str = "") -> None:
    _write(sys.stdout, text)


def err(text: str = "") -> None:
    _write(sys.stderr, text)


def success(text: str) -> None:
    out(f"{paint(OK, 'green')} {text}")


def failure(text: str) -> None:
    err(f"{paint(FAIL, 'red')} {text}")


def warn(text: str) -> None:
    err(f"{paint(WARN, 'yellow')} {text}")


def info(text: str) -> None:
    out(f"{BULLET} {text}")


def hint(text: str) -> None:
    err(paint(f"  {ARROW} {text}", "dim"))


def debug(text: str) -> None:
    if _VERBOSE:
        err(paint(f"  [debug] {text}", "dim"))


def heading(text: str) -> None:
    out()
    out(paint(text, "bold"))
    out(paint("-" * len(text), "dim"))
