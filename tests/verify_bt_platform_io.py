#!/usr/bin/env python3
"""Source-bound MCP23009 phase/poll proof; run Linux ELF inside Ubuntu WSL.

This does not certify board edge rates or native fitted routing. Its receipt
states those separate release gates explicitly. No Quartus DB is modified.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP = "bt_mcp23009_phase_tb"
SOURCES = ["sys/i2c.v", "rtl/bt_mcp23009.sv", "tests/bt_mcp23009_phase_tb.sv"]
ENVELOPE = {
    "fpga_to_scl_ns": 20, "fpga_to_sda_ns": 50, "sda_to_capture_ns": 100,
    "capture_clock_latency_ns": 50, "board_each_way_ns": 10,
    "scl_fall_ns": 40, "scl_rise_ns": 900, "sda_fall_ns": 300,
    "sda_rise_ns": 1000, "slave_taa_ns": 3450, "receiver_aperture_ns": 20,
}

def normalized(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")

def fnv(body: bytes) -> str:
    value = 2166136261
    for byte in body:
        value = ((value ^ byte) * 16777619) & 0xffffffff
    return f"{value:08x}"

def source_contract() -> dict:
    upstream = normalized(ROOT / "sys/mcp23009.sv")
    local = normalized(ROOT / "rtl/bt_mcp23009.sv")
    header, separator, implementation = local.partition(b"// BEGIN UNMODIFIED UPSTREAM BODY\n")
    assert separator and b"100 kHz" in header, "Missing local-source provenance"
    expected = upstream.replace(b"i2c #(50_000_000, 500_000)", b"i2c #(50_000_000, 100_000)")
    assert expected != upstream and implementation == expected, "MCP override must change only the bus rate"
    sdc = (ROOT / "rtl/bt_platform_io.sdc").read_text(encoding="utf-8")
    bound_sources = re.findall(r"^\s+(sys/(?:i2c\.v|sys_top\.v)|rtl/bt_mcp23009\.sv) ([0-9a-f]{8})$", sdc, re.M)
    assert len(bound_sources) == 3, "Missing executable SDC source bindings"
    for path, checksum in bound_sources:
        assert fnv(normalized(ROOT/path)) == checksum, f"SDC source changed: {path}"
    core = (ROOT / "Arcade-Battletoads.sv").read_text(encoding="utf-8")
    assert re.search(r"assign\s+USER_OUT\s*=\s*'1\s*;", core), "Core USER outputs must be released"
    assert re.search(r"assign\s+\{SD_SCK,\s*SD_MOSI,\s*SD_CS\}\s*=\s*'Z\s*;", core), "Core SD SPI must be inactive"
    return {path: {"fnv1a_normalized": checksum, "sha256_normalized": hashlib.sha256(normalized(ROOT/path)).hexdigest()}
            for path, checksum in bound_sources}

def run(command: list[str], log: Path, timeout: int) -> dict:
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    details = {"command": command, "exit_code": result.returncode, "seconds": round(time.monotonic()-started, 3), "log": str(log)}
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}); see {log}\n{result.stdout[-2500:]}{result.stderr[-2500:]}")
    return details

def executable_contract(output: Path) -> dict:
    tcl = shutil.which("tclsh")
    native_python = Path("/mnt/c/Users/meath/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe")
    def windows_path(path: Path) -> str:
        absolute = str(path.resolve())
        match = re.fullmatch(r"/mnt/([a-z])/(.*)", absolute)
        assert match, "Native Tcl fallback requires a WSL drive-mounted path"
        return match.group(1).upper()+":/"+match.group(2)
    if not tcl and not native_python.is_file():
        raise RuntimeError("tclsh or the verified native Python/Tcl runtime is required")
    cases = [
        ("valid", None, None, None),
        ("changed_i2c_phase", "sys/i2c.v", b"I2C_Freq*2", b"I2C_Freq*3"),
        ("unsafe_bus_rate", "rtl/bt_mcp23009.sv", b"100_000", b"500_000"),
        ("active_user_driver", "Arcade-Battletoads.sv", b"assign USER_OUT = '1;", b"assign USER_OUT = '0;"),
        ("active_sd_driver", "Arcade-Battletoads.sv", b"assign {SD_SCK, SD_MOSI, SD_CS} = 'Z;", b"assign {SD_SCK, SD_MOSI, SD_CS} = '0;"),
    ]
    results = {}
    with tempfile.TemporaryDirectory(prefix="contract-", dir=output) as folder:
        base = Path(folder)
        for name, changed_path, before, after in cases:
            fixture = base/name
            for path in ["rtl/bt_platform_io.sdc", "sys/i2c.v", "sys/sys_top.v", "rtl/bt_mcp23009.sv", "Arcade-Battletoads.sv"]:
                target = fixture/path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT/path).read_bytes())
            if changed_path:
                target = fixture/changed_path
                body = target.read_bytes()
                assert before in body, f"Negative contract fixture did not mutate {changed_path}"
                target.write_bytes(body.replace(before, after, 1))
            command = ([tcl, str(ROOT/"tests/bt_platform_io_contract.tcl"), str(fixture/"rtl/bt_platform_io.sdc")]
                       if tcl else [str(native_python), "-X", "utf8", windows_path(ROOT/"tests/bt_platform_io_tclcheck.py"), windows_path(fixture/"rtl/bt_platform_io.sdc")])
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=15)
            log = output/("contract-"+name+".log")
            log.write_text(result.stdout+result.stderr, encoding="utf-8")
            expected_exit = result.returncode == 0 if name == "valid" else result.returncode != 0
            assert expected_exit, f"Executable SDC contract case failed: {name}; see {log}"
            results[name] = {"exit_code": result.returncode, "expected": "accept" if name == "valid" else "reject", "log": str(log)}
    return {"type": "Tcl syntax/source-contract with modeled collection cardinality, not native STA", "cases": results}

def physical_margins(phase: dict[str, int]) -> dict[str, int]:
    e = ENVELOPE
    clock_fall = e["fpga_to_scl_ns"] + e["board_each_way_ns"] + e["scl_fall_ns"]
    clock_rise = e["fpga_to_scl_ns"] + e["board_each_way_ns"] + e["scl_rise_ns"]
    data_latest = phase["sda_after_fall_ns"] + e["fpga_to_sda_ns"] + e["board_each_way_ns"] + e["sda_rise_ns"]
    return_latest = clock_fall + e["slave_taa_ns"] + e["sda_rise_ns"] + e["board_each_way_ns"] + e["sda_to_capture_ns"]
    result = {
        "scl_low_ns": phase["low_ns"]-clock_fall,
        "scl_high_ns": phase["high_ns"]-clock_rise,
        "master_data_hold_ns": phase["sda_after_fall_ns"]-clock_fall,
        "master_data_setup_ns": phase["low_ns"]-data_latest,
        "start_hold_ns": phase["start_hold_ns"]-(e["fpga_to_sda_ns"]+e["board_each_way_ns"]+e["sda_fall_ns"]),
        "stop_setup_ns": phase["stop_setup_ns"]-clock_rise,
        "bus_free_ns": phase["bus_free_ns"]-(e["fpga_to_sda_ns"]+e["board_each_way_ns"]+e["sda_rise_ns"]),
        "slave_latest_to_capture_ns": return_latest,
        "receiver_setup_margin_ns": phase["capture_ns"]-e["receiver_aperture_ns"]-return_latest,
        "receiver_hold_margin_ns": phase["low_ns"]+phase["high_ns"]-phase["capture_ns"]-e["capture_clock_latency_ns"]-e["receiver_aperture_ns"],
    }
    assert result["scl_low_ns"] >= 4700 and result["scl_high_ns"] >= 4000
    assert result["master_data_hold_ns"] >= 0 and result["master_data_setup_ns"] >= 250
    assert result["start_hold_ns"] >= 4000 and result["stop_setup_ns"] >= 4000
    assert result["bus_free_ns"] >= 4700 and result["receiver_setup_margin_ns"] > 0 and result["receiver_hold_margin_ns"] > 0
    return result

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="build/bt_platform_io")
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    assert output.is_relative_to(ROOT / "build"), "Proof outputs must stay in ignored build/"
    output.mkdir(parents=True, exist_ok=True)
    receipt = {"result": "FAIL", "source_contract": source_contract(), "physical_envelope": ENVELOPE,
               "limitations": ["Board pullups, capacitance and edge rates require physical qualification of the stated envelope.",
                               "All-corner native STA must gate physical I2C routes and capture clock latency separately.",
                               "USER I2S supports the existing 2 ns receiver setup/hold +0.25 ns skew envelope; connector loading requires qualification.",
                               "All accumulator start phases are checked in steady state; uninitialized RTL accumulator power-up is not newly guaranteed."]}
    if sys.platform == "win32":
        raise RuntimeError("Run this qualifier with wsl.exe -d Ubuntu --cd <repo> --exec /usr/bin/python3 tests/verify_bt_platform_io.py")
    verilator = shutil.which("verilator")
    if not verilator:
        raise RuntimeError("Verilator is required in the selected Linux runtime")
    (output/"receipt.json").write_text(json.dumps(receipt, indent=2)+"\n", encoding="utf-8")
    receipt["executable_sdc_contract"] = executable_contract(output)
    relative = str(output.relative_to(ROOT))
    receipt["tool_version"] = subprocess.check_output([verilator, "--version"], text=True).strip()
    command = [verilator, "--binary", "--timing", "--top-module", TOP, "-Wno-fatal", "-j", "2", "--Mdir", relative+"/verilator", *SOURCES]
    receipt["compile"] = run(command, output/"compile.log", 180)
    receipt["simulation"] = run(["./"+relative+"/verilator/V"+TOP], output/"run.log", 180)
    trace = (output/"run.log").read_text(encoding="utf-8")
    assert "PASS transfers=1500 start_phases=500 kinds=3" in trace, "Simulation did not complete its coverage"
    phase_line = re.search(r"^PHASE (.*)$", trace, re.M)
    assert phase_line, "Missing measured phase trace"
    phase = {name:int(value) for name,value in re.findall(r"(\w+)=(\d+)", phase_line.group(1))}
    receipt["measured_rtl_phase"] = phase
    receipt["physical_margin_with_envelope"] = physical_margins(phase)
    receipt["coverage"] = re.search(r"^PASS .*", trace, re.M).group(0)
    receipt["result"] = "PASS_RTL_WITH_EXPLICIT_PHYSICAL_GATES"
    (output/"receipt.json").write_text(json.dumps(receipt, indent=2)+"\n", encoding="utf-8")
    print(receipt["coverage"])
    print("PASS source-bound bus-rate-only override and conservative physical phase arithmetic")
    print("Receipt: "+str(output/"receipt.json"))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
