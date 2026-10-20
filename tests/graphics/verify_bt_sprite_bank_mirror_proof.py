"""Reproduce the frozen sprite-bank proof inputs and verify retained evidence.

No compiler or simulator is launched. Earlier vlib log digests are explicitly
checked as prefixes of subsequently appended compile logs; receipts are intact.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
PREPARER = ROOT / "tests/graphics/prepare_bt_sprite_bank_mirrors.py"
QUALIFIER = ROOT / "tests/graphics/qualify_bt_sprite_bank_mirrors.py"
CONTROL_NAMES = ["hard_output_reset", "extra_output_cycle", "wrong_read_address",
                 "old_alias_wrong_fg", "activation_missing", "wrong_bank_binding",
                 "wrong_mux_lane", "default_on"]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def checked(path, expected, evidence):
    path = Path(path)
    assert path.is_file() and not path.is_symlink(), ("missing/linked evidence", str(path))
    raw = path.read_bytes()
    assert sha(raw) == expected, ("evidence digest changed", str(path))
    evidence[str(path.resolve())] = expected
    return raw


def prefix_length(raw, expected):
    if sha(raw) == expected:
        return len(raw)
    # Only newline-delimited, actually retained command output is admissible.
    candidates = [0] + [m.end() for m in re.finditer(b"\n", raw)]
    matches = [n for n in candidates if sha(raw[:n]) == expected]
    assert len(matches) == 1, "compile stage prefix not retained exactly"
    return matches[0]


def verify_proof(edge_directory, receipt_path, _receipt=None, _preparation=None):
    edge = Path(edge_directory).resolve()
    receipt_path = Path(receipt_path).resolve()
    assert edge.is_relative_to(ROOT / "build") and receipt_path.is_relative_to(ROOT / "build")
    evidence = {}
    receipt_raw = receipt_path.read_bytes()
    evidence[str(receipt_path)] = sha(receipt_raw)
    receipt = json.loads(receipt_raw) if _receipt is None else _receipt
    assert receipt["schema"] == "bt-v20-sprite-bank-registered-mirror-qualification-v1"
    assert receipt["status"] == "PASS_VENDOR_4STATE_SPRITE_AND_ACTUAL_BANK_PINS"
    for name in ("x_exclusions", "collision_exclusions"):
        assert receipt[name] == 0
    for name in ("pin_spy_is_physical_RAM_proof", "whole_board_native_rerun",
                 "mapped_ram_replicas_or_placement_proven", "core_timing_accepted",
                 "rbf_generated", "root_modified"):
        assert receipt[name] is False
    assert receipt["actual_Intel_vendor_RAM"] is True
    assert receipt["negative_controls_rejected"] == CONTROL_NAMES
    prep_path = Path(receipt["preparation"])
    assert prep_path == receipt_path.parent / "preparation.json"
    prep_raw = checked(prep_path, receipt["preparation_sha256"], evidence)
    prep = json.loads(prep_raw) if _preparation is None else _preparation
    assert prep["schema"] == "bt-v20-sprite-bank-mirror-proof-preparation-v1"
    assert prep["negative_controls_rejected"] == CONTROL_NAMES
    assert Path(prep["edge"]) == edge / "manifest.json"
    manifest = json.loads(checked(edge / "manifest.json", prep["edge_sha256"], evidence))
    for helper in (PREPARER, QUALIFIER):
        checked(helper, prep["helpers"][str(helper)], evidence)
    assert prep["helpers"][str(PREPARER)] == manifest["helper_sha256"]
    checked(receipt_path.parent / "executed_helper.py", prep["helpers"][str(QUALIFIER)], evidence)
    preparer = load(PREPARER, "bank_mirror_evidence_preparer")
    qualifier = load(QUALIFIER, "bank_mirror_evidence_qualifier")
    parents, candidates, _ = preparer.verify_edge(edge)
    assert prep["source_files"] == {str(edge / "candidate" / rel): sha(data) for rel, data in candidates.items()}
    assert prep["oracle_files"] == {str(edge / "oracle" / rel): sha(data) for rel, data in parents.items()}
    for path, digest in {**prep["source_files"], **prep["oracle_files"], **prep["fixture_parents"],
                         **prep["vendor"], **prep["old_fixture_proof"]}.items():
        checked(path, digest, evidence)
    fixture_base = qualifier.OLD_PROOF.parent / "compiled"
    fixture_data = {name: (fixture_base / name).read_bytes() for name in
                    ("sprite_local_q_vendor_tb.sv", "sprite_read_equivalence_tb.sv", "sprite_packet_tb.sv")}
    inputs = {
        "spr_v20.sv": qualifier.renamed_spr(parents["rtl/spr_vram.sv"], "_V20"),
        "spr_banks.sv": qualifier.renamed_spr(candidates["rtl/spr_vram.sv"], "_BANKS"),
        "BT_mem.sv": preparer.MEM.read_bytes(),
        "sprite_local_q_vendor_tb.sv": qualifier.vendor_fixture(fixture_data["sprite_local_q_vendor_tb.sv"]),
        "sprite_read_equivalence_tb.sv": qualifier.read_fixture(fixture_data["sprite_read_equivalence_tb.sv"]),
        "sprite_packet_tb.sv": qualifier.packet_fixture(fixture_data["sprite_packet_tb.sv"]),
    }
    pin_inputs = {
        "bank_v20.sv": qualifier.bank_module(parents["rtl/fg_vram.sv"], "_V20"),
        "bank_banks.sv": qualifier.bank_module(candidates["rtl/fg_vram.sv"], "_BANKS"),
        "sprite_bank_ram_pin_tb.sv": qualifier.PIN_BENCH.encode(),
    }
    compiled = receipt_path.parent / "compiled"
    expected_compiled = {str(compiled / name): sha(data) for name, data in {**inputs, **pin_inputs}.items()}
    assert prep["compiled_sources"] == expected_compiled
    for name, raw in {**inputs, **pin_inputs}.items():
        assert checked(compiled / name, sha(raw), evidence) == raw
    # Recheck the earlier decisive hard-Q mode experiment, including all inputs.
    mode = json.loads(checked(preparer.MODE_PROOF, preparer.MODE_PROOF_SHA, evidence))
    assert mode["status"] == "PASS_EXACT_VENDOR_EDGE"
    assert mode["parsed_coverage"] == [33695,33695,128,32768,16384,16,7]
    mode_prep = json.loads(checked(mode["preparation"], mode["preparation_sha256"], evidence))
    for path, digest in {**mode_prep["source_files"], **mode_prep["compiled_inputs"]}.items():
        checked(path, digest, evidence)
    tools = qualifier.TOOLS
    expected_commands = [
        [str(tools / "vlib.exe"), "work"],
        [str(tools / "vlog.exe"), "-sv", "-work", "work"] + [str(compiled / name) for name in inputs] + [str(qualifier.VENDOR)],
        [str(tools / "vlib.exe"), "pin_work"],
        [str(tools / "vlog.exe"), "-sv", "-work", "pin_work"] + [str(compiled / name) for name in pin_inputs],
    ]
    tops = ["work.sprite_local_q_vendor_tb", "work.sprite_read_equivalence_tb", "work.sprite_packet_tb", "pin_work.sprite_bank_ram_pin_tb"]
    expected_commands += [[str(tools / "vsim.exe"), "-c", top, "-do", "onerror {quit -code 1}; run -all; quit -code 0"] for top in tops]
    assert [row["command"] for row in receipt["runs"]] == expected_commands
    assert len(receipt["runs"]) == 8 and all(row["exit_code"] == 0 for row in receipt["runs"])
    prefixes = []
    for rows in (receipt["runs"], mode["runs"]):
        grouped = {}
        for row in rows:
            assert row["exit_code"] == 0
            grouped.setdefault(row["log"], []).append(row)
        for path, log_rows in grouped.items():
            raw = checked(path, log_rows[-1]["log_sha256"], evidence)
            assert not re.search(rb"\*\* (?:Fatal|Error):", raw)
            for row in log_rows[:-1]:
                prefixes.append({"log": path, "sha256": row["log_sha256"],
                                 "retained_prefix_bytes": prefix_length(raw, row["log_sha256"])})
    coverage = {}
    logtexts = {}
    for top in tops:
        log = receipt_path.parent / (top.split(".")[1] + ".log")
        logtexts[top] = log.read_text(errors="replace")
        coverage[top] = [line.strip() for line in logtexts[top].splitlines() if any(m in line for m in
                         ("_PASS", "PASS sprite", "SPRITE_LOCAL_", "SPRITE_REGISTERED_", "SPRITE_BANK_"))]
    assert receipt["coverage"] == coverage
    text = logtexts[tops[0]]
    assert re.search(r"SPRITE_LOCAL_VENDOR_PASS pre=33695 post=33695 old_data=128 mask_cases=32768 collisions=16384 offedge=16 unknown=7", text)
    assert re.search(r"SPRITE_REGISTERED_BANKS checks=541568 mirrors=8 literal_control_cases=50", text)
    text = logtexts[tops[1]]
    assert "transfers=16 comparisons=15424" in text
    assert "SPRITE_LOCAL_FULL_OUTPUTS checks=286232 ports=15" in text
    assert "SPRITE_BANK_READ_OUTPUTS checks=2289856 mirrors=8" in text
    text = logtexts[tops[2]]
    assert "SPRITE_PACKET_PASS packets=512 readbacks=512 completion_checks=528" in text
    assert "SPRITE_LOCAL_PACKET_OUTPUTS checks=3109" in text
    assert "SPRITE_BANK_PIN_PASS cases=2048 pre=8196 post=8196 banks=4 pins=12" in logtexts[tops[3]]
    return {"schema": "bt-v20-sprite-bank-mirror-retained-proof-validation-v1",
            "status": "PASS_SOURCE_INPUT_LOG_AND_COVERAGE_BINDING",
            "edge": str(edge / "manifest.json"), "receipt": str(receipt_path),
            "bound_evidence_files": evidence, "compile_log_prefix_edges": prefixes,
            "original_receipt_or_logs_modified": False, "new_simulation_run": False,
            "scope": "vendor four-state mirrors + full sprite outputs + actual foreground input pins; physical leaf unchanged",
            "mapped_retention_or_core_timing_accepted": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--edge", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    receipt_path = Path(args.receipt).resolve()
    result = verify_proof(args.edge, receipt_path)
    receipt = json.loads(receipt_path.read_bytes())
    prep = json.loads(Path(receipt["preparation"]).read_bytes())
    negatives = []
    mutations = [("wrong_status", lambda r,p:r.update(status="PASS")),
                 ("x_exclusion", lambda r,p:r.update(x_exclusions=1)),
                 ("collision_exclusion", lambda r,p:r.update(collision_exclusions=1)),
                 ("fake_physical_claim", lambda r,p:r.update(mapped_ram_replicas_or_placement_proven=True)),
                 ("lost_source_control", lambda r,p:r["negative_controls_rejected"].pop()),
                 ("missing_command", lambda r,p:r["runs"].pop()),
                 ("changed_command", lambda r,p:r["runs"][-1]["command"].append("-novopt")),
                 ("wrong_bank_coverage", lambda r,p:r["coverage"]["pin_work.sprite_bank_ram_pin_tb"].clear()),
                 ("missing_input", lambda r,p:p["compiled_sources"].pop(next(iter(p["compiled_sources"])))),
                 ("foreign_input", lambda r,p:p["compiled_sources"].update({"foreign.sv":"0"*64})),
                 ("changed_compiled_hash", lambda r,p:p["compiled_sources"].update({next(iter(p["compiled_sources"])):"0"*64})),
                 ("wrong_old_body", lambda r,p:p["oracle_files"].update({next(iter(p["oracle_files"])):"0"*64}))]
    for label, mutate in mutations:
        r,p = copy.deepcopy(receipt),copy.deepcopy(prep)
        mutate(r,p)
        try:
            verify_proof(args.edge, receipt_path, r,p)
        except (AssertionError, KeyError):
            negatives.append(label)
        else:
            raise AssertionError((label, "negative accepted"))
    result["validator_negative_controls_rejected"] = negatives
    result["helper"] = str(Path(__file__).resolve())
    result["helper_sha256"] = sha(Path(__file__).read_bytes())
    output = Path(args.output).resolve()
    assert output.is_relative_to(ROOT / "build") and not output.exists()
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "output": str(output), "sha256": sha(output.read_bytes()),
                      "files": len(result["bound_evidence_files"]), "negatives": len(negatives)}))


if __name__ == "__main__":
    main()
