#!/usr/bin/env python3
"""Generate the direct_nodes() table for src/modern.cpp from full_mapping.json."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FULL = json.load(open(os.path.join(HERE, "full_mapping.json")))

def esc(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


lines = []
lines.append("const std::map<std::string, std::string> &direct_nodes()")
lines.append("{")
lines.append("\tstatic const std::map<std::string, std::string> m = {")
for k in sorted(FULL):
    lines.append(f'\t\t{{"{esc(k)}", "{esc(FULL[k])}"}},')
lines.append("\t};")
lines.append("\treturn m;")
lines.append("}")
lines.append("")

body = "\n".join(lines)
print(f"table entries: {len(FULL)}")
open(os.path.join(HERE, "direct_nodes.txt"), "w").write(body)
print("written", os.path.join(HERE, "direct_nodes.txt"))
