#!/usr/bin/env python3
"""Factor the original pixel priorities into a parallel three-source selection."""
import argparse
import base64
import hashlib
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PARENT = ROOT / "build/timing_closure_20261011/fg_sprite_controls_v20_private/rtl/BT.sv"
PARENT_SHA = "e24c7e25743b00be2061d0767ba5785c745bc7def07deae3fc55c1f01384ff71"
DECL = b"\tbit [ 7:0] PIX_OUT;"
CASE = b"\t\t\tcase (DISP_CONTROL[9:8])"
CASE_END = b"\n\t\t\tendcase"
FUNCTION = b"""\t// Parallel source masks preserve the original per-mode pixel priorities.
\tfunction automatic bit [7:0] BT_SELECT_PIXEL;
\t\tinput logic [1:0] mode;
\t\tinput bit [7:0] spr, bg0, bg1, previous;
\t\tinput logic [2:0] enabled;
\t\tbit spr_nz, spr_low, spr_high, bg0_nz, bg1_nz, bg1_high;
\t\tbit bg0_enabled, bg1_enabled, take_spr, take_bg0, take_bg1, valid;
\t\tbegin
\t\t\tspr_nz = spr && enabled[2];
\t\t\tspr_low = spr && !spr[7] && enabled[2];
\t\t\tspr_high = spr[7] && enabled[2];
\t\t\tbg0_nz = bg0 && enabled[0];
\t\t\tbg1_nz = bg1 && enabled[1];
\t\t\tbg1_high = bg1[7] && enabled[1];
\t\t\tbg0_enabled = enabled[0];
\t\t\tbg1_enabled = enabled[1];
\t\t\ttake_spr = 0; take_bg0 = 0; take_bg1 = 0; valid = 1;
\t\t\tcase (mode)
\t\t\t\t2'b00: begin
\t\t\t\t\ttake_spr = spr_low || (!bg1_high && spr_nz);
\t\t\t\t\ttake_bg1 = !spr_low && (bg1_high || (!spr_nz && bg1_nz));
\t\t\t\t\ttake_bg0 = !spr_nz && !bg1_nz && bg0_enabled;
\t\t\t\tend
\t\t\t\t2'b01: begin
\t\t\t\t\ttake_spr = spr_low || (!bg0_nz && !bg1_high && spr_nz);
\t\t\t\t\ttake_bg0 = !spr_low && bg0_nz;
\t\t\t\t\ttake_bg1 = !spr_low && !bg0_nz && (bg1_high || (!spr_nz && bg1_enabled));
\t\t\t\tend
\t\t\t\t2'b10: begin
\t\t\t\t\ttake_spr = spr_nz;
\t\t\t\t\ttake_bg1 = !spr_nz && bg1_nz;
\t\t\t\t\ttake_bg0 = !spr_nz && !bg1_nz && bg0_enabled;
\t\t\t\tend
\t\t\t\t2'b11: begin
\t\t\t\t\ttake_bg1 = bg1_high || (!spr_high && bg1_nz);
\t\t\t\t\ttake_spr = !bg1_high && (spr_high || (!bg1_nz && spr_nz));
\t\t\t\t\ttake_bg0 = !spr_nz && !bg1_nz && bg0_enabled;
\t\t\t\tend
\t\t\t\tdefault: valid = 0;
\t\t\tendcase
\t\t\tBT_SELECT_PIXEL = previous;
\t\t\tif (valid) BT_SELECT_PIXEL = (spr & {8{take_spr}}) |
\t\t\t                              (bg0 & {8{take_bg0}}) |
\t\t\t                              (bg1 & {8{take_bg1}});
\t\tend
\tendfunction

"""
CALL = b"\t\t\tPIX_OUT <= BT_SELECT_PIXEL(DISP_CONTROL[9:8], SPR_PIX, BG0_PIX, BG1_PIX, PIX_OUT, BG_EN);"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(data):
    return data.replace(b"\r\n", b"\n")


def forward(data, edits):
    for edit in edits:
        before, after = (base64.b64decode(edit[key], validate=True) for key in ("old", "new"))
        if data.count(before) != 1:
            raise ValueError("Exact unique pixel forward guard failed")
        data = data.replace(before, after, 1)
    return data


def reverse(data, edits):
    for edit in reversed(edits):
        before, after = (base64.b64decode(edit[key], validate=True) for key in ("old", "new"))
        if data.count(after) != 1:
            raise ValueError("Exact unique pixel inverse guard failed")
        data = data.replace(after, before, 1)
    return data


def transform(parent):
    if sha(parent) != PARENT_SHA:
        raise ValueError("Frozen v20 BT parent required")
    text = canonical(parent)
    if text.count(DECL) != 1 or text.count(CASE) != 1 or b"BT_SELECT_PIXEL" in text:
        raise ValueError("Exact pixel process anchors required")
    first = text.index(CASE)
    last = text.index(CASE_END, first) + len(CASE_END)
    old_case = text[first:last]
    if old_case.count(b"PIX_OUT <=") != 22 or old_case.count(b"2'b") != 4:
        raise ValueError("Complete original four-mode priority block required")
    newline = b"\r\n" if b"\r\n" in parent else b"\n"
    edits = [{"old": base64.b64encode(before.replace(b"\n", newline)).decode(),
              "new": base64.b64encode(after.replace(b"\n", newline)).decode()}
             for before, after in ((DECL, FUNCTION + DECL), (old_case, CALL))]
    candidate = forward(parent, edits)
    if reverse(candidate, edits) != parent:
        raise ValueError("Whole-file raw-byte pixel inverse failed")
    return candidate, edits


def winner(mode, spr_class, bg0_nonzero, bg1_class, enabled):
    spr = enabled[2] and spr_class != 0
    low = spr and spr_class == 1
    high = spr and spr_class == 2
    b0 = enabled[0] and bg0_nonzero
    b1 = enabled[1] and bg1_class != 0
    b1_high = enabled[1] and bg1_class == 2
    # Independent transcription of the immutable original if/else priority lists.
    if mode == 0:
        priorities = ((low, 1), (b1_high, 3), (spr, 1), (b1, 3), (enabled[0], 2))
    elif mode == 1:
        priorities = ((low, 1), (b0, 2), (b1_high, 3), (spr, 1), (enabled[1], 3))
    elif mode == 2:
        priorities = ((spr, 1), (b1, 3), (enabled[0], 2))
    else:
        priorities = ((b1_high, 3), (high, 1), (b1, 3), (spr, 1), (enabled[0], 2))
    return next((source for condition, source in priorities if condition), 0)


def masks(mode, spr_class, bg0_nonzero, bg1_class, enabled):
    s = bool(enabled[2] and spr_class)
    lo = bool(s and spr_class == 1)
    hi = bool(s and spr_class == 2)
    b0 = bool(enabled[0] and bg0_nonzero)
    b1 = bool(enabled[1] and bg1_class)
    h1 = bool(b1 and bg1_class == 2)
    if mode == 0:
        return lo or (not h1 and s), not s and not b1 and enabled[0], not lo and (h1 or (not s and b1))
    if mode == 1:
        return lo or (not b0 and not h1 and s), not lo and b0, not lo and not b0 and (h1 or (not s and enabled[1]))
    if mode == 2:
        return s, not s and not b1 and enabled[0], not s and b1
    return not h1 and (hi or (not b1 and s)), not s and not b1 and enabled[0], h1 or (not hi and b1)


def verify_source(candidate, edits):
    parent = reverse(candidate, edits)
    actual, actual_edits = transform(parent)
    if actual != candidate or actual_edits != edits:
        raise ValueError("Pixel forward reproduction failed")
    count = 0
    for mode, spr, b0, b1, en in itertools.product(range(4), range(3), range(2), range(3), itertools.product((0, 1), repeat=3)):
        select = masks(mode, spr, b0, b1, en)
        expected = winner(mode, spr, b0, b1, en)
        if sum(bool(x) for x in select) > 1 or select != tuple(expected == source for source in (1, 2, 3)):
            raise ValueError("Universal source-identity priority proof failed")
        count += 1
    if count != 576:
        raise ValueError("Complete predicate-domain coverage required")
    return {"scope": "All576 priority/predicate classes, source identity and onehot-or-zero; unchanged8-bit transfers/capture/reset/local bit conversions",
            "parent_sha256": sha(parent), "candidate_sha256": sha(candidate), "priority_classes": count,
            "extra_clock_edges": 0, "complete_raw_inverse": True, "simulation": "UNRUN", "timing": "UNRUN"}


def pixel_fragment(data):
    text = canonical(data)
    start = text.index(DECL)
    ending = b"\n\t\tend\n\tend"
    case_start = text.index(CASE, start) if CASE in text[start:] else text.index(CALL, start)
    end = text.index(ending, case_start) + len(ending)
    prefix = FUNCTION if b"BT_SELECT_PIXEL" in text else b""
    return prefix + text[start:end] + b"\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Pixel output must be a new directory")
    candidate, edits = transform(PARENT.read_bytes())
    proof = verify_source(candidate, edits)
    destination = args.output / "candidate/rtl/BT.sv"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(candidate)
    document = {"schema": "bt-parallel-pixel-source-edge-v1", "status": "PASS_SCOPED_SOURCE_IDENTITY",
                "helper_sha256": sha(Path(__file__).read_bytes()), "candidate": str(destination),
                "proof": proof, "edits": edits}
    (args.output / "manifest.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": document["status"], "candidate_sha256": sha(candidate), "manifest": str(args.output / "manifest.json")}))


if __name__ == "__main__":
    main()
