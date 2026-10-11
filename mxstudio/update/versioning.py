"""Version parsing for the updater.

Rule: only a strictly newer release is ever offered (no silent downgrade through a
replayed old manifest); a pre-release ("0.3.0-rc.1") sorts before its final release.
"""
from __future__ import annotations

import re

_VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.]+))?$")


def parse(version: str) -> tuple:
    match = _VERSION.match(str(version).strip())
    if not match:
        raise ValueError(f"not a version: {version!r}")
    major, minor, patch, pre = match.groups()
    # final releases sort after any pre-release of the same triple
    pre_key: tuple = (1,) if pre is None else (0, *[(0, int(p)) if p.isdigit() else (1, p) for p in pre.split(".")])
    return (int(major), int(minor), int(patch), pre_key)


def is_valid(version: str) -> bool:
    return bool(_VERSION.match(str(version).strip()))


def is_newer(candidate: str, current: str) -> bool:
    return parse(candidate) > parse(current)
