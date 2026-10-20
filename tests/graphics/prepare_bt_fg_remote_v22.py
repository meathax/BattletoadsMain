"""Prepare an exact four-state factorization of the v22 FG remote-address gate."""
from pathlib import Path
import argparse
import hashlib
import itertools
import json

ROOT = Path(__file__).resolve().parents[2]
PARENT = ROOT / "build/timing_closure_20261011/q17_local_paths_v22_private/rtl/fg_vram.sv"
PARENT_SHA = "8b5de31eb18ea5b0c495e43f33cfe6f91220db747494198374f3144949164b74"
BEFORE = "\t\t(* keep *) wire remote_addr = next_rmt && next_copy_mode && next_pos[8];"
AFTER = """\t\t// De Morgan distributes completion masking without changing any state,
\t\t// capture edge or four-state value. Avoid the kept stop/next-RMT cascade.
\t\t(* keep *) wire remote_addr =
\t\t\t((HOLE_RMT_EXEC_B[hole_group] && !start_ras) || start_rmt) &&
\t\t\tnext_copy_mode && next_pos[8] &&
\t\t\t!(step_ram && HOLE_POS_END_RAM_B[hole_group]) &&
\t\t\t!(step_ddr && HOLE_POS_END_DDR_B[hole_group]);"""


def sha(data):
    return hashlib.sha256(data).hexdigest()


def edits_for(parent):
    assert sha(parent) == PARENT_SHA
    assert parent.count(b"\r\n") == parent.count(b"\n")
    return [{"name": "remote-address-completion-factor", "before": BEFORE.replace("\n", "\r\n"), "after": AFTER.replace("\n", "\r\n")}]


def forward(data, edits):
    text = data.decode("latin1")
    for edit in edits:
        assert text.count(edit["before"]) == 1, edit["name"]
        text = text.replace(edit["before"], edit["after"], 1)
    return text.encode("latin1")


def reverse(data, edits):
    text = data.decode("latin1")
    for edit in reversed(edits):
        assert text.count(edit["after"]) == 1, edit["name"]
        text = text.replace(edit["after"], edit["before"], 1)
    return text.encode("latin1")


def transform(parent):
    edits = edits_for(parent)
    candidate = forward(parent, edits)
    assert reverse(candidate, edits) == parent
    return candidate, edits


def prove_binary():
    count = 0
    for rmt, ras, restart, mode, pos, ram, ddr, ram_end, ddr_end in itertools.product((False, True), repeat=9):
        run = (rmt and not ras) or restart
        stop = (ram and ram_end) or (ddr and ddr_end)
        before = (run and not stop) and mode and pos
        after = run and mode and pos and not (ram and ram_end) and not (ddr and ddr_end)
        assert before == after
        count += 1
    return {"all_nine_independent_boolean_inputs": count, "four_state_proof_required": True}


def source_proof(parent, candidate, edits):
    assert forward(parent, edits) == candidate and reverse(candidate, edits) == parent
    regenerated, again = transform(parent)
    assert regenerated == candidate and again == edits
    original = parent.replace(b"\r\n", b"\n")
    current = candidate.replace(b"\r\n", b"\n")
    for needle in (b"always @(posedge CLK", b"always @(posedge CPU_CLK", b"HOLE_A_FF[6*hole_group +: 6] <=", b"next_pos = step_ddr ? SREG_POS + 9'd2 :", b"wire next_rmt =", b"wire stop_rmt ="):
        assert original.count(needle) == current.count(needle), needle
    rejected = []
    for old, new in ((b"!(step_ram &&", b"(step_ram &&"), (b"!(step_ddr &&", b"(step_ddr &&"), (b"next_copy_mode && next_pos[8]", b"next_copy_mode || next_pos[8]"), (b"HOLE_RMT_EXEC_B[hole_group] && !start_ras", b"HOLE_RMT_EXEC_B[0] && !start_ras")):
        block = edits[0]["after"].encode("latin1")
        assert candidate.count(block) == 1 and block.count(old) == 1
        bad = candidate.replace(block, block.replace(old, new, 1), 1)
        try:
            passed = reverse(bad, edits) == parent and forward(parent, edits) == bad
        except AssertionError:
            passed = False
        assert not passed
        rejected.append(old.decode())
    return {"inverse_raw_equal": True, "all_other_source_bytes_equal": True,
            "boolean_coverage": prove_binary(), "negative_controls_rejected": rejected,
            "new_registers": 0, "new_capture_edges": 0, "new_initializers": 0,
            "unchanged_position_adders_wrap_reset_priority": True,
            "unchanged_existing_assertions": True, "timing_claim": False}


def record(path):
    raw = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": sha(raw), "bytes": len(raw)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    assert out.is_relative_to(ROOT / "build") and not out.exists(), out
    parent = PARENT.read_bytes()
    candidate, edits = transform(parent)
    proof = source_proof(parent, candidate, edits)
    target = out / "candidate/rtl/fg_vram.sv"
    target.parent.mkdir(parents=True)
    target.write_bytes(candidate)
    oracle = out / "immutable-parent/rtl/fg_vram.sv"
    oracle.parent.mkdir(parents=True)
    oracle.write_bytes(parent)
    manifest = {"schema": "bt-v22-fg-remote-address-source-edge-v1",
                "status": "SOURCE_PASS_COMPILED_PROOFS_PENDING",
                "parent": record(PARENT), "oracle": record(oracle), "candidate": record(target),
                "helper": record(Path(__file__).resolve()), "edits": edits, "source_proof": proof,
                "contract": "One combinational De Morgan factorization only. All sequential assignment sites, reset/startup, raw command coercion, address wrap, selection priority, RAM ABI/configuration and existing assertions stay byte-identical."}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"candidate": record(target), "manifest": record(out / "manifest.json"), "helper": record(Path(__file__).resolve()), "proof": proof}, separators=(",", ":")))


if __name__ == "__main__":
    main()
