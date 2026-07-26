#!/usr/bin/env python3
"""Refresh the vendored Recommended-Levels snapshot (backend/zem_levels.wiki).

The live wiki is still the primary source; this snapshot is the fallback for
when the fetch fails -- offline, wiki down, or a packaged .exe on a fresh
machine. That case is not cosmetic: _gate_locations() reads an empty table
as "no table" and lets the model's zone picks through UNGATED, so without a
snapshot the location verifier quietly switches itself off.

Stored as raw WIKITEXT rather than markdown on purpose: it is byte-identical
to what the live URL serves, so _parse_zem_wikitext() reads both with one
tested parser and there is no second format to keep in step.

Run from the repo root:  python scripts/refresh_zem.py
"""
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.game_data import ZEM_RAW_URL, _parse_zem_wikitext  # noqa: E402

DEST = Path(__file__).resolve().parents[1] / "backend" / "zem_levels.wiki"


def main() -> int:
    old = _parse_zem_wikitext(DEST.read_text(encoding="utf-8")) if DEST.is_file() else {}
    req = urllib.request.Request(ZEM_RAW_URL, headers={"User-Agent": "WarCounsel"})
    try:
        text = urllib.request.urlopen(req, timeout=30).read().decode("utf-8")
    except Exception as exc:
        print(f"fetch failed: {exc}")
        return 1

    new = _parse_zem_wikitext(text)
    if not new:
        print("refused: the fetched page parses to ZERO zones "
              "(page moved or its table shape changed) -- snapshot untouched")
        return 1
    if len(new) < len(old) * 0.75:
        print(f"refused: {len(new)} zones is a big drop from the current "
              f"{len(old)} -- eyeball the page before overwriting")
        return 1

    DEST.write_text(text, encoding="utf-8")
    gained, lost = sorted(set(new) - set(old)), sorted(set(old) - set(new))
    print(f"wrote {DEST.relative_to(Path.cwd()) if DEST.is_relative_to(Path.cwd()) else DEST}"
          f" — {len(text):,} bytes, {len(new)} in-era zones (was {len(old)})")
    if gained:
        print("  added:   " + ", ".join(gained))
    if lost:
        print("  removed: " + ", ".join(lost))
    if not gained and not lost:
        print("  no zone-level changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
