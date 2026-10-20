"""Simulate the wrapper's player wiring through BT's actual input read mux.

Uses Ubuntu WSL on Windows. Expected masks follow MAME rare/btoads.cpp,
INPUT_PORTS_START(btoads), rather than the wrapper's concatenation order.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid


ROOT = Path(__file__).resolve().parents[1]


def extract(pattern, source):
    match = re.search(pattern, source, re.MULTILINE | re.DOTALL)
    if not match:
        raise ValueError(f"Missing RTL section: {pattern}")
    return match.group(0)


def make_bench(wrapper):
    board = (ROOT / "rtl/BT.sv").read_text()
    ports = extract(r"\bBT\s*(?:#\(.*?\)\s*)?BT\s*\(.*?\n\s*\);", wrapper)
    wires = "\n".join(re.findall(r"^\s*wire \[7:0\] P[123] = [^;]+;", wrapper, re.MULTILINE))
    connections = ",\n".join(extract(rf"\.{name}\([^\n]+?\)", ports) for name in ("SW1", "P1", "P2", "P3"))
    for player in range(3):
        extract(rf"\.joystick_{player}\(joy{player}\)", wrapper)
    decode = extract(r"wire MISC_SEL = [^;]+;", board)
    mux = extract(r"bit\s*\[\s*7:\s*0\]\s*MISC_DO;.*?endcase\s+end", board)
    read_data = extract(r"assign LDI = .*?;", board)
    read_select = extract(r"wire \[7:0\] LDI_SELECT_NEXT = .*?always @\(posedge CLK\) begin.*?\n\s*end", board)
    dip_latch = ""
    dip_checks = ""
    if ".SW1(dips_sw1)" in connections:
        dip_latch = extract(r"reg \[7:0\] dips_sw1 = [^;]+;[^\n]*\n\s*always @\(posedge clk_sys\) begin.*?\n\s*end", wrapper)
        dip_checks = """
            initial_dip=cabinet;
            write_dip(16'd0,27'd0,8'h00);
            if (cabinet !== initial_dip) $fatal(1,"Unrelated ioctl index changed DIPs");
            write_dip(16'd254,27'd1,8'h00);
            if (cabinet !== initial_dip) $fatal(1,"Unrelated ioctl address changed DIPs");
            write_dip(16'd254,27'd0,initial_dip | 8'h08);
            if (cabinet !== (initial_dip | 8'h08)) $fatal(1,"Configured two-player DIP not applied");
            write_dip(16'd254,27'd0,initial_dip);
            if (cabinet !== initial_dip) $fatal(1,"Configured three-player DIP not applied");
            for (pattern=0;pattern<256;pattern=pattern+1) begin
                write_dip(16'd254,27'd0,pattern);
                if (cabinet !== pattern[7:0]) $fatal(1,"Physical SW1 bit mapping mismatch");
            end
            write_dip(16'd254,27'd0,initial_dip);
            $display("PASS: DIP ioctl filtering, all 256 physical switch combinations and CPU readback");
        """
    return f"""
module board_inputs(input CLK, input [7:0] P1,P2,P3,SW1, input [31:0] LA,
                    output [31:0] LDI, output [7:0] cabinet);
    wire Z80_CTRL_RDY=0, SERVICE=1, Z80_RESP_RDY=0;
    wire [7:0] Z80_RESP_DATA=0;
    wire [7:0] PAL_WADDR=0, PAL_READ_DATA=0, PAL_MASK=0, PAL_RADDR=0;
    wire EFG=0, ERAM=0, EROM=0, ENVRAM=0;
    wire SPR_SEL=0, FG0_SEL=0, FG1_SEL=0, BG0_SEL=0, BG1_SEL=0;
    wire [31:0] EQ=0;
    wire [15:0] FG0_Q=0, FG1_Q=0, BG0_Q_1=0, BG0_Q_0=0, BG1_Q_1=0, BG1_Q_0=0;
    {decode}
    {mux}
    {read_select}
    {read_data}
    assign cabinet = SW1;
endmodule

module tb;
    reg [31:0] joy0=0,joy1=0,joy2=0,LA=0;
    reg clk_sys=0,ioctl_wr=0;
    reg [15:0] ioctl_index=0,ioctl_dout=0;
    reg [26:0] ioctl_addr=0;
    always #5 clk_sys=~clk_sys;
    wire [31:0] LDI;
    wire [7:0] cabinet;
    {dip_latch}
    {wires}
    board_inputs BT(.CLK(clk_sys),.LA(LA),.LDI(LDI),.cabinet(cabinet),{connections});
    integer player,pattern,p,checks=0;
    reg [7:0] expected;
    reg [7:0] initial_dip;

    // MiSTer directions R,L,D,U; MAME masks R=02,L=08,D=04,U=01.
    function automatic [7:0] expected_port(input [31:0] j);
        reg [7:0] pressed;
        begin
            pressed=0;
            if (j[0]) pressed=pressed | 8'h02;
            if (j[1]) pressed=pressed | 8'h08;
            if (j[2]) pressed=pressed | 8'h04;
            if (j[3]) pressed=pressed | 8'h01;
            if (j[4]) pressed=pressed | 8'h10; // Button 1
            if (j[5]) pressed=pressed | 8'h20; // Button 2
            if (j[6]) pressed=pressed | 8'h40; // Coin
            if (j[7]) pressed=pressed | 8'h80; // Start
            expected_port=~pressed;
        end
    endfunction

    task automatic check_ports;
        begin
            for (p=0;p<3;p=p+1) begin
                // TMS34020 bit addresses, including the low-bit alias.
                @(negedge clk_sys);
                LA=32'h20000000 + p*32'h80;
                case(p)
                    0: expected=expected_port(joy0);
                    1: expected=expected_port(joy1);
                    2: expected=expected_port(joy2);
                endcase
                @(posedge clk_sys); #1;
                if (LDI !== {{24'h000000,expected}})
                    $fatal(1,"P%0d input mismatch: joy=%h/%h/%h read=%h expected=%h",
                           p+1,joy0,joy1,joy2,LDI,expected);
                LA=LA | 32'h1f;
                @(posedge clk_sys); #1;
                if (LDI !== {{24'h000000,expected}}) $fatal(1,"P%0d address alias",p+1);
                checks=checks+2;
            end
        end
    endtask

    task automatic write_dip(input [15:0] index,input [26:0] address,input [7:0] value);
        begin
            @(negedge clk_sys);
            ioctl_wr=1; ioctl_index=index; ioctl_addr=address; ioctl_dout={{8'h00,value}};
            @(posedge clk_sys);
            #1;
            @(negedge clk_sys);
            ioctl_wr=0;
            LA=32'h20000280;
            @(posedge clk_sys); #1;
            if (LDI !== {{24'h000000,cabinet}}) $fatal(1,"CPU DIP readback mismatch");
        end
    endtask

    initial begin
        #1;
        if ($test$plusargs("dip_only")) begin
            if (^cabinet === 1'bx) $fatal(1,"Cabinet DIP contains undriven or unknown bits");
            if (cabinet[3] !== 1'b0) $fatal(1,"Three Players DIP is disabled");
            $display("PASS: Three Players DIP enabled (SW1=%h)",cabinet);
            {dip_checks}
            $finish;
        end
        for (player=0;player<3;player=player+1) begin
            for (pattern=0;pattern<256;pattern=pattern+1) begin
                joy0=0; joy1=0; joy2=0;
                case(player)
                    0: joy0=pattern;
                    1: joy1=pattern;
                    2: joy2=pattern;
                endcase
                check_ports();
            end
        end
        for (pattern=0;pattern<256;pattern=pattern+1) begin
            joy0=pattern; joy1=pattern ^ 8'h55; joy2=pattern ^ 8'haa;
            check_ports();
        end
        joy0=32'hffffff00; joy1=32'hffffff00; joy2=32'hffffff00;
        check_ports();
        $display("PASS: %0d CPU input reads; all players, combinations, isolation, aliases and unused bits",checks);
        $finish;
    end
endmodule
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wrapper", type=Path, default=ROOT / "Arcade-Battletoads.sv")
    args = parser.parse_args()
    for name in (("wsl.exe",) if os.name == "nt" else ("iverilog", "vvp")):
        if not shutil.which(name):
            parser.error(f"{name} must be on PATH")
    retained = ROOT / "build/player_inputs" / ("inputs-" + uuid.uuid4().hex)
    retained.mkdir(parents=True)
    inputs = [args.wrapper.resolve(), ROOT / "rtl/BT.sv", Path(__file__).resolve()]
    hashes = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}
    bench, binary = retained / "tb.sv", retained / "tb.vvp"
    bench.write_text(make_bench(args.wrapper.read_text()), encoding="utf-8")
    relative = retained.relative_to(ROOT).as_posix()
    commands = [["iverilog", "-g2012", "-s", "tb", "-o", relative + "/tb.vvp", relative + "/tb.sv"]]
    commands.extend([["vvp", relative + "/tb.vvp", mode] for mode in ("+dip_only", "+controls")])
    results = []
    for number, command in enumerate(commands):
        actual = ["wsl.exe", "-d", "Ubuntu", "--cd", str(ROOT), "--exec", *command] if os.name == "nt" else command
        result = subprocess.run(actual, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
        (retained / f"phase_{number}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        results.append({"command": actual, "exit_code": result.returncode})
        if result.returncode:
            raise RuntimeError(f"Player-input regression failed; retained evidence: {retained}")
        if result.stdout:
            print(result.stdout.strip())
    if hashes != {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs}:
        raise RuntimeError("Player-input source changed during qualification")
    receipt = {"status": "PASS", "inputs": hashes, "commands": results,
               "bench_sha256": hashlib.sha256(bench.read_bytes()).hexdigest(),
               "scope": "Actual wrapper input wiring, DIP latch, production misc mux and registered read selector; 6150 player reads and 256 DIP combinations. No CPU retirement or hardware claim."}
    (retained / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print("Player-input evidence: " + str(retained / "receipt.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
