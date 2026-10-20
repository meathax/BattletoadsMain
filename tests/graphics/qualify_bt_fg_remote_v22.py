"""Fresh complete FG state/pin and four-state proof for the v22 remote gate."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "build/timing_closure_20261011/q17_local_paths_v22_private"
SNAPSHOT = ROOT / "build/timing_closure_20261011/q17_local_paths_v22_private-snapshot.json"
SNAPSHOT_SHA = "339bf281bad4f0235b0effb5b1b468a9ac6854421634aaec8d489bcc93520aed"
PREPARER = ROOT / "tests/graphics/prepare_bt_fg_remote_v22.py"
OLD = ROOT / "tests/graphics/qualify_bt_fg_v20_controls.py"
OLD_SHA = "dcb52aecb244fb56d3bf45d6fed2937b117d1d384c50ae8490389bff5e4e2006"
TEMPLATE = ROOT / "tests/graphics/bt_fg_remote_v22_fourstate_tb.sv"
SHA = lambda raw: hashlib.sha256(raw).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record(path):
    raw = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": SHA(raw), "bytes": len(raw)}


def checked(path, expected):
    raw = path.read_bytes()
    assert SHA(raw) == expected, (path, SHA(raw), expected)
    return raw


def additions():
    return '''
  integer fg_v22_remote_checks=0;
  genvar remote_group;
  generate for(remote_group=0;remote_group<3;remote_group=remote_group+1) begin : remote_equivalence
    always @(posedge CLK or negedge CLK) begin
      #0.1;
      if(RST_N) begin
        assert(candidate.hole_addr_local[remote_group].remote_addr === reference.hole_addr_local[remote_group].remote_addr)
          else $fatal(1,"FG remote address select differs group=%0d",remote_group);
      end
    end
  end endgenerate
  always @(negedge CLK) begin
    #0.1;
    if(RST_N) fg_v22_remote_checks=fg_v22_remote_checks+1;
  end
'''


def make_fragment(parent, candidate):
    old = parent.replace(b"\r\n", b"\n").decode("latin1")
    new = candidate.replace(b"\r\n", b"\n").decode("latin1")
    def block(text, name):
        pattern = r"(?m)^\s*\(\* keep \*\) wire " + name + r"\s*=.*?;"
        hits = re.findall(pattern, text, re.S)
        assert len(hits) == 1, (name, len(hits))
        return hits[0].replace("(* keep *) ", "")
    stop, next_rmt = block(old, "stop_rmt"), block(old, "next_rmt")
    before = block(old, "remote_addr").replace("wire remote_addr", "wire original_remote", 1)
    after = block(new, "remote_addr").replace("wire remote_addr", "wire candidate_remote", 1)
    template = TEMPLATE.read_text()
    for marker, body in (("// __ORIGINAL_STOP_AND_NEXT__", stop + "\n" + next_rmt), ("// __ORIGINAL_REMOTE__", before), ("// __CANDIDATE_REMOTE__", after)):
        assert template.count(marker) == 1
        template = template.replace(marker, body, 1)
    return template.encode("latin1"), {"stop": SHA(stop.encode()), "next_rmt": SHA(next_rmt.encode()), "original_remote": SHA(before.encode()), "candidate_remote": SHA(after.encode())}


def prepare(edge, output, profile):
    checked(OLD, OLD_SHA)
    old = load(OLD, "fg_v22_frozen_runtime")
    preparer = load(PREPARER, "fg_v22_remote_preparer")
    manifest_path = edge / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["schema"] == "bt-v22-fg-remote-address-source-edge-v1"
    assert manifest["helper"]["sha256"] == SHA(PREPARER.read_bytes())
    parent = checked(Path(manifest["oracle"]["path"]), preparer.PARENT_SHA)
    checked(Path(manifest["parent"]["path"]), preparer.PARENT_SHA)
    candidate = checked(Path(manifest["candidate"]["path"]), manifest["candidate"]["sha256"])
    proof = preparer.source_proof(parent, candidate, manifest["edits"])
    snapshot = json.loads(checked(SNAPSHOT, SNAPSHOT_SHA))
    output.mkdir(parents=True)
    inputs = output / "inputs"
    inputs.mkdir()
    helpers = output / "executed-helpers"
    helpers.mkdir()
    for path in (Path(__file__).resolve(), PREPARER, TEMPLATE, OLD, old.ORDER):
        (helpers / path.name).write_bytes(path.read_bytes())
    sources = {}
    for name in ("rtl/BT_mem.sv", "rtl/ddram.sv", "rtl/bt_fg_ddr_clear.sv"):
        source = BASE / name
        raw = checked(source, snapshot["sources"][name])
        (inputs / source.name).write_bytes(raw)
        sources[name] = record(source)
    for name in ("tests/graphics/ram_models.sv", "tests/foreground_ddr_tb.sv"):
        source = ROOT / name
        raw = checked(source, old.BOUND[name])
        (inputs / source.name).write_bytes(raw)
        sources[name] = record(source)
    (inputs / "fg_vram.sv").write_bytes(candidate)
    reference = parent.decode("latin1")
    modules = re.findall(r"^module\s+(\w+)", reference, re.M)
    for module in sorted(modules, key=len, reverse=True):
        reference = re.sub(r"\b" + re.escape(module) + r"\b", module + "_REFERENCE", reference)
    (inputs / "reference-fg_vram.sv").write_bytes(reference.encode("latin1"))
    vendor = old.checked(old.VENDOR, old.VENDOR_SHA)
    primitive = re.search(rb"(?m)^module lcell \(in, out\);\r?\n.*?^endmodule", vendor, re.S)[0]
    assert SHA(primitive) == old.PRIMITIVE_SHA
    (inputs / "intel_lcell.v").write_bytes(b"`timescale 1ps/1ps\n" + primitive + b"\n")
    original_tb = old.checked(old.TB, old.TB_SHA)
    text = old.canonical(original_tb).decode("latin1")
    extra = additions()
    assert text.count("  initial begin\n") >= 1
    text = text.replace("  initial begin\n", extra + "  initial begin\n", 1)
    marker = '    $display("PASS serial chunk complete pins/state:'
    assert text.count(marker) == 1
    report = '    $display("PASS FG v22 remote control: checks=%0d",fg_v22_remote_checks);\n'
    if profile == "four-state":
        report += '    assert(fg_remote_v22_fourstate_tb.done) else $fatal(1,"FG remote exhaustive proof unfinished");\n'
    text = text.replace(marker, report + marker, 1)
    assert text.replace(extra, "", 1).replace(report, "", 1) == old.canonical(original_tb).decode("latin1")
    (inputs / "item4_foreground_equivalence_tb.sv").write_bytes(text.encode("latin1"))
    fragment, fragment_hashes = make_fragment(parent, candidate)
    (inputs / "fg_remote_v22_fourstate_tb.sv").write_bytes(fragment)
    adapters = {}
    if profile == "four-state":
        order = old.load(old.ORDER, old.ORDER_SHA, "fg_remote_v22_decl_order")
        for name in ("fg_vram.sv", "reference-fg_vram.sv"):
            raw = (inputs / name).read_bytes()
            canonical = old.canonical(raw)
            adapted, detail = order.declaration_order(canonical, old.ORDER_NAMES)
            adapters[name] = {"raw_sha256": SHA(raw), "canonical_sha256": SHA(canonical), "newline_edge": "CRLF to LF", **detail}
            (inputs / name).write_bytes(adapted)
        raw = (inputs / "item4_foreground_equivalence_tb.sv").read_bytes()
        adapted, detail = order.declaration_order(raw, ("DRAW_ADDR",))
        adapters["item4_foreground_equivalence_tb.sv"] = detail
        (inputs / "item4_foreground_equivalence_tb.sv").write_bytes(adapted)
    meta = {"schema": "bt-v22-fg-remote-proof-inputs-v1", "profile": profile,
            "edge": record(manifest_path), "parent": manifest["parent"], "oracle": manifest["oracle"], "candidate": manifest["candidate"],
            "source_proof": proof, "snapshot": record(SNAPSHOT), "parent_sources": sources,
            "original_fixture": record(old.TB), "original_fixture_canonical_inverse": True,
            "assertion_additions": extra, "report_addition": report, "namespace_modules": modules,
            "function_template": record(TEMPLATE), "fragment_hashes": fragment_hashes,
            "declaration_order_adapters": adapters, "executed_helpers": {str(p): SHA(p.read_bytes()) for p in helpers.iterdir()},
            "compiled_inputs": {str(p): SHA(p.read_bytes()) for p in inputs.iterdir()},
            "case_equality_exclusions": 0, "collision_masks_added": 0, "intel_ram_or_timing_claim": False}
    (output / "preparation.json").write_text(json.dumps(meta, indent=2) + "\n")
    return meta


def verify_frozen(meta):
    for key in ("executed_helpers", "compiled_inputs"):
        for path, expected in meta[key].items():
            checked(Path(path), expected)


def simulate(output, meta):
    runtime = load(OLD, "fg_v22_remote_runtime")
    inputs = output / "inputs"
    records = []
    if meta["profile"] == "native":
        jobs = [("fg", "item4_foreground_equivalence_tb", ["fg_vram.sv", "reference-fg_vram.sv", "ram_models.sv", "intel_lcell.v", "item4_foreground_equivalence_tb.sv"]),
                ("fg-ddr", "foreground_ddr_tb", ["fg_vram.sv", "ddram.sv", "bt_fg_ddr_clear.sv", "ram_models.sv", "intel_lcell.v", "foreground_ddr_tb.sv"])]
        for label, top, files in jobs:
            target = output / label
            target.mkdir()
            command = ["C:/Windows/System32/wsl.exe", "-d", "Ubuntu", "--cd", str(inputs), "--exec", "verilator", "--binary", "--assert", "--timing", "-j", "4", "--threads", "1", "--x-initial", "unique", "--x-assign", "unique", "--top-module", top, "--Mdir", runtime.wsl(target / "obj"), "-Wno-fatal", *files]
            records.append(runtime.run(command, inputs, target / "build.log"))
            if records[-1]["exit_code"]:
                break
            records.append(runtime.run(["C:/Windows/System32/wsl.exe", "-d", "Ubuntu", "--cd", str(inputs), "--exec", runtime.wsl(target / "obj" / ("V" + top))], inputs, target / "run.log"))
            if records[-1]["exit_code"]:
                break
    else:
        tools = Path("D:/q17/modelsim_ase/win32aloem")
        work = output / "work"
        records.append(runtime.run([str(tools / "vlib.exe"), str(work)], output, output / "vlib.log"))
        if not records[-1]["exit_code"]:
            files = ["fg_vram.sv", "reference-fg_vram.sv", "ram_models.sv", "intel_lcell.v", "item4_foreground_equivalence_tb.sv", "fg_remote_v22_fourstate_tb.sv"]
            records.append(runtime.run([str(tools / "vlog.exe"), "-sv", "-work", str(work), *[str(inputs / name) for name in files]], output, output / "build.log"))
        if not records[-1]["exit_code"]:
            records.append(runtime.run([str(tools / "vsim.exe"), "-c", "-assertdebug", "-onfinish", "stop", "-lib", str(work), "item4_foreground_equivalence_tb", "fg_remote_v22_fourstate_tb", "-do", "run -all; quit -code 0"], output, output / "run.log"))
    passed = bool(records) and all(row["exit_code"] == 0 for row in records)
    coverage = {}
    if passed:
        path = output / ("fg/run.log" if meta["profile"] == "native" else "run.log")
        text = path.read_text(errors="replace")
        state = re.search(r"PASS serial chunk complete pins/state: state_edges=(\d+) bank_edge_checks=(\d+)", text)
        pred = re.search(r"PASS FG v22 remote control: checks=(\d+)", text)
        passed = bool(state and pred) and not runtime.failure_text(text)
        if passed:
            coverage = {"state_edges": int(state[1]), "bank_edge_checks": int(state[2]), "remote_identity_checks": int(pred[1])}
            assert coverage["state_edges"] == 1263909 and coverage["bank_edge_checks"] == 10111272 and coverage["remote_identity_checks"] > 1200000
        if meta["profile"] == "four-state":
            four = re.search(r"PASS FG v22 remote four-state: cases=(\d+) negative_detected=(\d+)", text)
            passed = passed and bool(four)
            if four:
                coverage.update({"four_state_cases": int(four[1]), "four_state_negative_detected": int(four[2])})
                passed = passed and int(four[1]) == 262144 and int(four[2]) > 0
        else:
            path = output / "fg-ddr/run.log"
            text = path.read_text(errors="replace") if path.exists() else ""
            passed = passed and "PASS" in text and not runtime.failure_text(text)
            coverage["foreground_ddr_log"] = record(path) if path.exists() else None
    verify_frozen(meta)
    receipt = {"schema": "bt-v22-fg-remote-proof-v1", "status": "PASS" if passed else "FAIL",
               "preparation": record(output / "preparation.json"), "profile": meta["profile"],
               "candidate": meta["candidate"], "oracle": meta["oracle"], "edge": meta["edge"],
               "compiled_inputs": meta["compiled_inputs"], "executed_helpers": meta["executed_helpers"],
               "commands": records, "coverage": coverage, "original_assertions_preserved": True,
               "four_state_case_equality_exclusions": 0, "collision_masks_added": 0,
               "intel_ram_or_physical_timing_claim": False}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "receipt": record(output / "receipt.json"), "coverage": coverage}, separators=(",", ":")))
    assert passed, "Original assertions or decisive coverage failed"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--edge", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=("native", "four-state"), required=True)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    assert output.is_relative_to(ROOT / "build")
    if args.resume:
        meta = json.loads((output / "preparation.json").read_text())
        assert meta["profile"] == args.profile
        verify_frozen(meta)
    else:
        assert not output.exists(), output
        meta = prepare(args.edge.resolve(), output, args.profile)
    if args.prepare_only:
        print(json.dumps({"status": "PREPARED", "preparation": record(output / "preparation.json"), "candidate": meta["candidate"]}, separators=(",", ":")))
    else:
        simulate(output, meta)


if __name__ == "__main__":
    main()
