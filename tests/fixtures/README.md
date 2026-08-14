# Test fixtures

`eqlog_Kenkyo_freeport.txt` — a real EverQuest Legends log capture,
vendored from kpxcoolx/eql-meter (MIT), `samples/` directory. Used by
`scripts/parser_coverage.py` as a regression corpus for the log parser:
if an event category drops to zero against this file after a parser
change, the change broke a format we used to handle.

`inventory_extended_storage.tsv` — a sanitized inventory-export slice. Its
location labels and nesting follow real EQL output; item names and IDs are
generic test data.
