# Notices and credits

WarCounsel is MIT licensed (see [LICENSE](LICENSE)). This file
records the third-party material bundled or vendored here, and the
project's relationship to the game.

## Vendored material, with thanks

- Community-measured spell durations and raid triggers in
  backend/alert_data.py, and the real-log test fixture under tests/fixtures/,
  derive from kpxcoolx/eql-alerts and kpxcoolx/eql-meter (MIT).
- Zone travel and translocator/ritual routing data in backend/map_system.py
  follows rari/eqltools (CC0).
- The item acquisition extraction approach in backend/game_data.py follows
  DavisChappins/eql-tooltip (MIT).
- The weapon damage-bonus model in backend/game_data.py follows
  xaziaver/eql-weapon-inflection-analyzer (MIT).
- Packaged builds may embed a copy of the eqlbuilds dataset snapshot from
  ArtSabintsev/everquest-legends-mcp (MIT).

## Trademarks

EverQuest and EverQuest Legends are trademarks of their respective owners.
This project is an unaffiliated, passive, read-only companion: it parses log
files the game itself writes, and does not modify, inject into, or automate
the game.
