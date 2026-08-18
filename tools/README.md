# Mapping generation tools

`src/modern.cpp` contains the full Minecraft 1.21+ → Mineclonia block mapping used
by the converter. It is generated from these tools so the mapping can be reviewed
and regenerated.

## Files

- `mc_blocks.txt` — one Minecraft block id per line (namespace stripped), covering
  the full 1.21.x block set.
- `mcl_all_nodes.txt` — one Mineclonia node name per line, collected from the
  installed game's `mcl_*` mods (string literals found in the Lua sources).
- `gen_mapping.py` — builds the mapping from those two lists, applying the
  family rules (woods, colors, stairs, slabs, walls, doors, beds, candles, …).
  Writes `full_mapping.json`.
- `gen_cpp.py` — turns `full_mapping.json` into the `direct_nodes()` table body
  written to `direct_nodes.txt`.

## Usage

```bash
python3 tools/gen_mapping.py   # -> tools/full_mapping.json
python3 tools/gen_cpp.py       # -> tools/direct_nodes.txt
```

Then splice the generated `direct_nodes()` function into `src/modern.cpp`
(it must be an exact match with the checked-in table — the converter relies on it).
