#!/usr/bin/env python3
"""Reproduce the frozen actual old/current pixel-process compiler evidence."""
import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "tests/graphics/prepare_bt_pixel_parallel.py"
QUALIFIER = ROOT / "tests/graphics/qualify_bt_pixel_parallel.py"
EDGE_PIN = "cef1aee684116f7dcb2f0d14072f37c12b7a530d49ba2f15426c4b75a00564f0"
HELPER_PIN = "4a43226a9ae2255587b3856c6605beb260ccca9b1dfae0292feef3fd28b00452"
COUNTS = {"checks": 234241, "categories": 4608, "values": 98304, "unknowns": 131072, "resets": 128}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resolved(name):
    path = Path(name)
    return path if path.is_absolute() else ROOT / path


def verify_proof(edge_directory, receipt_path):
    edge_path = Path(edge_directory) / "manifest.json"
    receipt_path = Path(receipt_path)
    if sha(edge_path.read_bytes()) != EDGE_PIN or sha(HELPER.read_bytes()) != HELPER_PIN:
        raise ValueError("Exact frozen pixel edge/helper pins required")
    edge = json.loads(edge_path.read_bytes())
    receipt = json.loads(receipt_path.read_bytes())
    if receipt["schema"] != "bt-pixel-parallel-modelsim-proof-v1" or receipt["status"] != "PASS_SCOPED_PIXEL_PROCESS":
        raise ValueError("Exact executed pixel receipt schema/status required")
    if receipt["edge_manifest_sha256"] != EDGE_PIN or resolved(receipt["edge_manifest"]).resolve() != edge_path.resolve():
        raise ValueError("Exact executed pixel edge identity required")
    if sha(QUALIFIER.read_bytes()) != receipt["qualifier_sha256"]:
        raise ValueError("Executed pixel qualifier bytes changed")
    if receipt["counts"] != COUNTS or receipt["assertions_removed"] != 0 or receipt["excluded_cases"] != 0 or receipt["timing"] != "UNRUN":
        raise ValueError("Complete scoped pixel coverage/no-exclusion contract changed")
    helper = load(HELPER, "pixel_verify_edge")
    qualifier = load(QUALIFIER, "pixel_verify_qualifier")
    candidate = resolved(edge["candidate"]).read_bytes()
    proof = helper.verify_source(candidate, edge["edits"])
    if receipt["source_proof"] != proof:
        raise ValueError("Complete regenerated pixel source proof changed")
    parent = helper.reverse(candidate, edge["edits"])
    generated = {"pixel_old.sv": b"module bt_pixel_old" + qualifier.HEADER + helper.pixel_fragment(parent) + b"assign RESULT=PIX_OUT; endmodule\n",
                 "pixel_new.sv": b"module bt_pixel_new" + qualifier.HEADER + helper.pixel_fragment(candidate) + b"assign RESULT=PIX_OUT; endmodule\n",
                 "pixel_tb.sv": qualifier.BENCH.encode()}
    if receipt["compiled_inputs"] != {name: sha(data) for name, data in generated.items()}:
        raise ValueError("Regenerated pixel compiler-input hashes changed")
    artifacts = {}
    for name, data in generated.items():
        path = receipt_path.parent / name
        if path.read_bytes() != data:
            raise ValueError("Actual retained pixel compiler input changed: " + name)
        artifacts[str(path)] = sha(data)
    runs = receipt["runs"]
    if len(runs) != 3:
        raise ValueError("All three actual compiler/simulator executions required")
    work = receipt_path.parent / "work"
    commands = [[str(qualifier.SIM / "vlib.exe"), str(work)],
                [str(qualifier.SIM / "vlog.exe"), "-sv", "-work", str(work), *[str(receipt_path.parent / name) for name in generated]],
                [str(qualifier.SIM / "vsim.exe"), "-c", "-assertdebug", "-onfinish", "stop", "-lib", str(work), "bt_pixel_parallel_tb", "-do", "run -all; quit -code 0"]]
    # The original qualifier records its caller's relative output arguments;
    # resolve each path argument while preserving every nonpath flag/token.
    for index, (record, expected) in enumerate(zip(runs, commands)):
        actual = record["command"]
        if len(actual) != len(expected):
            raise ValueError("Executed pixel command shape changed")
        path_positions = {0, 1} if index == 0 else {0, 3, 4, 5, 6} if index == 1 else {0, 6}
        for position, (value, wanted) in enumerate(zip(actual, expected)):
            if position in path_positions:
                if resolved(value).resolve() != Path(wanted).resolve():
                    raise ValueError("Executed pixel command input path changed")
            elif value != wanted:
                raise ValueError("Executed pixel command flags changed")
        log = resolved(record["log"])
        if log.resolve() != (receipt_path.parent / f"step-{index}.log").resolve():
            raise ValueError("Exact retained pixel log path required")
        data = log.read_bytes()
        if sha(data) != record["log_sha256"] or record["exit_code"] != 0:
            raise ValueError("Actual pixel log/exit evidence changed")
        if re.search(rb"(?mi)^#?\s*\*\*\s*(?:Error|Fatal):", data):
            raise ValueError("Actual pixel compiler/runtime error present")
        artifacts[str(log)] = sha(data)
    transcript = resolved(runs[-1]["log"]).read_bytes()
    markers = re.findall(rb"PIXEL_PARALLEL_PASS checks=(\d+) categories=(\d+) values=(\d+) unknowns=(\d+) resets=(\d+)", transcript)
    if len(markers) != 1 or dict(zip(COUNTS, map(int, markers[0]))) != COUNTS:
        raise ValueError("Actual complete pixel simulation marker changed")
    return {"status": "PASS_SCOPED_PIXEL_REPRODUCTION", "receipt_sha256": sha(receipt_path.read_bytes()),
            "source_proof": proof, "files": artifacts, "counts": COUNTS,
            "compiled_full_core": False, "timing_accepted": False, "hardware": "UNTESTED"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--edge", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    report = verify_proof(args.edge, args.receipt)
    print(json.dumps({key: report[key] for key in ("status", "receipt_sha256", "counts", "timing_accepted")}))


if __name__ == "__main__":
    main()
