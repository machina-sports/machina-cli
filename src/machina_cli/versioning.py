"""Small dependency-free version comparison for release/update checks."""

from __future__ import annotations

import re

_PRERELEASE_RANK = {"dev": 0, "a": 1, "alpha": 1, "b": 2, "beta": 2, "pre": 3, "rc": 3}


def version_key(value: str) -> tuple[tuple[int, ...], int, int]:
    """Return an ordering key for common SemVer/PEP 440 release tags.

    Final releases sort after their dev/alpha/beta/rc builds. Missing release
    components are padded so 1.2 and 1.2.0 compare equally.
    """
    cleaned = value.strip().lower().lstrip("v").split("+", 1)[0]
    match = re.match(r"^(\d+(?:\.\d+)*)(.*)$", cleaned)
    if not match:
        return ((0, 0, 0, 0), 0, 0)

    release = tuple(int(part) for part in match.group(1).split("."))
    release = (release + (0, 0, 0, 0))[:4]
    suffix = match.group(2).lstrip(".-_+")
    if not suffix or suffix.startswith("+"):
        return (release, 4, 0)

    pre = re.search(r"(dev|alpha|beta|pre|rc|a|b)[.-]?(\d*)", suffix)
    if not pre:
        return (release, 0, 0)
    return (release, _PRERELEASE_RANK[pre.group(1)], int(pre.group(2) or 0))


def is_newer(candidate: str, current: str) -> bool:
    return version_key(candidate) > version_key(current)
