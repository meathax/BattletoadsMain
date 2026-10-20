#!/usr/bin/env python3
"""Qualify the frozen v20 DDR idle/bin flag edge against its full parent.

Existing cache/owner/return and foreground round-trip assertions stay intact.
The four-state test compiles the exact old/new DIN scopes, with flag predicates
supplied by the separately checked same-edge literal-state induction.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PARENT_DIR = ROOT / "build/timing_closure_20261011/fg_sprite_controls_v20_private"
SNAPSHOT = ROOT / "build/timing_closure_20261011/fg_sprite_controls_v20_private-snapshot.json"
SNAPSHOT_SHA = "e889eac9badb82a3ab654cf7b6b22c05235849300c70b45734b5bc8725064ab4"
CANDIDATE = ROOT / "build/ddr_din_local_flags_v20_v2/candidate/rtl/ddram.sv"
CANDIDATE_SHA = "80b5af022202c55070102c242c0f59cda409a83d71bce5079ea0b93e47ae3f6b"
EDGE = ROOT / "build/ddr_din_local_flags_v20_v2/manifest.json"
EDGE_SHA = "7a0fe6bb8015c351403d4e33cb41f2dbf0528ded335a45eef7ec542fc461dc85"
PREPARER = ROOT / "tests/graphics/prepare_bt_ddr_din_local_flags.py"
PREPARER_SHA = "10a84f846daaa26dccd5d2d9431e96c65d276ed4fca369ce2e77b2d0cc799365"
PARALLEL_DIR = ROOT / "build/ddr_parallel_sources_v9_v2/proof"
PARALLEL_RECEIPT_SHA = "7963e66ef8a36f8748fb10f02e21fab545d13483848ae360841a971d9ad9d5a5"
READ_RECEIPT = ROOT / "build/current_read_storage_b537_v6/receipt.json"
READ_RECEIPT_SHA = "50e8e34f7054b9f4d0e0cea3abff8b539f705480820970b238c463f392749764"
NATIVE128 = ROOT / "build/native_lcell_link_v20_v1/qualified-128-r3/receipt.json"
NATIVE128_SHA = "0045422f3d4fb925ba9f730c89e37cd2e5feb99079c4e9044ce6919aae538909"
OLD_CACHE_TB_SHA = "9d19169bae517cc1043073e692ea316f010cbb848089686fa8e5aa77c7b45cdd"
FG_SHA = "ddf9c579f24837042d1eb0e700f4e6f7f27896d0e93f4538525d66bfa1efbdd9"
SHARED = {
    "tests/foreground_ddr_tb.sv": "fd723e62a48b285c8872526720cbf18b30b82e80f908986ce1addef70a21ea3c",
    "tests/graphics/ram_models.sv": "039f6ead2da5edfeaa0bf4aeb45eb7795ccf3e57e6193ea3e7763a41ae2cdafc",
    "tests/graphics/intel_lcell_sim.v": "481b1c8fc9326e98502b4cdafa921dbe9f17b061b498b80b4d602d52ec511b29",
    "rtl/bt_fg_ddr_clear.sv": "bb811a37ed3e084eb291e2f1a4f24218aa69dad859223c248261860fd5a6f9d1",
}
OUTPUTS = ("DDRAM_CLK DDRAM_BURSTCNT DDRAM_ADDR DDRAM_RD DDRAM_DIN DDRAM_BE DDRAM_WE "
           "io_dout io_busy dout busy tag_keys bout ba bte dbg_din").split()
SCALARS = ("ram_address ram_din ram_ba ram_burst ram_read ram_write burst_read_busy burst_write_busy "
           "read_busy write_pend write_busy io_read_busy io_write_busy burst_addr write_addr write_data "
           "write_data_o write_be write_cache cache_write_commit write_tag_hit read_cache read_bank_sel "
           "read_tag_hit read_bank_miss read_miss rpos io_write_addr io_write_data io_write_data_din "
           "io_write_be io_read_addr io_rbuf state write_prepend old_brd old_bwr old_rd old_we busy_reg "
           "state_idle read_clear write_clear request_write write_start read_busy_next write_busy_next "
           "read_return_sel return_capture_bank return_hold_bank return_word3_bank request_word busy_next "
           "busy_local read_start_busy write_data_parallel write_data_o_parallel write_data_serial "
           "write_data_o_serial").split()
MARKER = "// DDR_DIN_FLAG_FULL_PARENT_MONITORS_BEGIN"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pin(path: Path, digest: str) -> bytes:
    raw = path.read_bytes()
    if sha(raw) != digest:
        raise ValueError(f"Input hash mismatch: {path}")
    return raw


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wsl(path: Path) -> str:
    path = path.resolve()
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


def clone_instance(fixture: str, instance: str, new_name: str) -> str:
    pattern = r"\bddram\s*(?:#\(.*?\)\s*)?" + instance + r"\(.*?;"
    matches = list(re.finditer(pattern, fixture, re.S))
    if len(matches) != 1:
        raise ValueError("Unique full-controller instance guard failed: " + instance)
    result = matches[0].group()
    result = result.replace("ddram", "DDR_DIN_PARENT", 1)
    result = result.replace(instance + "(", new_name + "(", 1)
    for name in OUTPUTS:
        result = re.sub(r"\." + name + r"\s*\([^()]*\)", "." + name + "()", result)
    return "    " + result


def monitors(pairs: list[tuple[str, str, str, bool]], all_states: bool) -> str:
    lines = [MARKER]
    for old, new, label, activated in pairs:
        lines += [f"    integer {label}_pre=0, {label}_post=0, {label}_flags=0;",
                  f"    reg [7:0] {label}_states=0;", f"    task automatic {label}_compare;"]
        for names, description in [(OUTPUTS, "all outputs"), (SCALARS, "original full controller state")]:
            left = ",".join(new + "." + name for name in names)
            right = ",".join(old + "." + name for name in names)
            lines += [f"        assert({{{left}}} === {{{right}}})",
                      f'            else $fatal(1,"DDR DIN {label} {description} changed at t=%0t",$time);']
        lines += [f"        for(integer lane=0;lane<4;lane=lane+1) begin",
                  f"            assert({new}.din_phase_lane[lane] === {{{old}.state==3'd1,{old}.state==3'd0}})",
                  f'                else $fatal(1,"DDR DIN {label} local phase changed lane=%0d t=%0t",lane,$time);',
                  f"            {label}_flags++;", "        end",
                  "        for(integer bank_index=0;bank_index<4;bank_index=bank_index+1) begin",
                  f"            assert({new}.read_addr[bank_index] === {old}.read_addr[bank_index] &&",
                  f"                   {new}.read_word_sel[bank_index] === {old}.read_word_sel[bank_index] &&",
                  f"                   {new}.read_bank_data[bank_index] === {old}.read_bank_data[bank_index])",
                  f'                else $fatal(1,"DDR DIN {label} read metadata changed");',
                  "            for(integer word_index=0;word_index<4;word_index=word_index+1)",
                  f"                assert({new}.rbuf[bank_index][word_index] === {old}.rbuf[bank_index][word_index])",
                  f'                    else $fatal(1,"DDR DIN {label} cache word changed");',
                  "        end"]
        if activated:
            lines += [f"        assert({{{new}.parallel_write_capture.cache_owner,{new}.parallel_write_capture.beat_owner}} ===",
                      f"               {{{old}.parallel_write_capture.cache_owner,{old}.parallel_write_capture.beat_owner}})",
                      f'            else $fatal(1,"DDR DIN {label} owner register changed");']
        lines += [f"        if({old}.state < 8) {label}_states[{old}.state]=1'b1;", "    endtask",
                  f"    always @(posedge clk) begin {label}_compare(); {label}_pre++;",
                  f"        #1; {label}_compare(); {label}_post++; end",
                  f"    for(genvar mb=0;mb<4;mb=mb+1)begin:{label}_banks",
                  f"        for(genvar mw=0;mw<4;mw=mw+1)begin:words",
                  "            task automatic cache_compare;"]
        for name in ["fill_data", "patch_data", "patch_valid"]:
            n = f"{new}.cache_store_bank[mb].cache_store_word[mw].{name}"
            o = f"{old}.cache_store_bank[mb].cache_store_word[mw].{name}"
            lines += [f"                assert({n} === {o})",
                      f'                    else $fatal(1,"DDR DIN {label} {name} changed");']
        lines += ["            endtask", "            always @(posedge clk)begin cache_compare(); #1; cache_compare(); end",
                  "        end", "    end",
                  f"    for(genvar ml=1;ml<4;ml=ml+1)begin:{label}_return_lanes",
                  "        task automatic return_compare;",
                  f"            assert({new}.return_lanes[ml].read_return_sel_lane === {old}.return_lanes[ml].read_return_sel_lane)",
                  f'                else $fatal(1,"DDR DIN {label} return lane changed");',
                  "        endtask", "        always @(posedge clk)begin return_compare(); #1; return_compare(); end",
                  "    end", "    final begin"]
        if all_states:
            lines += [f"        assert({label}_states===8'hff) else $fatal(1,\"DDR state coverage incomplete\");"]
        lines += [f'        $display("DDR_DIN_PHASE_FULL_PASS label={label} pre=%0d post=%0d flags=%0d states=%h",',
                  f"                 {label}_pre,{label}_post,{label}_flags,{label}_states);", "    end"]
    return "\n".join(lines) + "\n// DDR_DIN_FLAG_FULL_PARENT_MONITORS_END\n"


def append_fixture(raw: bytes, instances: list[tuple[str, str, str, bool]], all_states: bool) -> tuple[bytes, str]:
    text = raw.decode()
    if text.count("endmodule") != 1 or MARKER in text:
        raise ValueError("Exact original testbench module boundary guard failed")
    additions = "\n" + "\n".join(clone_instance(text, new, old) for old, new, _, _ in instances)
    additions += "\n" + monitors(instances, all_states)
    index = text.rfind("endmodule")
    result = text[:index] + additions + text[index:]
    if result.replace(additions, "", 1).encode() != raw:
        raise ValueError("Original fixture full-byte inverse failed")
    return result.encode(), additions


def fourstate_scopes(preparer) -> bytes:
    ports = """input clk, input [2:0] state,
 input DDRAM_BUSY, burst_write_busy, burst_read_busy, write_pend, read_busy, io_write_busy,
 input [63:0] bin, input [31:0] write_data_o, io_write_data_din,
 output reg [63:0] ram_din);
"""
    old = "module DIN_BEFORE(" + ports + preparer.OLD_BEAT.decode() + "\nendmodule\n"
    new = "module DIN_AFTER(" + ports + """wire[1:0] din_phase_lane[4];
for(genvar phase=0;phase<4;phase=phase+1)
 assign din_phase_lane[phase]={state==3'd1,state==3'd0};
""" + preparer.NEW_BEAT.decode() + "\nendmodule\n"
    return ("`timescale 1ns/1ps\n" + old + new).encode()


def fourstate_bench() -> bytes:
    return b"""`timescale 1ns/1ps
module ddr_din_flags_four_state_tb;
 reg clk=0; reg[2:0] state=0;
 reg DDRAM_BUSY,burst_write_busy,burst_read_busy,write_pend,read_busy,io_write_busy;
 reg[63:0] bin; reg[31:0] write_data_o,io_write_data_din;
 wire[63:0] before_q,after_q;
 DIN_BEFORE old(.clk(clk),.state(state),.DDRAM_BUSY(DDRAM_BUSY),.burst_write_busy(burst_write_busy),
 .burst_read_busy(burst_read_busy),.write_pend(write_pend),.read_busy(read_busy),.io_write_busy(io_write_busy),
 .bin(bin),.write_data_o(write_data_o),.io_write_data_din(io_write_data_din),.ram_din(before_q));
 DIN_AFTER current(.clk(clk),.state(state),.DDRAM_BUSY(DDRAM_BUSY),.burst_write_busy(burst_write_busy),
 .burst_read_busy(burst_read_busy),.write_pend(write_pend),.read_busy(read_busy),.io_write_busy(io_write_busy),
 .bin(bin),.write_data_o(write_data_o),.io_write_data_din(io_write_data_din),.ram_din(after_q));
 function automatic reg four(input integer code);
 case(code%4) 0:four=1'b0;1:four=1'b1;2:four=1'bx;3:four=1'bz;endcase
 endfunction
 integer cases=0,known_state_cases=0,pre=0,post=0,xz_data=0,holds=0;
 task automatic check;
 assert(before_q===after_q)else $fatal(1,"DIN four-state data/X mismatch case=%0d",cases);
 for(integer lane=0;lane<4;lane=lane+1)begin
 assert(old.din_sel===current.din_lanes[lane].din_sel)else $fatal(1,"DIN selector X mismatch");
 end
 endtask
 // Constant generate indices keep this legal for Icarus hierarchical lookup.
 for(genvar lane=0;lane<4;lane=lane+1)begin:lane_check
 always @(posedge clk)begin
 assert(old.din_sel===current.din_lanes[lane].din_sel)else $fatal(1,"DIN lane select changed");
 #1;assert(old.din_sel===current.din_lanes[lane].din_sel)else $fatal(1,"DIN lane select changed");
 end
 end
 initial begin
 #1;assert(before_q===64'bx && after_q===64'bx)else $fatal(1,"Uninitialized DIN contract changed");
 for(integer state_case=0;state_case<64;state_case=state_case+1)begin
 for(integer control_case=0;control_case<4096;control_case=control_case+1)begin
 integer ctrl; integer value;
 state={four(state_case/16),four(state_case/4),four(state_case)};
 ctrl=control_case;
 DDRAM_BUSY=four(ctrl);ctrl=ctrl/4;burst_write_busy=four(ctrl);ctrl=ctrl/4;
 burst_read_busy=four(ctrl);ctrl=ctrl/4;write_pend=four(ctrl);ctrl=ctrl/4;
 read_busy=four(ctrl);ctrl=ctrl/4;io_write_busy=four(ctrl);
 value=state_case+control_case;
 for(integer b=0;b<64;b=b+1)bin[b]=four(value+b/7);
 for(integer b=0;b<32;b=b+1)begin write_data_o[b]=four(value+b/5+1);io_write_data_din[b]=four(value+b/3+2);end
 #1;check();pre++;
 if($isunknown({bin,write_data_o,io_write_data_din}))xz_data++;
 if(!$isunknown(state))known_state_cases++;
 if(old.din_sel!==2'd1 && old.din_sel!==2'd2 && old.din_sel!==2'd3)holds++;
 clk=1;#1;check();post++;clk=0;#1;cases++;
 end end
 assert(cases==262144 && known_state_cases==32768 && xz_data==262144 && holds>0)
 else $fatal(1,"Incomplete DIN four-state exhaustive coverage");
 $display("DDR_DIN_FOUR_STATE_PASS cases=%0d reachable_state_controls=%0d pre=%0d post=%0d xz_data=%0d holds=%0d uninitialized_x=1 masks=0",cases,known_state_cases,pre,post,xz_data,holds);
 $finish;
 end
endmodule
""".replace(b" for(integer lane=0;lane<4;lane=lane+1)begin\n assert(old.din_sel===current.din_lanes[lane].din_sel)else $fatal(1,\"DIN selector X mismatch\");\n end\n", b"")


def check_inputs() -> tuple[object, bytes, bytes, dict]:
    pin(SNAPSHOT, SNAPSHOT_SHA)
    pin(PREPARER, PREPARER_SHA)
    preparer = load(PREPARER, "ddr_din_flag_preparer")
    candidate = pin(CANDIDATE, CANDIDATE_SHA)
    edge = json.loads(pin(EDGE, EDGE_SHA))
    parent = pin(PARENT_DIR / "rtl/ddram.sv", preparer.PARENT_SHA)
    proof = preparer.verify_source(candidate, edge["edits"])
    if preparer.reverse(candidate, edge["edits"]) != parent:
        raise ValueError("Full before/after raw DDR inverse failed")
    legacy = json.loads(pin(PARALLEL_DIR / "receipt.json", PARALLEL_RECEIPT_SHA))
    if legacy["status"] != "PASS" or legacy["candidate_sources"]["rtl/ddram.sv"] != preparer.PARENT_SHA:
        raise ValueError("Accepted actual parent controller evidence mismatch")
    for name, digest in legacy["compiled_sources"].items():
        pin(PARALLEL_DIR / name, digest)
    for kind in ("compile", "run"):
        if legacy[kind + "_exit_code"] != 0:
            raise ValueError("Original controller run failed")
        pin(PARALLEL_DIR / (kind + ".log"), legacy[kind + "_log_sha256"])
    read = json.loads(pin(READ_RECEIPT, READ_RECEIPT_SHA))
    if read["status"] != "PASS":
        raise ValueError("Original current-input read suite failed")
    for family in ("ddram-cache", "foreground-ddr"):
        job = read["jobs"][family]
        if job["compile_exit_code"] or job["run_exit_code"] or not job["testbench_passed"]:
            raise ValueError("Original full controller fixture failed")
        for row in job["compiled_inputs"]:
            pin(ROOT / row["path"], row["sha256"])
        for path, digest in job["logs"].items():
            pin(ROOT / path, digest)
    pin(NATIVE128, NATIVE128_SHA)
    for path, digest in SHARED.items():
        pin((PARENT_DIR if path.startswith("rtl/") else ROOT) / path, digest)
    pin(PARENT_DIR / "rtl/fg_vram.sv", FG_SHA)
    pin(PARALLEL_DIR / "ddram_cache_tb.sv", OLD_CACHE_TB_SHA)
    return preparer, parent, candidate, proof


def generated_files(preparer, parent: bytes, candidate: bytes) -> dict[str, dict[str, bytes]]:
    if parent.count(b"module ddram") != 1:
        raise ValueError("Exact parent module alias guard failed")
    old = parent.replace(b"module ddram", b"module DDR_DIN_PARENT", 1)
    cache, _ = append_fixture((PARALLEL_DIR / "ddram_cache_tb.sv").read_bytes(),
                             [("before_active", "candidate", "activated", True),
                              ("before_default", "serial", "default", False)], True)
    foreground, _ = append_fixture((ROOT / "tests/foreground_ddr_tb.sv").read_bytes(),
                                  [("before_controller", "controller", "foreground", False)], False)
    files = {"activated": {"ddram.sv": candidate, "ddram_parent.sv": old,
               "ddram_baseline.sv": (PARALLEL_DIR / "ddram_baseline.sv").read_bytes(),
               "bt_parallel_ddr_source.sv": (PARALLEL_DIR / "bt_parallel_ddr_source.sv").read_bytes(),
               "ddram_cache_tb.sv": cache},
             "foreground": {"ddram.sv": candidate, "ddram_parent.sv": old,
               "fg_vram.sv": (PARENT_DIR / "rtl/fg_vram.sv").read_bytes(),
               "ram_models.sv": (ROOT / "tests/graphics/ram_models.sv").read_bytes(),
               "intel_lcell_sim.v": (ROOT / "tests/graphics/intel_lcell_sim.v").read_bytes(),
               "bt_fg_ddr_clear.sv": (PARENT_DIR / "rtl/bt_fg_ddr_clear.sv").read_bytes(),
               "foreground_ddr_tb.sv": foreground},
             "fourstate": {"ddr_din_flags_scopes.sv": fourstate_scopes(preparer),
                           "ddr_din_flags_four_state_tb.sv": fourstate_bench()}}
    return files


def negative_controls(preparer, parent: bytes, candidate: bytes, edge: dict) -> list[dict]:
    substitutions = [
        ("initial_idle", b"'{4{2'b01}}", b"'{4{2'b00}}"),
        ("writer_phase", b"din_phase_lane[din_copy] <= 2'b01;", b"din_phase_lane[din_copy] <= 2'b10;"),
        ("delayed_projection", b"din_phase_lane[din_copy] <= 2'b10;", b"din_phase_lane[din_copy] <= {state==1,state==0};"),
        ("missing_writer", b"din_phase_lane[din_copy] <= 2'b00;", b";"),
        ("wrong_lane_data", b"write_data_o[(din_lane%2)*16 +: 16]", b"write_data_o[0 +: 16]"),
        ("wrong_bin_control", b"!DDRAM_BUSY && din_phase_lane[din_lane][1]", b"DDRAM_BUSY && din_phase_lane[din_lane][1]"),
        ("wrong_idle_control", b"din_phase_lane[din_lane][0] &&", b"din_phase_lane[din_lane][1] &&"),
        ("changed_clock_edge", b"always @(posedge clk)", b"always @(negedge clk)"),
    ]
    result = []
    for name, before, after in substitutions:
        if before not in candidate:
            raise ValueError("Negative control anchor absent: " + name)
        try:
            preparer.verify_source(candidate.replace(before, after, 1), edge["edits"])
        except (ValueError, AssertionError):
            result.append({"name": name, "rejected": True})
        else:
            raise ValueError("Unsafe source mutation accepted: " + name)
    try:
        preparer.transform(parent + b"\n")
    except ValueError:
        result.append({"name": "changed_parent_source", "rejected": True})
    else:
        raise ValueError("Wrong parent source accepted")
    return result


def prepare(output: Path) -> None:
    if output.exists() or not output.is_relative_to(ROOT / "build"):
        raise ValueError("A new private build output directory is required")
    preparer, parent, candidate, induction = check_inputs()
    files = generated_files(preparer, parent, candidate)
    controls = negative_controls(preparer, parent, candidate, json.loads(EDGE.read_text()))
    output.mkdir(parents=True)
    (output / "parent_raw.sv").write_bytes(parent)
    (output / "candidate_raw.sv").write_bytes(candidate)
    (output / "executed_qualifier.py").write_bytes(Path(__file__).read_bytes())
    (output / "executed_preparer.py").write_bytes(PREPARER.read_bytes())
    artifacts = {}
    for family, values in files.items():
        (output / family).mkdir()
        for name, raw in values.items():
            path = output / family / name
            path.write_bytes(raw)
            artifacts[path.relative_to(output).as_posix()] = sha(raw)
    manifest = {"schema": "bt-ddr-din-local-flags-proof-v2", "status": "PREPARED",
        "source_snapshot": str(SNAPSHOT), "source_snapshot_sha256": SNAPSHOT_SHA,
        "parent_sha256": sha(parent), "candidate": str(CANDIDATE), "candidate_sha256": sha(candidate),
        "edge": str(EDGE), "edge_sha256": EDGE_SHA, "source_induction": induction,
        "helper_sha256": sha(Path(__file__).read_bytes()), "preparer_sha256": PREPARER_SHA,
        "parent_actual_parallel_receipt": str(PARALLEL_DIR / "receipt.json"),
        "parent_actual_parallel_receipt_sha256": PARALLEL_RECEIPT_SHA,
        "parent_current_read_receipt": str(READ_RECEIPT), "parent_current_read_receipt_sha256": READ_RECEIPT_SHA,
        "parent_actual_native128_receipt": str(NATIVE128), "parent_actual_native128_receipt_sha256": NATIVE128_SHA,
        "compiled_inputs": artifacts, "negative_controls": controls,
        "preservation": {"activated_fixture_sha256": OLD_CACHE_TB_SHA,
                         "original_assertions_removed": 0, "original_fixtures_append_only_full_byte_inverse": True,
                         "changed_ddr_parameters_or_ports": False, "case_equality_all_outputs_pre_and_post": True,
                         "inactive_outputs_or_collisions_masked": 0, "clock_or_sdc_changes": 0},
        "scope": "Actual full old/current DDR activated/default and shipping FG round-trip simulations; exact actual DIN cone four-state truth including X hold. Native128 is a separately preserved v20 parent run. No mapped, hardware, whole-board, MAME or timing acceptance claim."}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"status": "PREPARED", "manifest": str(output / "manifest.json"),
                      "sha256": sha((output / "manifest.json").read_bytes())}), flush=True)


def verify_prepared(output: Path, manifest: dict) -> None:
    preparer, parent, candidate, _ = check_inputs()
    if manifest["helper_sha256"] != sha(Path(__file__).read_bytes()):
        raise ValueError("Executed qualifier changed")
    if manifest["candidate_sha256"] != CANDIDATE_SHA or manifest["parent_sha256"] != preparer.PARENT_SHA:
        raise ValueError("Selected source identity mismatch")
    for name, digest in manifest["compiled_inputs"].items():
        pin(output / name, digest)
    regenerated = generated_files(preparer, parent, candidate)
    expected = {f"{family}/{name}": sha(raw) for family, files in regenerated.items() for name, raw in files.items()}
    if expected != manifest["compiled_inputs"]:
        raise ValueError("Full compiler input regeneration failed")
    pin(output / "executed_qualifier.py", manifest["helper_sha256"])
    pin(output / "executed_preparer.py", PREPARER_SHA)
    pin(output / "parent_raw.sv", preparer.PARENT_SHA)
    pin(output / "candidate_raw.sv", CANDIDATE_SHA)


def run_step(directory: Path, name: str, command: list[str], record: dict, timeout: int = 1200) -> None:
    print("DDR_FLAGS_" + name.upper(), flush=True)
    path = directory / (name + ".log")
    with path.open("w") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
    record[name] = {"command": command, "exit_code": result.returncode, "log": str(path),
                    "log_sha256": sha(path.read_bytes())}
    if result.returncode:
        print(path.read_text(errors="replace")[-5000:], flush=True)
        raise RuntimeError("Compiler or simulation failed: " + name)


def native_job(output: Path, family: str, top: str, manifest: dict) -> dict:
    directory = output / family
    obj = Path("R:/Verilator/BT") / ("ddr-flags-" + family + "-" + uuid.uuid4().hex) / "obj"
    obj.mkdir(parents=True)
    files = [output / name for name in manifest["compiled_inputs"] if name.startswith(family + "/")]
    build = ["wsl.exe", "-d", "Ubuntu", "--cd", str(ROOT), "--exec", "/usr/bin/verilator",
             "--binary", "--assert", "--timing", "-Wno-fatal", "-Wno-BLKANDNBLK", "-j", "2", "--threads", "1",
             "--top-module", top, "--Mdir", wsl(obj)] + [wsl(path) for path in files]
    job = {}
    run_step(directory, "compile", build, job)
    run_step(directory, "run", ["wsl.exe", "-d", "Ubuntu", "--cd", str(ROOT), "--exec", wsl(obj / ("V" + top))], job)
    job["executable"] = str(obj / ("V" + top))
    job["executable_sha256"] = sha((obj / ("V" + top)).read_bytes())
    return job


def coverage(output: Path) -> dict:
    active = (output / "activated/run.log").read_text()
    foreground = (output / "foreground/run.log").read_text()
    four = (output / "fourstate/run.log").read_text()
    pattern = r"PARALLEL_DDR_PASS acceptance=(\d+) hold=(\d+) reset_blocks=(\d+) priority_collisions=(\d+) state_checks=(\d+) io_cpu=(\d+) fill_patch=(\d+) owners=(\d+),(\d+),(\d+),(\d+) owner_masks=60"
    match = re.search(pattern, active)
    if not match or not all(int(value) > 0 for value in match.groups()):
        raise ValueError("Original activated controller coverage absent")
    legacy_match = re.search(r"PASS DDR cache: writes=(\d+) reads=(\d+).*?DDR.*?=(\d+)", active)
    # Preserve the exact existing fixture's result line without guessing its spelling.
    original_pass = [line for line in active.splitlines() if "PASS" in line and "DDR_DIN" not in line]
    if not any("cache" in line.lower() for line in original_pass):
        raise ValueError("Original cache assertions did not finish")
    result = {"activated_original": dict(zip(["accepted_words", "hold", "pending_reset", "priority_collisions",
                  "full_state", "io_cpu", "fill_patch", "sprite", "foreground0", "foreground1", "cpu"], map(int, match.groups()))),
              "owner_mask_cases": 60, "original_result_lines": original_pass}
    pins = []
    for text in (active, foreground):
        for match in re.finditer(r"DDR_DIN_PHASE_FULL_PASS label=(\w+) pre=(\d+) post=(\d+) flags=(\d+) states=([0-9a-fA-F]+)", text):
            label, before, after, flags, states = match.groups()
            before, after, flags = int(before), int(after), int(flags)
            if before < 20000 or after < 20000 or abs(before-after) > 1 or flags != 4*(before+after):
                raise ValueError("Incomplete every-edge state/pin comparisons")
            pins.append({"profile": label, "pre": before, "post": after, "lane_flags": flags,
                         "all_output_count": len(OUTPUTS), "old_scalar_count": len(SCALARS), "state_mask": states})
    if {row["profile"] for row in pins} != {"activated", "default", "foreground"}:
        raise ValueError("Missing full controller profile")
    if any(row["state_mask"].lower() != "ff" for row in pins if row["profile"] != "foreground"):
        raise ValueError("Actual original state coverage incomplete")
    expected = "PASS shipping DDR controller: 196608 cold-clear writes during reset, 128 masked writes, 512 round-trip copy bytes, cache reads and command backpressure"
    if expected not in foreground:
        raise ValueError("Original foreground/DDRam assertions did not finish")
    match = re.search(r"DDR_DIN_FOUR_STATE_PASS cases=(\d+) reachable_state_controls=(\d+) pre=(\d+) post=(\d+) xz_data=(\d+) holds=(\d+) uninitialized_x=1 masks=0", four)
    if not match or list(map(int, match.groups()[:5])) != [262144, 32768, 262144, 262144, 262144] or int(match.group(6)) <= 0:
        raise ValueError("Four-state exhaustive scope incomplete")
    result.update(full_controller_profiles=pins, cold_clear_writes=196608, masked_writes=128, copy_bytes=512,
                  four_state_cases=262144, reachable_state_control_cases=32768, four_state_holds=int(match.group(6)),
                  full_data_and_x_equality=True, output_or_collision_masks=0)
    return result


def run(output: Path) -> None:
    manifest = json.loads((output / "manifest.json").read_text())
    if manifest["status"] != "PREPARED" or (output / "receipt.json").exists():
        raise ValueError("Only an unexecuted frozen preparation may run")
    verify_prepared(output, manifest)
    receipt = dict(manifest)
    receipt["jobs"] = {}
    try:
        versions = {}
        for label, executable, flag in [("verilator", "/usr/bin/verilator", "--version"), ("iverilog", "/usr/bin/iverilog", "-V")]:
            run_step(output, label + "_version", ["wsl.exe", "-d", "Ubuntu", "--cd", str(ROOT), "--exec", executable, flag], versions)
        receipt["tool_versions"] = versions
        receipt["jobs"]["activated"] = native_job(output, "activated", "ddram_cache_tb", manifest)
        receipt["jobs"]["foreground"] = native_job(output, "foreground", "foreground_ddr_tb", manifest)
        directory = output / "fourstate"
        job = {}
        executable = directory / "ddr_din_flags_four_state.vvp"
        run_step(directory, "compile", ["wsl.exe", "-d", "Ubuntu", "--cd", str(ROOT), "--exec", "/usr/bin/iverilog",
                 "-g2012", "-s", "ddr_din_flags_four_state_tb", "-o", wsl(executable),
                 wsl(directory / "ddr_din_flags_scopes.sv"), wsl(directory / "ddr_din_flags_four_state_tb.sv")], job)
        run_step(directory, "run", ["wsl.exe", "-d", "Ubuntu", "--cd", str(ROOT), "--exec", "/usr/bin/vvp", wsl(executable)], job)
        job["executable"] = str(executable)
        job["executable_sha256"] = sha(executable.read_bytes())
        receipt["jobs"]["fourstate"] = job
        receipt["coverage"] = coverage(output)
        verify_prepared(output, manifest)
        receipt["status"] = "PASS_SCOPED_DDR_DIN_LOCAL_FLAGS"
        receipt["source_induction"]["simulation"] = "PASS full parent/child replay and exact four-state DIN scopes"
    except Exception as exc:
        receipt["status"] = "FAIL"
        receipt["failure"] = str(exc)
        (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        raise
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    verify_composition_receipt(output / "receipt.json")
    print(json.dumps({"status": receipt["status"], "receipt": str(output / "receipt.json"),
                      "sha256": sha((output / "receipt.json").read_bytes()), "coverage": receipt["coverage"]}), flush=True)


def verify_composition_receipt(path: Path) -> dict:
    path = Path(path).resolve()
    receipt = json.loads(path.read_text())
    if receipt["status"] != "PASS_SCOPED_DDR_DIN_LOCAL_FLAGS":
        raise ValueError("No accepted fresh DDR proof")
    verify_prepared(path.parent, receipt)
    for job in list(receipt["jobs"].values()) + [receipt["tool_versions"]]:
        for step in ("compile", "run", "verilator_version", "iverilog_version"):
            if step in job:
                entry = job[step]
                if entry["exit_code"] != 0:
                    raise ValueError("Actual compiler/run failed")
                pin(Path(entry["log"]), entry["log_sha256"])
        if "executable" in job:
            pin(Path(job["executable"]), job["executable_sha256"])
    if coverage(path.parent) != receipt["coverage"]:
        raise ValueError("Actual retained log coverage changed")
    if len(receipt["negative_controls"]) != 9 or not all(row["rejected"] for row in receipt["negative_controls"]):
        raise ValueError("Source corruption controls missing")
    return {"status": receipt["status"], "receipt_sha256": sha(path.read_bytes()),
            "parent_sha256": receipt["parent_sha256"], "candidate_sha256": receipt["candidate_sha256"],
            "source_snapshot_sha256": receipt["source_snapshot_sha256"], "scope": receipt["scope"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--run-prepared", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify_composition_receipt(args.verify)))
    elif args.run_prepared:
        run(args.run_prepared.resolve())
    elif args.out:
        directory = args.out.resolve()
        prepare(directory)
        if not args.prepare_only:
            run(directory)
    else:
        parser.error("--out, --run-prepared or --verify is required")
