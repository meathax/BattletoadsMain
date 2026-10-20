"""Actual Intel four-state proof and unchanged complete sprite consumers.

The additional foreground fixture spies on actual RAM input pins, with a
clearly marked leaf stub; it makes no new physical RAM simulation claim.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TOOLS = Path("D:/q17/modelsim_ase/win32aloem")
VENDOR = Path("D:/q17/quartus/eda/sim_lib/altera_mf.v")
VENDOR_SHA = "c2f3f75264468c5ef594c5864fa81b550d113f40e3027c700c6153106d247213"
PREPARER = ROOT / "tests/graphics/prepare_bt_sprite_bank_mirrors.py"
OLD_PROOF = ROOT / "build/sprite_fg_local_q_v18_v1/proof-r3/receipt.json"
OLD_PROOF_SHA = "ed5eb483ab2e4884c1beb8b2378dcf24c60a07525e7111c65f27f08faf7c940e"

PIN_BENCH = r'''`timescale 1ns/1ps
module VRAM_MEM_64Kx8 #(parameter ADDR_WIDTH=14,SQ_REG=1,QA_REG=0,SERIAL_WRITE_DECODE=1,LANE_WREN_PRE=1,QSEL_EN=1,SERIAL_SEGMENT_PRE=1)(
 input CLK,input[12:0]ADDR,input[15:0]DATA,input WREN,input[1:0]BE,output[15:0]Q,
 input[10:0]SADDR,input[63:0]SDATA,input SWREN,output[63:0]SQ,input[10:0]SADDR_W,
 input[1:0]WREN_LANE,input QGATE_D,input[3:0]SWREN_SEGMENT);
 // Pin spy only. The physical RAM body is unchanged and separately qualified.
 assign Q=QGATE_D ? DATA : 16'b0;
 assign SQ=SDATA;
endmodule
module sprite_bank_ram_pin_tb;
 reg clk=0;
 always #3.125 clk=~clk;
 reg[15:1] addr=0;reg[3:0][15:1] addr_b=0;reg[3:0][15:0] data_b=0;
 reg[15:0] data=0,bw=0;reg[1:0]be=0;
 reg[15:3]sw=0,sc=0,sv=0,scn=0;
 reg[3:0][12:0]swb=0;reg[3:0]sr=0,ss=0,swe=0,sel=0,pre=0,bwp=0;
 reg[3:0][3:0]sel4=0,seg=0;reg[3:0][10:0]svb=0,scb=0,scnb=0;
 reg[3:0][1:0]lane=0;reg copy_we=0;
 reg[63:0]cpu=0,serial=0;reg[3:0][63:0]bank_cpu=0,foreign_cpu=0;
 wire[15:0]qo,qa,qd;wire[63:0]so,sa,sd,sdo,sda,sdd;
 integer cases=0;integer pre_checks[4]='{default:0},post_checks[4]='{default:0};
 BT_FG_BANKED_VRAM_V20 #(1,1,1,1) original(
  .CLK(clk),.ADDR(addr),.ADDR_B(addr_b),.DATA_B(data_b),.DATA(data),.BANK_WREN(bw),.BE(be),.Q(qo),
  .SADDR_W(sw),.SADDR_C(sc),.SADDR_V(sv),.SADDR_WB(swb),.SRSEL(sr),.SWSEL(ss),.SWREN_B(swe),
  .SDATA_C(cpu),.SDATA_S(serial),.SCSEL(sel),.SCSEL4(sel4),.SQ(so),.SQ_D(sdo),.COPY_WE_NEXT(copy_we),
  .SADDR_CN(scn),.SADDR_VB(svb),.SADDR_CB(scb),.SADDR_CNB(scnb),.COPY_PREFETCH_B(pre),
  .BANK_WREN_PRE(bwp),.BANK_LANE_WREN_PRE(lane),.SWREN_SEG_B(seg));
 BT_FG_BANKED_VRAM_BANKS #(1,1,1,1,1) active(
  .CLK(clk),.ADDR(addr),.ADDR_B(addr_b),.DATA_B(data_b),.DATA(data),.BANK_WREN(bw),.BE(be),.Q(qa),
  .SADDR_W(sw),.SADDR_C(sc),.SADDR_V(sv),.SADDR_WB(swb),.SRSEL(sr),.SWSEL(ss),.SWREN_B(swe),
  .SDATA_C(cpu),.SDATA_CB(bank_cpu),.SDATA_S(serial),.SCSEL(sel),.SCSEL4(sel4),.SQ(sa),.SQ_D(sda),.COPY_WE_NEXT(copy_we),
  .SADDR_CN(scn),.SADDR_VB(svb),.SADDR_CB(scb),.SADDR_CNB(scnb),.COPY_PREFETCH_B(pre),
  .BANK_WREN_PRE(bwp),.BANK_LANE_WREN_PRE(lane),.SWREN_SEG_B(seg));
 BT_FG_BANKED_VRAM_BANKS #(1,1,1,1) default_off(
  .CLK(clk),.ADDR(addr),.ADDR_B(addr_b),.DATA_B(data_b),.DATA(data),.BANK_WREN(bw),.BE(be),.Q(qd),
  .SADDR_W(sw),.SADDR_C(sc),.SADDR_V(sv),.SADDR_WB(swb),.SRSEL(sr),.SWSEL(ss),.SWREN_B(swe),
  .SDATA_C(cpu),.SDATA_CB(foreign_cpu),.SDATA_S(serial),.SCSEL(sel),.SCSEL4(sel4),.SQ(sd),.SQ_D(sdd),.COPY_WE_NEXT(copy_we),
  .SADDR_CN(scn),.SADDR_VB(svb),.SADDR_CB(scb),.SADDR_CNB(scnb),.COPY_PREFETCH_B(pre),
  .BANK_WREN_PRE(bwp),.BANK_LANE_WREN_PRE(lane),.SWREN_SEG_B(seg));
 generate for(genvar bank=0;bank<4;bank++)begin:check_banks
  wire[139:0]po={original.banks[bank].ram.CLK,original.banks[bank].ram.ADDR,original.banks[bank].ram.DATA,
   original.banks[bank].ram.WREN,original.banks[bank].ram.BE,original.banks[bank].ram.SADDR,
   original.banks[bank].ram.SDATA,original.banks[bank].ram.SWREN,original.banks[bank].ram.SADDR_W,
   original.banks[bank].ram.WREN_LANE,original.banks[bank].ram.QGATE_D,original.banks[bank].ram.SWREN_SEGMENT};
  wire[139:0]pa={active.banks[bank].ram.CLK,active.banks[bank].ram.ADDR,active.banks[bank].ram.DATA,
   active.banks[bank].ram.WREN,active.banks[bank].ram.BE,active.banks[bank].ram.SADDR,
   active.banks[bank].ram.SDATA,active.banks[bank].ram.SWREN,active.banks[bank].ram.SADDR_W,
   active.banks[bank].ram.WREN_LANE,active.banks[bank].ram.QGATE_D,active.banks[bank].ram.SWREN_SEGMENT};
  wire[139:0]pd={default_off.banks[bank].ram.CLK,default_off.banks[bank].ram.ADDR,default_off.banks[bank].ram.DATA,
   default_off.banks[bank].ram.WREN,default_off.banks[bank].ram.BE,default_off.banks[bank].ram.SADDR,
   default_off.banks[bank].ram.SDATA,default_off.banks[bank].ram.SWREN,default_off.banks[bank].ram.SADDR_W,
   default_off.banks[bank].ram.WREN_LANE,default_off.banks[bank].ram.QGATE_D,default_off.banks[bank].ram.SWREN_SEGMENT};
  task automatic check_pins;
   assert(pa===po && pd===po)else $fatal(1,"actual foreground bank%0d pins changed old=%h active=%h default=%h",bank,po,pa,pd);
  endtask
  always @(posedge clk)begin
   check_pins();pre_checks[bank]++;#0.2;check_pins();post_checks[bank]++;
  end
 end endgenerate
 always @(posedge clk)begin
  #0.25;assert({qa,sa,sda,qd,sd,sdd}==={qo,so,sdo,qo,so,sdo})else $fatal(1,"old banked outputs changed");
 end
 function automatic reg symbol(input integer value);
  case(value)0:symbol=0;1:symbol=1;2:symbol=1'bx;3:symbol=1'bz;endcase
 endfunction
 initial begin
  for(integer word=0;word<8;word++)for(integer controls=0;controls<256;controls++)begin
   @(negedge clk);
   cpu=64'hD4831CA7690EBF52 ^ (64'(word)*64'h15398BA70EC64D2F);
   serial=~cpu;
   case(word)2:cpu[15:0]='x;3:cpu[31:16]='z;4:cpu[47:32]='x;5:cpu[63:48]='z;6:cpu='x;7:cpu='z;endcase
   addr=15'(word*917+controls*29);data=16'(controls*351);bw=16'(controls*19);be=2'(controls);
   sw=13'(controls*17);sc=13'(controls*29);sv=13'(controls*43);scn=sc+1;
   sr=4'(controls);ss=4'(controls>>2);swe=4'(controls>>4);sel=4'(controls>>6);pre=~sr;bwp=ss;copy_we=controls[3];
   for(integer bank=0;bank<4;bank++)begin
    bank_cpu[bank]=cpu;foreign_cpu[bank]=~cpu;
    addr_b[bank]=addr+15'(bank*271);data_b[bank]=data+16'(bank*77);swb[bank]=sw+13'(bank*33);
    svb[bank]=11'(sv+bank);scb[bank]=11'(sc+bank);scnb[bank]=11'(scn+bank);lane[bank]=2'(controls>>bank);seg[bank]=4'(controls+bank);
    for(integer chunk=0;chunk<4;chunk++)sel4[bank][chunk]=symbol((controls>>(chunk*2))&3);
   end
   @(posedge clk);#0.3;cases++;
  end
  assert(cases==2048)else $fatal(1,"pin selector cases missing");
  for(integer bank=0;bank<4;bank++)assert(pre_checks[bank]>=2048 && post_checks[bank]>=2048)else $fatal(1,"bank pin coverage missing");
  $display("SPRITE_BANK_PIN_PASS cases=%0d pre=%0d post=%0d banks=4 pins=12",cases,pre_checks[0]+pre_checks[1]+pre_checks[2]+pre_checks[3],post_checks[0]+post_checks[1]+post_checks[2]+post_checks[3]);
  $finish;
 end
endmodule
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def once(text, before, after):
    assert text.count(before) == 1, ("fixture anchor changed", before)
    return text.replace(before, after, 1)


def text(data):
    return data.decode("utf-8-sig").replace("\r\n", "\n")


def renamed_spr(data, suffix):
    source = text(data)
    for name in ("SPR_VRAM", "BT_SPR_POST_NONZERO_MIRROR"):
        source = re.sub(r"\b" + name + r"\b", name + suffix, source)
    return source.encode()


def bank_module(data, suffix):
    matches = list(re.finditer(r"\bmodule BT_FG_BANKED_VRAM\b.*?\bendmodule\b", text(data), re.S))
    assert len(matches) == 1
    return (matches[0].group(0).replace("module BT_FG_BANKED_VRAM ", "module BT_FG_BANKED_VRAM" + suffix + " ", 1) + "\n").encode()


def vendor_fixture(raw):
    fixture = text(raw)
    fixture = fixture.replace("BT_SPR_POST_NONZERO_MIRROR_LOCAL", "BT_SPR_POST_NONZERO_MIRROR_BANKS")
    fixture = once(fixture, "BT_SPR_POST_NONZERO_MIRROR #(10) original(", "BT_SPR_POST_NONZERO_MIRROR_V20 #(10,1) original(")
    fixture = once(fixture, "BT_SPR_POST_NONZERO_MIRROR_BANKS #(10,1) active(", "BT_SPR_POST_NONZERO_MIRROR_BANKS #(10,1,1) active(")
    fixture = once(fixture, "wire [15:0] no_,na,nd;", "wire [15:0] no_,na,nd;\n wire [1:0][3:0][63:0] ab,db;integer bank_checks=0,literal_control_cases=0;")
    fixture = once(fixture, ".Q(qa),.NZ(na),.FG0_Q(a0),.FG1_Q(a1));", ".Q(qa),.NZ(na),.FG0_Q(a0),.FG1_Q(a1),.FG_BANK_Q(ab));")
    fixture = once(fixture, ".Q(qd),.NZ(nd),.FG0_Q(d0),.FG1_Q(d1));", ".Q(qd),.NZ(nd),.FG0_Q(d0),.FG1_Q(d1),.FG_BANK_Q(db));")
    fixture = once(fixture, "endtask\n always @(posedge clk)", "for(integer fg=0;fg<2;fg++)for(integer bank=0;bank<4;bank++)begin\n   assert(ab[fg][bank]===qo && db[fg][bank]===qo)else $fatal(1,\"registered bank output changed fg=%0d bank=%0d\",fg,bank);\n   bank_checks++;\n  end\n endtask\n always @(posedge clk)")
    fixture = fixture.replace("reg [495:0] held;", "reg [1519:0] held;")
    fixture = fixture.replace("{qo,no_,qa,na,qd,nd,a0,a1,d0,d1}", "{qo,no_,qa,na,qd,nd,a0,a1,d0,d1,ab,db}")
    fixture = fixture.replace("496'b0", "1520'b0")
    extra = """ // New literal control cases, preserving every original assertion.
   for(integer trial=0;trial<50;trial++)begin
    @(negedge clk);wa=7'd17;ra=7'd17;we=0;data=64'h59CEAF1072BD8643;
    if(trial<14)ra[trial/2]=(trial%2)?1'bx:1'bz;
    else if(trial<28)begin we=8'hff;wa[(trial-14)/2]=(trial%2)?1'bx:1'bz;end
    else if(trial<44)we[(trial-28)/2]=(trial%2)?1'bx:1'bz;
    else case(trial)44:ra='x;45:ra='z;46:begin wa='x;we='1;end 47:begin wa='z;we='1;end 48:we='x;49:we='z;endcase
    cycles(3);literal_control_cases++;
   end
   @(negedge clk);we=0;wa=0;ra=0;cycles(3);
   assert(literal_control_cases==50)else $fatal(1,"control-XZ cases missing");
   $display("SPRITE_REGISTERED_BANKS checks=%0d mirrors=8 literal_control_cases=%0d",bank_checks,literal_control_cases);
"""
    fixture = once(fixture, "  $finish;", extra + "  $finish;")
    return fixture.encode()


def read_fixture(raw):
    fixture = text(raw)
    fixture = once(fixture, "SPR_VRAM reference_core(", "SPR_VRAM_V20 #(.LOCAL_FG_Q(1)) reference_core(")
    fixture = once(fixture, "SPR_VRAM_SYNC #(.LOCAL_FG_Q(1)) candidate_core(", "SPR_VRAM_BANKS #(.LOCAL_FG_Q(1),.REGISTERED_FG_BANK_Q(1)) candidate_core(")
    fixture = once(fixture, "wire [63:0] local_q0,local_q1;", "wire [63:0] local_q0,local_q1;wire [1:0][3:0][63:0] local_bank_q;integer bank_checks=0;")
    fixture = once(fixture, ".FG1_SHIFT_Q(local_q1),", ".FG1_SHIFT_Q(local_q1),.FG_BANK_SHIFT_Q(local_bank_q),")
    fixture = once(fixture, "full_local_checks++;", "for(integer fg=0;fg<2;fg++)for(integer bank=0;bank<4;bank++)begin\n            assert(local_bank_q[fg][bank]===cpu_q_old)else $fatal(1,\"complete sprite bank edge/value changed\");bank_checks++;\n        end\n        full_local_checks++;")
    first_end = fixture.index("endmodule")
    fixture = fixture[:first_end] + "final $display(\"SPRITE_BANK_READ_OUTPUTS checks=%0d mirrors=8\",bank_checks);\n" + fixture[first_end:]
    return fixture.encode()


def packet_fixture(raw):
    fixture = text(raw)
    fixture = once(fixture, "SPR_VRAM_SYNC #(.LOCAL_FG_Q(1)) dut(", "SPR_VRAM_BANKS #(.LOCAL_FG_Q(1),.REGISTERED_FG_BANK_Q(1)) dut(")
    fixture = once(fixture, "local_checks++;", "for(integer fg=0;fg<2;fg++)for(integer bank=0;bank<4;bank++)\n            assert(dut.FG_BANK_SHIFT_Q[fg][bank]===read_data)else $fatal(1,\"packet registered bank output differs\");\n        local_checks++;")
    return fixture.encode()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--edge", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    edge = Path(args.edge).resolve()
    output = Path(args.output).resolve()
    assert output.is_relative_to(ROOT / "build") and not output.exists()
    preparer = load(PREPARER, "sprite_bank_preparer")
    parents, candidates, manifest = preparer.verify_edge(edge)
    assert sha(VENDOR.read_bytes()) == VENDOR_SHA
    assert sha(OLD_PROOF.read_bytes()) == OLD_PROOF_SHA
    prior = json.loads(OLD_PROOF.read_bytes())
    old_compiled = OLD_PROOF.parent / "compiled"
    fixtures = {}
    for name in ("sprite_local_q_vendor_tb.sv", "sprite_read_equivalence_tb.sv", "sprite_packet_tb.sv"):
        path = old_compiled / name
        raw = path.read_bytes()
        assert sha(raw) in json.dumps(prior), (name, "old tested fixture changed")
        fixtures[name] = raw
    inputs = {
        "spr_v20.sv": renamed_spr(parents["rtl/spr_vram.sv"], "_V20"),
        "spr_banks.sv": renamed_spr(candidates["rtl/spr_vram.sv"], "_BANKS"),
        "BT_mem.sv": preparer.MEM.read_bytes(),
        "sprite_local_q_vendor_tb.sv": vendor_fixture(fixtures["sprite_local_q_vendor_tb.sv"]),
        "sprite_read_equivalence_tb.sv": read_fixture(fixtures["sprite_read_equivalence_tb.sv"]),
        "sprite_packet_tb.sv": packet_fixture(fixtures["sprite_packet_tb.sv"]),
    }
    pin_inputs = {"bank_v20.sv": bank_module(parents["rtl/fg_vram.sv"], "_V20"),
                  "bank_banks.sv": bank_module(candidates["rtl/fg_vram.sv"], "_BANKS"),
                  "sprite_bank_ram_pin_tb.sv": PIN_BENCH.encode()}
    negatives = []
    mutations = [
        ("hard_output_reset", "rtl/spr_vram.sv", b".ACLR(1'b0),.WADDR(WADDR)", b".ACLR(ACLR),.WADDR(WADDR)"),
        ("extra_output_cycle", "rtl/spr_vram.sv", b"#(addr_width,1,1) mirror", b"#(addr_width,1,0) mirror"),
        ("wrong_read_address", "rtl/spr_vram.sv", b".RADDR(RADDR)", b".RADDR(WADDR)"),
        ("old_alias_wrong_fg", "rtl/spr_vram.sv", b"FG0_Q=FG_BANK_Q[0][0]", b"FG0_Q=FG_BANK_Q[1][0]"),
        ("activation_missing", "rtl/BT.sv", b".REGISTERED_FG_BANK_Q(1)", b".REGISTERED_FG_BANK_Q(0)"),
        ("wrong_bank_binding", "rtl/BT.sv", b".CPU_SHIFT_BANK_Q(FG_BANK_SHIFT_Q[0])", b".CPU_SHIFT_BANK_Q(FG_BANK_SHIFT_Q[1])"),
        ("wrong_mux_lane", "rtl/fg_vram.sv", b"bank_cpu_data[63:48]", b"bank_cpu_data[47:32]"),
        ("default_on", "rtl/fg_vram.sv", b"REGISTERED_FG_BANK_Q=0", b"REGISTERED_FG_BANK_Q=1"),
    ]
    for label, rel, before, after in mutations:
        assert before in candidates[rel]
        changed = candidates[rel].replace(before, after, 1)
        try:
            recovered = preparer.inverse(changed, manifest["files"][rel]["edits"])
            assert recovered == parents[rel]
        except AssertionError:
            negatives.append(label)
        else:
            raise AssertionError((label, "source mutation accepted"))
    output.mkdir(parents=True)
    compiled = output / "compiled"
    compiled.mkdir()
    for name, data in {**inputs, **pin_inputs}.items():
        (compiled / name).write_bytes(data)
    preparation = {
        "schema": "bt-v20-sprite-bank-mirror-proof-preparation-v1",
        "edge": str(edge / "manifest.json"), "edge_sha256": sha((edge / "manifest.json").read_bytes()),
        "source_files": {str(edge / "candidate" / rel): sha(data) for rel, data in candidates.items()},
        "oracle_files": {str(edge / "oracle" / rel): sha(data) for rel, data in parents.items()},
        "compiled_sources": {str(compiled / name): sha(data) for name, data in {**inputs, **pin_inputs}.items()},
        "fixture_parents": {str(old_compiled / name): sha(data) for name, data in fixtures.items()},
        "fixture_scope": "old assertions and stimulus retained; eight bank equality checks and 50 literal control cases appended",
        "namespace_edge": "module and instantiation names only; LF/CRLF normalization only",
        "ram_pin_spy_scope": "entire old/new actual BT_FG_BANKED_VRAM; unchanged physical leaf replaced only in separate pin_work library",
        "vendor": {str(VENDOR): VENDOR_SHA}, "old_fixture_proof": {str(OLD_PROOF): OLD_PROOF_SHA},
        "negative_controls_rejected": negatives,
        "helpers": {str(PREPARER): sha(PREPARER.read_bytes()), str(Path(__file__).resolve()): sha(Path(__file__).read_bytes())},
    }
    (output / "preparation.json").write_text(json.dumps(preparation, indent=2) + "\n")
    (output / "executed_helper.py").write_bytes(Path(__file__).read_bytes())
    commands = [
        [str(TOOLS / "vlib.exe"), "work"],
        [str(TOOLS / "vlog.exe"), "-sv", "-work", "work"] + [str(compiled / name) for name in inputs] + [str(VENDOR)],
        [str(TOOLS / "vlib.exe"), "pin_work"],
        [str(TOOLS / "vlog.exe"), "-sv", "-work", "pin_work"] + [str(compiled / name) for name in pin_inputs],
    ]
    runs = []
    for index, command in enumerate(commands):
        log = output / ("vendor_compile.log" if index < 2 else "pin_compile.log")
        with log.open("ab") as stream:
            result = subprocess.run(command, cwd=output, stdout=stream, stderr=subprocess.STDOUT, timeout=600)
        runs.append({"command": command, "exit_code": result.returncode, "log": str(log), "log_sha256": sha(log.read_bytes())})
        assert result.returncode == 0, ("compile failed; preserve log", str(log))
    coverage = {}
    tops = [("work.sprite_local_q_vendor_tb", "SPRITE_LOCAL_VENDOR_PASS"),
            ("work.sprite_read_equivalence_tb", "PASS sprite transaction equivalence"),
            ("work.sprite_packet_tb", "SPRITE_PACKET_PASS"),
            ("pin_work.sprite_bank_ram_pin_tb", "SPRITE_BANK_PIN_PASS")]
    for top, marker in tops:
        log = output / (top.split(".")[1] + ".log")
        command = [str(TOOLS / "vsim.exe"), "-c", top, "-do", "onerror {quit -code 1}; run -all; quit -code 0"]
        with log.open("wb") as stream:
            result = subprocess.run(command, cwd=output, stdout=stream, stderr=subprocess.STDOUT, timeout=1200)
        logtext = log.read_text(errors="replace")
        runs.append({"command": command, "exit_code": result.returncode, "log": str(log), "log_sha256": sha(log.read_bytes())})
        assert result.returncode == 0 and marker in logtext and not re.search(r"\*\* (?:Fatal|Error):", logtext), ("proof failed", str(log))
        coverage[top] = [line.strip() for line in logtext.splitlines() if any(m in line for m in ("_PASS", "PASS sprite", "SPRITE_LOCAL_", "SPRITE_REGISTERED_", "SPRITE_BANK_"))]
    receipt = {"schema": "bt-v20-sprite-bank-registered-mirror-qualification-v1",
               "status": "PASS_VENDOR_4STATE_SPRITE_AND_ACTUAL_BANK_PINS",
               "preparation": str(output / "preparation.json"), "preparation_sha256": sha((output / "preparation.json").read_bytes()),
               "runs": runs, "coverage": coverage, "negative_controls_rejected": negatives,
               "x_exclusions": 0, "collision_exclusions": 0,
               "actual_Intel_vendor_RAM": True, "pin_spy_is_physical_RAM_proof": False,
               "whole_board_native_rerun": False, "mapped_ram_replicas_or_placement_proven": False,
               "core_timing_accepted": False, "rbf_generated": False, "root_modified": False}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"status": receipt["status"], "receipt": str(output / "receipt.json"), "coverage": coverage}))


if __name__ == "__main__":
    main()
