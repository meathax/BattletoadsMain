#!/usr/bin/env python3
"""Compile the full unchanged old/current pixel processes with ModelSim."""
import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "tests/graphics/prepare_bt_pixel_parallel.py"
SIM = Path("D:/q17/modelsim_ase/win32aloem")
HEADER = b"""(input logic CLK, RST_N, VCE_DIV, HBL_N,
input logic [7:0] FG0_SQ, FG1_SQ, input logic [15:0] BG0_SQ, BG1_SQ, DISP_CONTROL,
input logic [2:0] BG_EN, output wire [7:0] RESULT);
"""
BENCH = r"""module bt_pixel_parallel_tb;
  logic CLK=0, RST_N=0, VCE_DIV=0, HBL_N=0;
  logic [7:0] FG0_SQ=0, FG1_SQ=0;
  logic [15:0] BG0_SQ=0, BG1_SQ=0, DISP_CONTROL=0;
  logic [2:0] BG_EN=0;
  wire [7:0] OLD_RESULT, NEW_RESULT;
  integer checks=0, categories=0, values=0, unknowns=0, resets=0;
  bt_pixel_old old_i(CLK,RST_N,VCE_DIV,HBL_N,FG0_SQ,FG1_SQ,BG0_SQ,BG1_SQ,DISP_CONTROL,BG_EN,OLD_RESULT);
  bt_pixel_new new_i(CLK,RST_N,VCE_DIV,HBL_N,FG0_SQ,FG1_SQ,BG0_SQ,BG1_SQ,DISP_CONTROL,BG_EN,NEW_RESULT);
  function automatic logic four(input integer value);
    case(value) 0:four=0;1:four=1;2:four=1'bx;3:four=1'bz;endcase
  endfunction
  function automatic logic [7:0] data(input integer value);
    case(value)
      0:data=8'h00;1:data=8'h35;2:data=8'hb6;3:data=8'hxx;
      4:data=8'hzz;5:data=8'b1x0z0101;6:data=8'b0xz00000;7:data=8'bxx111zzz;
    endcase
  endfunction
  task automatic tick;
    begin
      #2 CLK=1; #1;
      checks=checks+1;
      if(OLD_RESULT !== NEW_RESULT) $fatal(1,"PIXEL mismatch check=%0d old=%h new=%h ctrl=%h en=%b",checks,OLD_RESULT,NEW_RESULT,DISP_CONTROL,BG_EN);
      CLK=0; #1;
    end
  endtask
  integer m,s,b0,b1,e,bank,alias_i,v,which,u,a,b,c,p;
  initial begin
    tick; RST_N=1;
    for(m=0;m<4;m=m+1) for(s=0;s<3;s=s+1) for(b0=0;b0<2;b0=b0+1)
    for(b1=0;b1<3;b1=b1+1) for(e=0;e<8;e=e+1) for(bank=0;bank<4;bank=bank+1)
    for(alias_i=0;alias_i<2;alias_i=alias_i+1) begin
      DISP_CONTROL=0;DISP_CONTROL[9:8]=m;DISP_CONTROL[15]=alias_i;
      BG_EN=e;VCE_DIV=bank[1];HBL_N=bank[0];
      FG0_SQ=data(s);FG1_SQ=data(s);
      BG0_SQ={b0?8'h29:8'h00,b0?8'h19:8'h00};
      BG1_SQ={data(b1),data(b1)};
      tick;categories=categories+1;
    end
    for(v=0;v<256;v=v+1) for(which=0;which<3;which=which+1)
    for(m=0;m<4;m=m+1) for(e=0;e<8;e=e+1) for(bank=0;bank<4;bank=bank+1) begin
      DISP_CONTROL=0;DISP_CONTROL[9:8]=m;DISP_CONTROL[15]=v[0];BG_EN=e;
      VCE_DIV=bank[1];HBL_N=bank[0];FG0_SQ=8'h59;FG1_SQ=8'hc7;
      BG0_SQ=16'h2619;BG1_SQ=16'hb748;
      case(which)
        0:begin FG0_SQ=v;FG1_SQ=~v;end
        1:BG0_SQ={8'(v),8'(~v)};
        2:BG1_SQ={8'(v),8'(~v)};
      endcase
      tick;values=values+1;
    end
    for(u=0;u<16;u=u+1) for(e=0;e<64;e=e+1) for(bank=0;bank<16;bank=bank+1)
    for(p=0;p<8;p=p+1) begin
      DISP_CONTROL=0;DISP_CONTROL[9]=four(u/4);DISP_CONTROL[8]=four(u%4);
      DISP_CONTROL[15]=four(p%4);BG_EN={four(e/16),four((e/4)%4),four(e%4)};
      VCE_DIV=four(bank/4);HBL_N=four(bank%4);
      FG0_SQ=data(p);FG1_SQ=data((p+3)%8);
      BG0_SQ={data((p+1)%8),data((p+2)%8)};
      BG1_SQ={data((p+4)%8),data((p+5)%8)};
      tick;unknowns=unknowns+1;
    end
    for(p=0;p<4;p=p+1) for(m=0;m<4;m=m+1) for(e=0;e<8;e=e+1) begin
      RST_N=1;DISP_CONTROL[9:8]=m;BG_EN=e;tick;
      #1 RST_N=0;#1;
      if(OLD_RESULT !== NEW_RESULT || OLD_RESULT !== 8'h00) $fatal(1,"PIXEL async reset mismatch");
      RST_N=four(p);tick;resets=resets+1;
    end
    $display("PIXEL_PARALLEL_PASS checks=%0d categories=%0d values=%0d unknowns=%0d resets=%0d",checks,categories,values,unknowns,resets);
    $finish;
  end
endmodule
"""


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--edge", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Proof output must be new")
    manifest = json.loads((args.edge / "manifest.json").read_bytes())
    if sha(HELPER.read_bytes()) != manifest["helper_sha256"]:
        raise ValueError("Frozen pixel helper changed")
    spec = importlib.util.spec_from_file_location("pixel_edge", HELPER)
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    candidate = Path(manifest["candidate"]).read_bytes()
    proof = helper.verify_source(candidate, manifest["edits"])
    parent = helper.reverse(candidate, manifest["edits"])
    args.output.mkdir(parents=True)
    old = b"module bt_pixel_old" + HEADER + helper.pixel_fragment(parent) + b"assign RESULT=PIX_OUT; endmodule\n"
    new = b"module bt_pixel_new" + HEADER + helper.pixel_fragment(candidate) + b"assign RESULT=PIX_OUT; endmodule\n"
    inputs = {"pixel_old.sv": old, "pixel_new.sv": new, "pixel_tb.sv": BENCH.encode()}
    for name, data in inputs.items():
        (args.output / name).write_bytes(data)
    commands = [[str(SIM / "vlib.exe"), str(args.output / "work")],
                [str(SIM / "vlog.exe"), "-sv", "-work", str(args.output / "work"), *[str(args.output / n) for n in inputs]],
                [str(SIM / "vsim.exe"), "-c", "-assertdebug", "-onfinish", "stop", "-lib", str(args.output / "work"), "bt_pixel_parallel_tb", "-do", "run -all; quit -code 0"]]
    runs = []
    for number, command in enumerate(commands):
        start = time.monotonic()
        completed = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW, timeout=300)
        log = args.output / f"step-{number}.log"; log.write_bytes(completed.stdout)
        runs.append({"command": command, "exit_code": completed.returncode, "seconds": time.monotonic()-start,
                     "log": str(log), "log_sha256": sha(completed.stdout)})
        if completed.returncode or re.search(rb"(?mi)^#?\s*\*\*\s*(?:Error|Fatal):", completed.stdout):
            raise ValueError("ModelSim compile/runtime error: " + str(log))
    transcript = (args.output / "step-2.log").read_bytes()
    marker = re.search(rb"PIXEL_PARALLEL_PASS checks=(\d+) categories=(\d+) values=(\d+) unknowns=(\d+) resets=(\d+)", transcript)
    expected = (234241, 4608, 98304, 131072, 128)
    if not marker or tuple(map(int, marker.groups())) != expected:
        raise ValueError("Complete expected pixel coverage marker missing")
    receipt = {"schema": "bt-pixel-parallel-modelsim-proof-v1", "status": "PASS_SCOPED_PIXEL_PROCESS",
               "edge_manifest": str(args.edge / "manifest.json"), "edge_manifest_sha256": sha((args.edge / "manifest.json").read_bytes()),
               "qualifier_sha256": sha(Path(__file__).read_bytes()), "source_proof": proof,
               "compiled_inputs": {n: sha(d) for n, d in inputs.items()}, "runs": runs,
               "counts": dict(zip(("checks", "categories", "values", "unknowns", "resets"), expected)),
               "scope": "Actual unchanged complete old/current pixel processes, local bit coercions, bank mux holding, priorities and reset; no full BT/vendor or hardware claim",
               "timing": "UNRUN", "assertions_removed": 0, "excluded_cases": 0}
    (args.output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "counts": receipt["counts"], "receipt": str(args.output / "receipt.json")}))


if __name__ == "__main__":
    main()
