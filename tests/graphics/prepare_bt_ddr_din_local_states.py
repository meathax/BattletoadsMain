#!/usr/bin/env python3
"""Freeze same-edge DDR state copies for the v20 state-to-DIN timing cone."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PARENT = ROOT / "build/timing_closure_20261011/fg_sprite_controls_v20_private/rtl/ddram.sv"
PARENT_SHA = "ea8b8738afeca05c2dc214cb9a30c946ddb9d3010900ada185d0e180f6987dc9"
EXPECTED_RHS = ["3'h1", "3'h2", "3'h3", "3'h4", "3'h5", "3'h6", "7", "0", "1", "0", "0", "0", "0", "0"]
STATE_DECL = b"\treg  [  2:  0] state = 0;"
LOCAL_DECL = (b"\n\t// Same state D assignments and initialization, local to each 16-bit DDR beat lane.\n"
              b"\t(* preserve, dont_merge *) reg [2:0] din_state_lane[4] = '{4{3'd0}};")
OLD_BEAT = b"""\twire st0_idle_pick = state == 3'h0 && !burst_write_busy && !burst_read_busy;
\twire take_din_bin = !DDRAM_BUSY && state == 3'h1;
\twire take_din_wr  = !DDRAM_BUSY && st0_idle_pick && write_pend;
\twire take_din_io  = !DDRAM_BUSY && st0_idle_pick && !write_pend && !read_busy && io_write_busy;
\t// The three loads are mutually exclusive (state 1 / state 0 with write_pend /
\t// state 0 without write_pend and with io_write_busy). Encode them in two
\t// select bits so every ram_din bit is one 6-input function of its four data
\t// sources (bin, write beat, io beat, hold) and the two selects: the sprite
\t// and write/io data each pass a single LUT.
\t(* keep = "true" *) wire [1:0] din_sel = {take_din_wr || take_din_io, take_din_bin || take_din_io};
\talways @(posedge clk)
\t\tcase (din_sel)
\t\t\t2'd1: ram_din <= bin;
\t\t\t2'd2: ram_din <= {2{write_data_o}};
\t\t\t2'd3: ram_din <= {2{io_write_data_din}};
\t\t\tdefault: ;
\t\tendcase"""
NEW_BEAT = b"""\tgenvar din_lane;
\tgenerate for (din_lane=0; din_lane<4; din_lane=din_lane+1) begin : din_lanes
\t\twire st0_idle_pick = din_state_lane[din_lane] == 3'h0 && !burst_write_busy && !burst_read_busy;
\t\twire take_din_bin = !DDRAM_BUSY && din_state_lane[din_lane] == 3'h1;
\t\twire take_din_wr = !DDRAM_BUSY && st0_idle_pick && write_pend;
\t\twire take_din_io = !DDRAM_BUSY && st0_idle_pick && !write_pend && !read_busy && io_write_busy;
\t\t(* keep = "true" *) wire [1:0] din_sel = {take_din_wr || take_din_io, take_din_bin || take_din_io};
\t\talways @(posedge clk)
\t\t\tcase (din_sel)
\t\t\t\t2'd1: ram_din[din_lane*16 +: 16] <= bin[din_lane*16 +: 16];
\t\t\t\t2'd2: ram_din[din_lane*16 +: 16] <= write_data_o[(din_lane%2)*16 +: 16];
\t\t\t\t2'd3: ram_din[din_lane*16 +: 16] <= io_write_data_din[(din_lane%2)*16 +: 16];
\t\t\t\tdefault: ;
\t\t\tendcase
\tend endgenerate"""
ASSIGNMENT = re.compile(rb"(?m)^([ \t]*)state[ \t]*<=[ \t]*(3'h[0-7]|[0-7])[ \t]*;[ \t]*$")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def replace_once(data: bytes, old: bytes, new: bytes, edits: list[dict]) -> bytes:
    if data.count(old) != 1:
        raise ValueError("Exact unique source guard failed")
    edits.append({"old": base64.b64encode(old).decode(), "new": base64.b64encode(new).decode()})
    return data.replace(old, new, 1)


def reverse(data: bytes, edits: list[dict]) -> bytes:
    for edit in reversed(edits):
        old, new = (base64.b64decode(edit[key], validate=True) for key in ("old", "new"))
        if data.count(new) != 1:
            raise ValueError("Exact unique inverse guard failed")
        data = data.replace(new, old, 1)
    return data


def transform(parent: bytes) -> tuple[bytes, list[dict]]:
    if sha(parent) != PARENT_SHA:
        raise ValueError("Frozen v20 DDR parent hash mismatch")
    newline = b"\r\n" if b"\r\n" in parent else b"\n"
    data = canonical(parent)
    matches = list(ASSIGNMENT.finditer(data))
    if [m.group(2).decode() for m in matches] != EXPECTED_RHS:
        raise ValueError("All fourteen original state assignments must be exact")
    if len(re.findall(rb"\bstate\s*<=", data)) != len(matches):
        raise ValueError("An original state assignment escaped the guard")
    edits: list[dict] = []
    # Walk bottom-to-top so each complete line is still unique at replacement.
    for serial, match in reversed(list(enumerate(matches))):
        old = match.group(0)
        # Repeated state <= 0 lines require a literal contextual guard.
        left = data.rfind(b"\n", 0, max(0, match.start()-1)) + 1
        right = data.find(b"\n", match.end()+1)
        if right < 0:
            right = len(data)
        old = data[left:right]
        target = match.group(0)
        extra = (match.group(1) + b"for (integer din_copy=0; din_copy<4; din_copy=din_copy+1)\n" +
                 match.group(1) + b"\tdin_state_lane[din_copy] <= " + match.group(2) + b";")
        new = old.replace(target, target + b"\n" + extra, 1)
        data = replace_once(data, old, new, edits)
    data = replace_once(data, STATE_DECL, STATE_DECL + LOCAL_DECL, edits)
    data = replace_once(data, OLD_BEAT, NEW_BEAT, edits)
    if reverse(data, edits) != canonical(parent):
        raise ValueError("Complete source inverse failed")
    raw_edits = [{key: base64.b64encode(base64.b64decode(e[key]).replace(b"\n", newline)).decode()
                  for key in ("old", "new")} for e in edits]
    candidate = data.replace(b"\n", newline)
    if reverse(candidate, raw_edits) != parent:
        raise ValueError("Complete raw-byte source inverse failed")
    return candidate, raw_edits


def verify_source(candidate: bytes, edits: list[dict]) -> dict:
    parent = reverse(candidate, edits)
    regenerated, expected_edits = transform(parent)
    if regenerated != candidate or expected_edits != edits:
        raise ValueError("Forward regeneration mismatch")
    data = canonical(candidate)
    old_values = [m.group(2) for m in ASSIGNMENT.finditer(data)]
    copies = re.findall(rb"din_state_lane\[din_copy\]\s*<=\s*(3'h[0-7]|[0-7])\s*;", data)
    if copies != old_values or len(copies) != 14:
        raise ValueError("Same-D literal state induction failed")
    if len(re.findall(rb"din_state_lane\[[^]]+\]\s*<=", data)) != 14:
        raise ValueError("Unexpected replica state write")
    if data.count(b"always @(posedge clk)") != canonical(parent).count(b"always @(posedge clk)"):
        raise ValueError("Clock process count changed")
    if b"din_state_lane[din_copy] <= state" in data:
        raise ValueError("Old-Q pipeline is forbidden")
    return {"scope": "four identical initial state values and all fourteen same-D same-edge assignments; four exact 16-bit case selectors",
            "parent_sha256": sha(parent), "candidate_sha256": sha(candidate), "replica_lanes": 4,
            "bits_per_lane": 16, "state_assignment_sites": 14, "extra_clock_edges": 0,
            "original_state_graph_and_consumers_preserved": True, "full_raw_inverse": True,
            "simulation": "UNRUN", "native_timing": "UNRUN"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Output must be a new directory")
    parent = PARENT.read_bytes()
    candidate, edits = transform(parent)
    proof = verify_source(candidate, edits)
    destination = args.output / "candidate/rtl/ddram.sv"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(candidate)
    manifest = {"schema": "bt-ddr-din-local-states-v1", "status": "PASS_SCOPED_SOURCE_INDUCTION",
                "helper_sha256": sha(Path(__file__).read_bytes()), "parent": str(PARENT),
                "candidate": str(destination), "edits": edits, "proof": proof}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "candidate_sha256": sha(candidate),
                      "manifest": str(args.output / "manifest.json"), "simulation": "UNRUN", "timing": "UNRUN"}))


if __name__ == "__main__":
    main()
