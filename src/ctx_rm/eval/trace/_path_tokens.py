"""Path-token detection helpers shared by the reference graph.

`is_path_like` answers "does this string look like a filesystem path
token worth stripping from quote content?". `strip_path_segments`
replaces every path-like run inside a larger text with a single space
so downstream substring/token matching does not see path noise.

The regex matches runs that (a) start at a whitespace/quote/bracket
boundary or at one of `= : , {` used in tool-arg serialization,
(b) optionally begin with `~/`, `./`, `../`, or `/`, and (c) contain at
least two `[A-Za-z0-9._-]+` segments joined by `/`. It is deliberately
loose because we would rather over-strip path noise than miss it. The
quote rule re-gates on other criteria.
"""
from __future__ import annotations

import re

# One or more path segments separated by /, where each segment can
# contain [A-Za-z0-9._-]+. Must contain at least one slash.
_PATH_RE = re.compile(
    r"""
    (?:^|(?<=[\s"'`(\[<=:,{]))      # start-of-line or whitespace/quote boundary
    (?:~/|\.{1,2}/|/)?              # optional ~/, ./, ../, /
    [A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+   # at least one / between segments
    """,
    re.VERBOSE,
)


def is_path_like(s: str) -> bool:
    """True iff s looks like a filesystem path token in isolation."""
    if not s or "/" not in s:
        return False
    if len(s) < 5:
        return False
    stripped = s.strip()
    return bool(_PATH_RE.fullmatch(stripped))


def strip_path_segments(text: str) -> str:
    """Replace every path-looking run in text with a single space.

    The goal is that after stripping, neither substring matching nor
    token extraction can re-discover the path's distinctive identifiers.
    We replace with " " rather than "" so word boundaries remain intact.
    """
    return _PATH_RE.sub(" ", text)
