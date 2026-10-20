"""Decide whether the exact Intel RAM output register matches the old soft edge.

This is a private experiment over immutable v20 sources; it does not prepare or
qualify a production candidate. The retained vendor fixture is unchanged except
for its prototype module name. Failure preserves all inputs and logs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "build/timing_closure_20261011/fg_sprite_controls_v20_private"
SPR_SHA = "9fff133ad84106b7b171134e4a09c6d01ffffc0bc2fc69be7b49e272b45822ef"
MEM_SHA = "903aeedc272fd64409ebae8b8624befe82bc1f073d1545310dbeb070afaf6393"
VENDOR = Path("D:/q17/quartus/eda/sim_lib/altera_mf.v")
VENDOR_SHA = "c2f3f75264468c5ef594c5864fa81b550d113f40e3027c700c6153106d247213"
TOOLS = Path("D:/q17/modelsim_ase/win32aloem")
OLD_PROOF = ROOT / "build/sprite_fg_local_q_v18_v1/proof-r3/receipt.json"
OLD_PROOF_SHA = "ed5eb483ab2e4884c1beb8b2378dcf24c60a07525e7111c65f27f08faf7c940e"
SOFT = """ generate if (LOCAL_FG_Q) begin : local_foreground_q
  (* preserve, dont_merge *) reg [63:0] fg0_q = 64'b0;
  (* preserve, dont_merge *) reg [63:0] fg1_q = 64'b0;
  // Capture the original mirror's D on its original edge, never its old Q.
  always @(posedge CLK) begin
   fg0_q<=raw_q;
   fg1_q<=raw_q;
  end
  assign FG0_Q=fg0_q;
  assign FG1_Q=fg1_q;
"""
HARD = """ generate if (LOCAL_FG_Q) begin : registered_foreground_q
  VRAM_SHIFTREG #(addr_width,1,1) fg0_mirror(
   .CLK(CLK),.ACLR(1'b0),.WADDR(WADDR),.RADDR(RADDR),
   .DATA(DATA),.WREN(WREN),.Q(FG0_Q));
  VRAM_SHIFTREG #(addr_width,1,1) fg1_mirror(
   .CLK(CLK),.ACLR(1'b0),.WADDR(WADDR),.RADDR(RADDR),
   .DATA(DATA),.WREN(WREN),.Q(FG1_Q));
"""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def checked(path, expected):
    data = path.read_bytes()
    assert digest(data) == expected, (str(path), "source changed")
    return data


def module_body(data, name):
    text = data.decode("utf-8").replace("\r\n", "\n")
    matches = list(re.finditer(r"\bmodule " + name + r"\b.*?\bendmodule\b", text, re.S))
    assert len(matches) == 1, (name, "module body ambiguous")
    return matches[0].group(0) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    assert output.is_relative_to(ROOT / "build"), "experiment must stay in ignored build"
    assert not output.exists(), "preserve old experiment evidence"
    spr = checked(BASE / "rtl/spr_vram.sv", SPR_SHA)
    mem = checked(BASE / "rtl/BT_mem.sv", MEM_SHA)
    checked(VENDOR, VENDOR_SHA)
    prior = json.loads(checked(OLD_PROOF, OLD_PROOF_SHA))
    fixture = ROOT / "tests/graphics/sprite_local_q_vendor_tb.sv"
    fixture_raw = fixture.read_bytes()
    fixture_sha = digest(fixture_raw)
    prior_bytes = json.dumps(prior)
    assert fixture_sha in prior_bytes, "fixture not bound to accepted earlier proof"
    mirror = module_body(spr, "BT_SPR_POST_NONZERO_MIRROR")
    assert mirror.count(SOFT) == 1, "old soft-copy branch changed"
    prototype = mirror.replace(SOFT, HARD).replace(
        "module BT_SPR_POST_NONZERO_MIRROR ",
        "module BT_SPR_POST_NONZERO_MIRROR_REGISTERED_PROBE ", 1)
    bench = fixture_raw.decode("utf-8").replace("\r\n", "\n")
    assert bench.count("BT_SPR_POST_NONZERO_MIRROR_LOCAL") == 2
    bench = bench.replace("BT_SPR_POST_NONZERO_MIRROR_LOCAL",
                          "BT_SPR_POST_NONZERO_MIRROR_REGISTERED_PROBE")
    output.mkdir(parents=True)
    compiled = output / "compiled"
    compiled.mkdir()
    inputs = {
        "mirror_oracle.sv": mirror.encode(),
        "mirror_registered_probe.sv": prototype.encode(),
        "VRAM_SHIFTREG.sv": module_body(mem, "VRAM_SHIFTREG").encode(),
        "sprite_registered_q_probe_tb.sv": bench.encode(),
    }
    for name, data in inputs.items():
        (compiled / name).write_bytes(data)
    manifest = {
        "schema": "bt-sprite-registered-q-feasibility-preparation-v1",
        "source_root": str(BASE), "source_files": {
            str(BASE / "rtl/spr_vram.sv"): SPR_SHA,
            str(BASE / "rtl/BT_mem.sv"): MEM_SHA,
            str(VENDOR): VENDOR_SHA, str(OLD_PROOF): OLD_PROOF_SHA,
            str(fixture): fixture_sha, str(Path(__file__).resolve()): digest(Path(__file__).read_bytes())},
        "compiled_inputs": {str(compiled / name): digest(data) for name, data in inputs.items()},
        "prototype_edge": {"before": SOFT, "after": HARD,
                           "name_only": "BT_SPR_POST_NONZERO_MIRROR_REGISTERED_PROBE"},
        "fixture_edge": "two prototype module names only; assertions/stimulus unchanged",
        "scope": "startup, every original pre/post edge, exact OLD_DATA, all masks/addresses, off-edge ACLR and literal X/Z",
        "production_changed": False,
    }
    (output / "preparation.json").write_text(json.dumps(manifest, indent=2) + "\n")
    commands = [
        [str(TOOLS / "vlib.exe"), "work"],
        [str(TOOLS / "vlog.exe"), "-sv", "-work", "work"]
        + [str(compiled / name) for name in inputs] + [str(VENDOR)],
        [str(TOOLS / "vsim.exe"), "-c", "work.sprite_local_q_vendor_tb", "-do",
         "onerror {quit -code 1}; run -all; quit -code 0"],
    ]
    runs = []
    passed = True
    for index, command in enumerate(commands):
        log = output / ("compile.log" if index < 2 else "simulation.log")
        with log.open("ab") as stream:
            result = subprocess.run(command, cwd=output, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=600)
        runs.append({"command": command, "exit_code": result.returncode,
                     "log": str(log), "log_sha256": digest(log.read_bytes())})
        if result.returncode:
            passed = False
            break
    simlog = (output / "simulation.log").read_text(errors="replace") if (output / "simulation.log").exists() else ""
    marker = re.search(r"SPRITE_LOCAL_VENDOR_PASS pre=(\d+) post=(\d+) old_data=(\d+) mask_cases=(\d+) collisions=(\d+) offedge=(\d+) unknown=(\d+)", simlog)
    passed = passed and marker is not None and not re.search(r"\*\* (?:Error|Fatal):", simlog)
    receipt = {"schema": "bt-sprite-registered-q-feasibility-v1",
               "status": "PASS_EXACT_VENDOR_EDGE" if passed else "FAIL_EXACT_VENDOR_EDGE",
               "preparation": str(output / "preparation.json"),
               "preparation_sha256": digest((output / "preparation.json").read_bytes()),
               "runs": runs, "parsed_coverage": list(map(int, marker.groups())) if marker else None,
               "same_clock_and_original_soft_Q_NZ_preserved": True,
               "ACLR_for_new_hard_output": "constant0",
               "collision_exclusions": 0, "x_exclusions": 0,
               "production_candidate_qualified": False, "mapped_retention_proven": False,
               "core_timing_accepted": False, "rbf_generated": False}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "receipt": str(output / "receipt.json"),
                      "coverage": receipt["parsed_coverage"]}))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
