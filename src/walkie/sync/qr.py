"""QR codes for the LAN sync server.

`walkie serve` prints a QR encoding the landing-page URL so the phone can
scan it with the camera instead of typing `http://<ip>:<port>/`. Pure-Python
(`segno`) — no image libraries, renders straight to terminal blocks.
"""

from __future__ import annotations

from io import StringIO

import segno

# Error-correction level "M" balances density against a smudged/screen photo.
_ERROR_LEVEL = "m"


def qr_blocks(url: str) -> str:
    """Render `url` as a QR code using half-block characters for a terminal.

    Each output line packs two QR rows into one line using ▀ ▄ █, so the
    code is roughly half as tall as it is wide and reads well on a laptop
    screen the phone is pointed at.
    """
    qr = segno.make(url, error=_ERROR_LEVEL)
    buf = StringIO()
    qr.terminal(out=buf, compact=True)
    return buf.getvalue().rstrip("\n")
