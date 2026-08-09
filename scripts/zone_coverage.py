"""Zone coverage runner — checks ZONE_FILES/ZONE_ALIASES against the game's
own zone list.

Usage (repo root):  python scripts/zone_coverage.py [game_dir]

The client ships `Resources/ZoneNames.txt`: one row per zone, `id^long
name^lo^hi`, where the long name is EXACTLY what "You have entered X." logs
and the level fields are 0^0 for every zone EQL does not run. That makes it
the authoritative roster — 77 live zones at launch — and the only way to
find a zone we cannot chart BEFORE a player walks into it and sees an empty
panel. "The Ruins of Old Paineel" (The Hole) was reported that way.

Reports, for every live zone:
  MISS   — no ZONE_FILES/ZONE_ALIASES entry resolves the name at all
  NOFILE — resolves, but no candidate file exists in maps/ or as a .s3d
A MISS is a bug in this table. NOFILE is usually fine — most dungeons ship
no stock chart, and .eqg zones have no .s3d to extract — so it prints what
IS available (chart / 3D / neither) rather than a bare failure.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.map_system import ZONE_FILES, _canonical, _maps_dirs  # noqa: E402


def live_zones(game_dir: str) -> list[tuple[str, str]]:
    path = os.path.join(game_dir, "Resources", "ZoneNames.txt")
    if not os.path.exists(path):
        print(f"no zone list at {path}")
        return []
    out = []
    with open(path, encoding="cp1252", errors="replace") as f:
        for line in f:
            parts = line.rstrip("\n").split("^")
            # lo == 0 marks a zone the client knows of but does not run
            if len(parts) >= 4 and parts[2] not in ("0", ""):
                out.append((parts[0], parts[1]))
    return out


def main() -> None:
    from backend.config import settings

    game_dir = sys.argv[1] if len(sys.argv) > 1 else str(settings.eql_game_dir)
    zones = live_zones(game_dir)
    if not zones:
        sys.exit(1)
    print(f"{len(zones)} live zones in {game_dir}")

    misses, nofile, ok = [], [], 0
    for zid, name in zones:
        key = _canonical(name)
        cands = ZONE_FILES.get(key or "", [])
        if not cands:
            misses.append((zid, name))
            continue
        chart = [c for c in cands
                 if any((d / f"{c}.txt").exists() for d in _maps_dirs())]
        mesh = [c for c in cands
                if os.path.exists(os.path.join(game_dir, f"{c}.s3d"))]
        if not chart and not mesh:
            nofile.append((zid, name, cands))
        else:
            ok += 1
            have = "+".join(x for x in ("chart" if chart else "",
                                        "3D" if mesh else "") if x)
            print(f"  ok   {name:<38} -> {key!r} ({have})")

    for zid, name, cands in nofile:
        print(f"  NOFILE {name:<36} -> candidates {cands} - nothing on disk")
    for zid, name in misses:
        print(f"  MISS  id {zid:>4}  {name!r} - add to ZONE_FILES/ZONE_ALIASES")

    print(f"\n{ok} charted or meshed, {len(nofile)} no files, {len(misses)} unresolved")

    zem_bad = check_zem_bridge()
    sys.exit(1 if (misses or zem_bad) else 0)


def check_zem_bridge() -> list:
    """Every zone the hunting sheet names must resolve to a map key.

    Two features meet here and used to miss each other entirely: the
    leveling chart recommends zones by the sheet's WIKI spelling, and
    routing/charting key on the GAME's. A name that does not bridge can be
    recommended and then not routed to, and the zone you are standing in
    reads as "not in the sheet" while its row sits there under another
    spelling. Nine zones were in that state until 2026-08-09.
    """
    import asyncio
    from backend.game_data import zem_zone_levels
    from backend.map_system import _canonical

    print("\n=== hunting sheet -> map keys ===")
    try:
        table = asyncio.run(zem_zone_levels())
    except Exception as e:      # offline and no snapshot: not this test's job
        print(f"  (sheet unavailable: {e})")
        return []
    bad = [z for z in table if _canonical(z) is None]
    for z in bad:
        print(f"  UNBRIDGED {z!r} - the chart can suggest it, nothing can "
              f"route to it. Add to ZONE_ALIASES.")
    print(f"  {len(table) - len(bad)}/{len(table)} sheet zones resolve")
    return bad


if __name__ == "__main__":
    main()
