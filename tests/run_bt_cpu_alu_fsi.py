"""Prove same-edge ALU field-size selection against immutable 0ecfb2f RTL.

The runner extracts the real instruction-update and field-size blocks, never
reimplements their update priority. The full native replay is a separate gate.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
REF = "0ecfb2f"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def git(*args):
    return subprocess.check_output([shutil.which("git") or "git", "-C", str(ROOT), *args])


def function(source, name):
    match = re.search(r"\tfunction automatic bit \[5:0\] " + name + r"\(.*?\tendfunction", source, re.S)
    if not match:
        raise RuntimeError("Missing actual RTL function " + name)
    return match.group()


def instruction_block(source):
    end = source.index("\tbit  [15: 0] LIST;")
    start = source.rfind("\talways @(posedge CLK or negedge RST_N)", 0, source.index("\t\tbit [31: 0] PC_NEXT;"))
    return source[start:end].strip()


def field_block(source):
    start = source.index("\tbit [5:0] FS0,FS1;")
    end = source.index("\tbit  [4:0] ALU_SA;") if "\tbit  [4:0] ALU_SA;" in source else source.index("\tbit [ 4: 0] ALU_SA;")
    body = source[start:end]
    return "always_comb" + body.split("always_comb", 1)[1]


def decoder(name, ic, matches, rs, state, de, sel):
    return f"""TMS34020_ID_ORACLE {name}(.CLK(CLK),.RST_N(RST_N),.EN(EN),.CE_R(CE_R),.CE_F(1'b0),
        .IC({ic}),.IC_MATCHES({matches}),.IC_RS_STATIC({rs}),
        .IC_RF_ADDR('0),.IC_RF_ADDR_POS('0),.OPSEL('0),.OPSEL_COMB({sel}),
        .STATE({state}),.STATE_OH(32'b1 << ({state})),
        .MD_COND(1'b0),.MD_NEG(1'b0),.DIV_V(1'b0),.J_COND(1'b0),.DS_COND(1'b0),.MM_COND(1'b0),
        .FE0(1'b0),.FE1(1'b0),.RP_COND(1'b0),.LINE_GZ(1'b0),.LINE_COND(1'b0),
        .PIX_XEND(1'b0),.PIX_YEND(1'b0),.PIX_WINEN(1'b0),.PIX_WINCC(4'b0),.PIX_BL(1'b0),.PIX_WE(1'b0),
        .DECI({de}),.DECI_AT_PRE());"""


def wrappers(candidate, original):
    helpers = function(candidate, "DecodeAluFSI") + "\n" + function(candidate, "AluFieldSize")
    code = ""
    for tag, source in [("candidate", candidate), ("oracle", original)]:
        code += f"""
module bt_alu_fsi_{tag}_instruction
  import TMS34020_PKG::*;
  (input bit CLK,RST_N,EN,CE_R,MC_WAIT,CACHE_WAIT,INT_REQ,J_COND,DS_COND,
   input DecInstr_t DECI,
   input bit [31:0] CACHE_Q,RF_RB_Q,MC_DIN,
   input bit [39:0] CACHE_RF_PRE,
   output bit [15:0] IC, output ICMatches_t IC_MATCHES,
   output bit [3:0] IC_RS_STATIC,
   output ICRFAddress_t IC_RF_ADDR,IC_RF_ADDR_POS,
   output OpSel_t OPSEL,
   output bit [31:0] IW,PC,STATE_OH,
   output bit [4:0] STATE, output bit RST_EXEC,
   output bit [1:0] WORD_MASK,
   output bit [5:0] OPSEL_ALU_FSI_OH);
  localparam OpSel_t OPSEL_RST=OPSEL_RST_CONST,OPSEL_INT=OPSEL_INT_CONST;
  OpSel_t OPSEL_NX,OPSEL_CACHE,ignored_sel;
  DecInstr_t OPSEL_NX_DECI,OPSEL_C_DECI,LIVE_DECI;
  wire [15:0] OPSEL_CIC = !PC[4] ? CACHE_Q[15:0] : CACHE_Q[31:16];
  {helpers if tag == 'candidate' else ''}
  {decoder('NX','IC','IC_MATCHES','IC_RS_STATIC','DECI.NST','OPSEL_NX_DECI','OPSEL_NX')}
  {decoder('CACHE','OPSEL_CIC','DecodeICMatches(OPSEL_CIC)','DecodeICRS(OPSEL_CIC)',"5'd0",'OPSEL_C_DECI','OPSEL_CACHE')}
  {decoder('LIVE','IC','IC_MATCHES','IC_RS_STATIC','STATE','LIVE_DECI','ignored_sel') if tag == 'oracle' else ''}
  {"assign OPSEL_ALU_FSI_OH=6'b1 << LIVE_DECI.FT.FSI;" if tag == 'oracle' else ''}
  {instruction_block(source)}
endmodule

module bt_alu_fsi_{tag}_field
  import TMS34020_PKG::*;
  (input DecInstr_t DECI,input ST_t ST,input bit [5:0] PSIZE,PIXBLT_PPW,OPSEL_ALU_FSI_OH,
   output bit [5:0] FS0,FS1,FS,output bit FE);
  {helpers if tag == 'candidate' else ''}
  {field_block(source)}
endmodule
"""
    return code, helpers


def wsl_path(path):
    resolved = path.resolve()
    return "/mnt/" + resolved.drive[0].lower() + "/" + resolved.as_posix()[3:]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    out = (args.out or ROOT / "tests/graphics/evidence" / ("cpu_alu_fsi_" + datetime.now().strftime("%Y%m%d_%H%M%S"))).resolve()
    out.mkdir(parents=True, exist_ok=False)
    commit = git("rev-parse", REF).decode().strip()
    names = ["rtl/TMS34020/TMS34020.sv", "rtl/TMS34020/TMS34020_pkg.sv", "rtl/TMS34020/TMS34020_ID.sv"]
    refs = {name: git("show", commit + ":" + name) for name in names}
    candidate = (ROOT / names[0]).read_bytes()
    for name in names[1:]:
        if (ROOT / name).read_bytes().replace(b"\r\n", b"\n") != refs[name].replace(b"\r\n", b"\n"):
            raise RuntimeError("Decoder dependency changed from immutable oracle: " + name)
    originals = out / "immutable_oracle"
    originals.mkdir()
    for name, data in refs.items():
        (originals / Path(name).name).write_bytes(data)
    wrapper, helper = wrappers(candidate.decode(), refs[names[0]].decode())
    (out / "instruction_and_field_slices.sv").write_text(wrapper)
    (out / "alu_fsi_helpers.svh").write_text(helper)
    (out / "TMS34020_ID_ORACLE.sv").write_text(refs[names[2]].decode().replace("module TMS34020_ID", "module TMS34020_ID_ORACLE", 1))
    tb = ROOT / "tests/bt_cpu_alu_fsi_tb.sv"
    files = [originals / "TMS34020_pkg.sv", out / "TMS34020_ID_ORACLE.sv", out / "instruction_and_field_slices.sv", tb]
    command = ["wsl.exe", "-d", "Ubuntu", "--cd", str(ROOT), "--exec", "/usr/bin/verilator", "--binary", "--assert", "--timing", "-j", "2", "--top-module", "bt_cpu_alu_fsi_tb", "-Wno-fatal", "-I" + wsl_path(out), "--Mdir", wsl_path(out / "obj"), *[wsl_path(f) for f in files]]
    receipt = {"oracle_commit": commit, "oracle_sha256": {n:sha(d) for n,d in refs.items()}, "candidate_cpu_sha256":sha(candidate), "candidate_dependency_sha256":{n:sha((ROOT/n).read_bytes()) for n in names[1:]}, "decoder_dependency_comparison":"Exact committed content after CRLF-to-LF normalization only; compiled oracle namespace renamed TMS34020_ID_ORACLE", "testbench_sha256":sha(tb.read_bytes()), "runner_sha256":sha(Path(__file__).read_bytes()), "extracted_slices_sha256":sha(wrapper.encode()), "command":command, "scope":"Real instruction-update and field-size RTL slices; exhaustive opcode/state and field inputs, reset/interrupt/stall/enable/CE behavior. Full native raster replay remains required."}
    with (out / "build.log").open("w") as log:
        build = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    receipt["build_exit_code"] = build.returncode
    result = build
    if not build.returncode:
        run_command = ["wsl.exe", "-d", "Ubuntu", "--cd", str(ROOT), "--exec", wsl_path(out / "obj/Vbt_cpu_alu_fsi_tb")]
        with (out / "run.log").open("w") as log:
            result = subprocess.run(run_command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        receipt["run_command"] = run_command
        receipt["run_exit_code"] = result.returncode
    (out / "receipt.json").write_text(json.dumps(receipt, indent=2))
    print("receipt=" + str(out / "receipt.json"))
    print((out / ("run.log" if (out / "run.log").exists() else "build.log")).read_text(errors="replace")[-3500:])
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
