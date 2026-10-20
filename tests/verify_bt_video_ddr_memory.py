"""Run the memory-only bridge equivalence proof against the frozen old RTL.

Only the oracle's unreachable rotation FIFO is substituted with an empty FIFO;
the old and new Avalon command/skid RTL are simulated without substitution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BIN = Path("D:/vibes/fpga/toolchains/msys64/ucrt64/bin")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iverilog", default=str(DEFAULT_BIN / "iverilog.exe") if os.name == "nt" else "iverilog")
    parser.add_argument("--vvp", default=str(DEFAULT_BIN / "vvp.exe") if os.name == "nt" else "vvp")
    parser.add_argument("--simulator", choices=["auto", "iverilog", "verilator"], default="auto")
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "bt_video_ddr_memory")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    paths = [ROOT / "rtl/bt_video_ddr.sv", ROOT / "tests/fixtures/bt_video_ddr_rotation_oracle.sv", ROOT / "tests/bt_video_ddr_memory_equiv_tb.sv"]
    executable = output / "memory_equiv.vvp"
    # Use the native driver's checked invocation: forward slashes and paths
    # relative to the fixed repository cwd for HDL files and simulation output.
    compiler = Path(args.iverilog).as_posix()
    runtime = Path(args.vvp).as_posix()
    simulation_path = Path(os.path.relpath(executable, ROOT)).as_posix()
    source_paths = [path.relative_to(ROOT).as_posix() for path in paths]
    simulator = args.simulator
    if simulator == "auto":
        simulator = "verilator" if os.name != "nt" and shutil.which("verilator") else "iverilog"
    if simulator == "verilator":
        model_dir = Path(os.path.relpath(output / "verilator", ROOT)).as_posix()
        commands = [["verilator", "--binary", "--timing", "--top-module", "bt_video_ddr_memory_equiv_tb", "-Wno-fatal", "-j", "2", "--Mdir", model_dir, *source_paths], [(output / "verilator" / "Vbt_video_ddr_memory_equiv_tb").as_posix()]]
    else:
        commands = [[compiler, "-g2012", "-s", "bt_video_ddr_memory_equiv_tb", "-o", simulation_path, *source_paths], [runtime, simulation_path]]
    logs = []
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=180)
        logs.append({"command": command, "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        (output / "run.log").write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in logs), encoding="utf-8")
        if result.returncode:
            raise SystemExit(f"FAIL {Path(command[0]).name} exit {result.returncode}: {result.stdout}{result.stderr}; full log: {output / 'run.log'}")
    if "PASS memory-only cycle equivalence:" not in logs[-1]["stdout"]:
        raise SystemExit("FAIL: simulator did not report proof completion")
    receipt = {"status": "PASS", "simulator": simulator, "coverage": logs[-1]["stdout"].strip(), "inputs": [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths], "commands": logs, "limits": "rot_we=0; empty oracle FIFO; directed/random protocol checks plus exhaustive four-cycle control sequences; not formal proof, CDC qualification, fitting, or hardware qualification"}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(logs[-1]["stdout"].strip())
    print(f"Evidence: {output / 'receipt.json'}")


if __name__ == "__main__":
    main()
