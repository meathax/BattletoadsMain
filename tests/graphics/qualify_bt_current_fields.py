"""Requalify the two field helpers against retained immutable Git functions.

This proves helper behavior only. Controller, return-stage, RAM, and phase
ownership are separate qualifications. It does not reconstruct a missing
historical full-file oracle or retag a historical receipt.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid


ROOT = Path(__file__).resolve().parents[2]
REFERENCES = (
    ("e5dbd1d", "rtl/TMS34020/TMS34020_MC.sv", "FastDataWriteBE",
     "6c226b95c281e7dfa25c4e6e6989335fee5b2543d7731cbc9a5ce1a8c1928dff"),
    ("7b80684", "rtl/TMS34020/TMS34020_pkg.sv", "Ext",
     "a921304988aa1521b9929407f7a3c9ef53dbe429a992e2b77ab56a585205f138"),
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def extract(text, name):
    matches = list(re.finditer(
        r"^[ \t]*function[^\n]*\b" + re.escape(name) +
        r"\s*\(.*?\bendfunction", text, re.M | re.S))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one actual function: {name}")
    return matches[0].group(0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    source_root = (args.source_root or root).resolve()
    run_id = "io-cpu_fields-current-" + uuid.uuid4().hex
    target = Path("R:/Verilator/BT") / run_id
    target.mkdir(parents=True)
    retained = root / "tests/graphics/evidence/io-phase" / run_id
    retained.mkdir(parents=True)
    declarations, sources, references = [], {}, []
    for revision, name, function, expected_hash in REFERENCES:
        commit = subprocess.check_output(
            ["git", "rev-parse", revision + "^{commit}"], cwd=root).decode().strip()
        original = subprocess.check_output(["git", "show", commit + ":" + name], cwd=root)
        if sha(original) != expected_hash:
            raise RuntimeError("Immutable reference hash differs: " + name)
        current = source_root / name
        if not current.is_file():
            raise RuntimeError("Current compiled input missing: " + str(current))
        data = current.read_bytes()
        sources[name] = sha(data)
        ref_body = extract(original.decode("utf-8"), function)
        current_body = extract(data.decode("utf-8").replace("\r\n", "\n"), function)
        for prefix, body in (("candidate", current_body), ("reference", ref_body)):
            declarations.append(re.sub(r"\b" + function + r"\b", prefix + "_" + function, body))
        references.append({"commit": commit, "path": name, "blob_sha256": sha(original),
                           "function": function, "reference_function_sha256": sha(ref_body.encode()),
                           "current_function_sha256": sha(current_body.encode())})
    bench = root / "tests/cpu_field_timing_tb.sv"
    shutil.copyfile(bench, target / bench.name)
    sources["tests/cpu_field_timing_tb.sv"] = sha(bench.read_bytes())
    sources["tests/graphics/qualify_bt_current_fields.py"] = sha(Path(__file__).read_bytes())
    include = target / "field_functions.svh"
    include.write_text("\n\n".join(declarations), encoding="utf-8", newline="\n")
    command = ["D:/vibes/fpga/bin/verilator.exe", "--binary", "--assert", "--timing", "-j", "4",
               "--threads", "1", "--top-module", "cpu_field_timing_tb", "--Mdir", str(target / "obj"),
               "-Wno-fatal", "-MAKEFLAGS",
               "CXX=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe LINK=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe",
               "-CFLAGS", "-DVL_TIME_CONTEXT -std=c++17", "-LDFLAGS", "-static-libstdc++ -static-libgcc",
               str(target / bench.name)]
    environment = dict(os.environ, MISTER_DIFF_HEADLESS="1", VERILATOR_PROJECT="BT",
                       VERILATOR_WORKSPACE=str(target), VERILATOR_RAM_WORKSPACE=str(target))
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with (target / "build.log").open("w") as log:
        result = subprocess.run(command, cwd=target, env=environment, stdout=log,
                                stderr=subprocess.STDOUT, creationflags=flags)
    build_exit = result.returncode
    if not build_exit:
        with (target / "run.log").open("w") as log:
            result = subprocess.run([str(target / "obj/Vcpu_field_timing_tb.exe")], cwd=target,
                                    env=environment, stdout=log, stderr=subprocess.STDOUT,
                                    creationflags=flags)
    run_log = target / "run.log"
    coverage = {}
    if run_log.exists():
        match = re.search(r"PASS CPU field timing helpers: byte_enables=(\d+) extensions=(\d+)",
                          run_log.read_text(errors="replace"))
        if match:
            coverage = {"byte_enables": int(match[1]), "extensions": int(match[2])}
    accepted = not result.returncode and coverage == {"byte_enables": 2048, "extensions": 33280}
    receipt = {"scope": "Actual current field helpers versus immutable e5dbd1d byte-enable and 7b80684 vendor extension functions; helper behavior only",
               "snapshot": str(target), "source_root": str(source_root), "sources": sources,
               "references": references, "generated_include_sha256": sha(include.read_bytes()),
               "command": command, "build_exit_code": build_exit, "run_exit_code": result.returncode,
               "coverage": coverage, "exit_code": int(not accepted)}
    (retained / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    for name in ("build.log", "run.log", "field_functions.svh", bench.name):
        if (target / name).exists():
            shutil.copyfile(target / name, retained / name)
    print(json.dumps({"receipt": str(retained / "receipt.json"), "coverage": coverage,
                      "exit_code": receipt["exit_code"]}, indent=2))
    if not accepted:
        print((run_log if run_log.exists() else target / "build.log").read_text(errors="replace")[-2200:])
    return receipt["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
