#!/usr/bin/env python3
"""Prepare disposable fitted copies and collect approved QuartusFast reports.

This script never launches Quartus. Diagnostic max/min limits deliberately
fail STA to expose pad paths in the approved global reports. They are never
release constraints. Native source/DB provenance and report coverage are
retained; missing coverage or unrecognized report structure fails the gate.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import re
import shutil
from pathlib import Path
from platform_io_topology import (PAIRS as ALL_OUTPUT_PAIRS, diagnostic_inventory,
                                 fresh_corners, keeper_catalog)

ROOT = Path(__file__).resolve().parents[1]
INPUT_NODES = {"ACK", *(f"rdata[{i}]" for i in range(5))}
OUTPUT_NODES = {"I2C_CLOCK", "SCLK", "SCLK~DUPLICATE", "SDO[3]"}
INPUT_FULL = {"mcp23009|i2c|"+name for name in INPUT_NODES}
OUTPUT_PAIRS = ALL_OUTPUT_PAIRS
SOURCE_SUFFIXES = {".qpf", ".qsf", ".qip", ".sdc", ".v", ".sv", ".vh", ".vhd", ".vhdl", ".tcl", ".mif", ".hex", ".bin", ".rom"}
IGNORED = {".git", "build", "output_files"}
PLATFORM_SDC_SHA256 = "18aaeadc8ddf1006c4915818ab501084ab4af6d3f4d8621df643ea279bdd8ce8"

def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def helper_hashes() -> dict[str, str]:
    return {str(path.relative_to(ROOT)): sha(path) for path in
            [Path(__file__).resolve(), ROOT/"scripts/platform_io_topology.py"]}

def catalog(root: Path, database: bool = False) -> dict[str, str]:
    result = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in IGNORED for part in relative.parts) or not path.is_file():
            continue
        in_db = any(part in {"db", "incremental_db"} for part in relative.parts)
        if in_db == database and (database or path.suffix.lower() in SOURCE_SUFFIXES):
            if path.is_symlink():
                raise ValueError(f"Provenance cannot silently follow a symlink: {path}")
            result[relative.as_posix()] = sha(path)
    return result

def physical_db(catalogue: dict[str, str]) -> dict[str, str]:
    return {name: digest for name,digest in catalogue.items()
            if ".sta." not in name.lower() and
            (".fit." in name.lower() or name.lower().endswith((".qdb", ".cdb", ".hdb")))}

def safe_output(output: Path, workspace: Path) -> Path:
    output = output.resolve()
    if not output.is_relative_to(ROOT/"build"):
        raise ValueError("Disposable copies must stay within this repository's ignored build/ directory")
    if output.exists():
        raise ValueError(f"Refusing to overwrite an existing diagnostic workspace: {output}")
    if output.is_relative_to(workspace) or workspace.is_relative_to(output):
        raise ValueError("Original fitted workspace and disposable output must be independent")
    return output

def project_paths(workspace: Path, project: str | None) -> tuple[Path, Path]:
    candidates = [workspace/project] if project else list(workspace.glob("*.qpf"))
    if len(candidates) != 1 or not candidates[0].is_file():
        raise ValueError("Specify the single fitted project .qpf with --project")
    qpf = candidates[0].resolve()
    if not qpf.is_relative_to(workspace) or qpf.suffix.lower() != ".qpf":
        raise ValueError("Project must be a .qpf within the fitted workspace")
    qsf = qpf.with_suffix(".qsf")
    if not qsf.is_file():
        raise ValueError("Matching revision .qsf not found")
    return qpf, qsf

def copy_fitted(source: Path, target: Path, qsf: Path, add_sdc: str) -> dict:
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(*IGNORED))
    local_qsf = target/qsf.relative_to(source)
    original = local_qsf.read_text(encoding="utf-8")
    altered = re.sub(r"(?m)^\s*set_global_assignment\s+-name\s+GENERATE_RBF_FILE\s+.*$",
                     "set_global_assignment -name GENERATE_RBF_FILE OFF", original)
    altered += "\n# Disposable diagnostic only: never assemble this workspace.\n"
    altered += "set_global_assignment -name GENERATE_RBF_FILE OFF\n"
    altered += f"set_global_assignment -name SDC_FILE {add_sdc}\n"
    local_qsf.write_text(altered, encoding="utf-8", newline="\n")
    return {"path": str(target), "qsf": str(local_qsf), "qsf_sha256": sha(local_qsf),
            "only_qsf_setting_changes": ["GENERATE_RBF_FILE OFF", f"append SDC_FILE {add_sdc}"],
            "database": catalog(target, True)}

def stress_text(group: str, targets: set[str] | None = None) -> str:
    explicit_focus = targets is not None
    targets = targets or (INPUT_NODES if group == "input" else OUTPUT_NODES)
    allowed = INPUT_NODES if group == "input" else OUTPUT_NODES
    if not targets or not targets <= allowed:
        raise ValueError(f"Unknown {group} focus nodes: {targets-allowed}")
    lines = ["# DIAGNOSTIC ONLY. Expected STA rejection. Never release/assemble.",
             "# Deliberately tighten only the source-bound MCP pad paths.",
             "if {![info exists bt_io_sda] || ![info exists bt_io_scl_regs] || [llength [info commands bt_platform_validate_scl_names]] != 1} {error {Missing qualified platform IO constraints}}",
             "set bt_diagnostic_scl_names [bt_platform_validate_scl_names $bt_io_scl_raw_names]",
             "puts \"BT_IO_DIAGNOSTIC_SCL_NAMES=[join $bt_diagnostic_scl_names { }]\"",
             f"puts {{BT_IO_DIAGNOSTIC_GROUP={group};TARGETS={' '.join(sorted(targets))}}}"]
    if group == "input":
        names = " ".join("mcp23009|i2c|"+name for name in sorted(targets))
        lines += ["set bt_diagnostic_regs [get_registers {"+names+"}]",
                  f"if {{[get_collection_size $bt_diagnostic_regs] != {len(targets)}}} {{error {{Input diagnostic endpoints changed}}}}",
                  "set_max_delay -1000.0 -from $bt_io_sda -to $bt_diagnostic_regs",
                  "set_min_delay 1000.0 -from $bt_io_sda -to $bt_diagnostic_regs"]
    else:
        lines += ["set bt_diagnostic_targets {"+" ".join("mcp23009|i2c|"+name for name in sorted(targets))+"}",
                  "set bt_diagnostic_found {}",
                  "foreach_in_collection bt_diagnostic_reg $bt_io_scl_regs {",
                  "    set bt_diagnostic_name [string map [list {mcp23009:mcp23009|} {mcp23009|} {i2c:i2c|} {i2c|}] [get_node_info -name $bt_diagnostic_reg]]",
                  "    if {[lsearch -exact $bt_diagnostic_targets $bt_diagnostic_name] >= 0} {",
                  "        set_max_delay -1000.0 -from $bt_diagnostic_reg -to $bt_io_scl",
                  "        set_min_delay 1000.0 -from $bt_diagnostic_reg -to $bt_io_scl",
                  "        lappend bt_diagnostic_found $bt_diagnostic_name",
                  "    }",
                  "}",
                  "if {[lsearch -exact $bt_diagnostic_targets {mcp23009|i2c|SDO[3]}] >= 0} {",
                  "    if {[get_collection_size $bt_io_sda_reg] != 1} {error {SDA diagnostic source changed}}",
                  "    set_max_delay -1000.0 -from $bt_io_sda_reg -to $bt_io_sda",
                  "    set_min_delay 1000.0 -from $bt_io_sda_reg -to $bt_io_sda",
                  "    lappend bt_diagnostic_found {mcp23009|i2c|SDO[3]}",
                  "}",
                  "foreach bt_diagnostic_expected $bt_diagnostic_targets {"]
        if not explicit_focus:
            lines += ["    if {$bt_diagnostic_expected eq {mcp23009|i2c|SCLK~DUPLICATE} && [lsearch -exact $bt_diagnostic_scl_names $bt_diagnostic_expected] < 0} {continue}"]
        lines += ["    if {[lsearch -exact $bt_diagnostic_found $bt_diagnostic_expected] < 0} {error {Requested exact physical output alias absent}}", "}"]
    return "\n".join(lines)+"\n"

def prepare(workspace: Path, project: str | None, output: Path, parser_only: bool) -> Path:
    workspace = workspace.resolve()
    qpf,qsf = project_paths(workspace, project)
    output = safe_output(output, workspace)
    baseline_sources, baseline_db = catalog(workspace), catalog(workspace, True)
    if not parser_only and baseline_sources.get("rtl/bt_platform_io.sdc") != PLATFORM_SDC_SHA256:
        raise ValueError("Physical pad qualification requires the exact reviewed alias/source/phase/budget SDC")
    if not physical_db(baseline_db) or not any(".fit." in name.lower() for name in baseline_db):
        raise ValueError("A completed native fitted database is required")
    output.mkdir(parents=True)
    manifest = {"type": "PLATFORM_IO_DIAGNOSTIC_PROVENANCE", "schema": "bt-platform-pad-proof-v2", "helper_sha256": helper_hashes(), "parser_only": parser_only,
                "compiled_source_mismatch": parser_only,
                "purpose": "Parser/endpoint check only: prior 500kHz fitted DB with100kHz source guards" if parser_only else "Physical route qualification of caller-provided exact final fitted image",
                "original_workspace": str(workspace), "original_project": str(qpf),
                "original_sources": baseline_sources, "original_database": baseline_db,
                "original_physical_database": physical_db(baseline_db), "copies": {}}
    groups = ["parser"] if parser_only else ["input", "output"]
    for group in groups:
        target = output/group
        added_sdc = "rtl/bt_platform_io.sdc" if parser_only else "bt_io_diagnostic_stress.sdc"
        info = copy_fitted(workspace, target, qsf, added_sdc)
        if info["database"] != baseline_db:
            raise ValueError("Fitted DB copy is not byte-identical")
        if parser_only:
            for relative in ["rtl/bt_platform_io.sdc", "rtl/bt_mcp23009.sv"]:
                destination = target/relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT/relative, destination)
            info["source_overlay"] = {relative: sha(target/relative) for relative in ["rtl/bt_platform_io.sdc", "rtl/bt_mcp23009.sv"]}
        else:
            (target/added_sdc).write_text(stress_text(group), encoding="utf-8", newline="\n")
            info["stress_history"] = [{"targets": sorted(INPUT_NODES if group == "input" else OUTPUT_NODES), "sha256": sha(target/added_sdc)}]
        info["sources_after_preparation"] = catalog(target)
        info["project"] = str(target/qpf.relative_to(workspace))
        manifest["copies"][group] = info
        (target/"DIAGNOSTIC_ONLY_NO_RBF.json").write_text(json.dumps({"parser_only": parser_only, "compiled_source_mismatch": parser_only, "group": group, "never_release": True}, indent=2)+"\n", encoding="utf-8")
    if catalog(workspace) != baseline_sources or catalog(workspace, True) != baseline_db:
        raise ValueError("Original fitted inputs changed while copying; discard these diagnostics")
    path = output/"provenance.json"
    path.write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    return path

def focus(manifest_path: Path, group: str, targets: set[str]) -> None:
    if not manifest_path.resolve().is_relative_to(ROOT/"build"):
        raise ValueError("Diagnostic provenance must stay within ignored build/")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("helper_sha256") != helper_hashes(): raise ValueError("Prepared diagnostic helper bytes changed")
    if manifest["parser_only"]: raise ValueError("Parser-only copies cannot become physical sign-off copies")
    info = manifest["copies"][group]
    target = Path(info["path"]).resolve()
    if not target.is_relative_to(ROOT/"build"): raise ValueError("Diagnostic path escaped ignored build/")
    path = target/"bt_io_diagnostic_stress.sdc"
    path.write_text(stress_text(group,targets), encoding="utf-8", newline="\n")
    info["stress_history"].append({"targets": sorted(targets), "sha256": sha(path)})
    info["sources_after_preparation"][path.name] = sha(path)
    manifest_path.write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")

def canonical(name: str) -> str:
    return "|".join(part.split(":")[-1] for part in name.split("|"))

def numeric_row(section: str, element: str, optional: bool = False) -> tuple[float,float]:
    matches = []
    for line in section.splitlines():
        if not line.lstrip().startswith(";"): continue
        fields = [value.strip() for value in line.strip().strip(";").split(";")]
        if len(fields) >= 7 and fields[-1] == element:
            values = (float(fields[0]), float(fields[1]))
            if not all(math.isfinite(value) for value in values):
                raise ValueError(f"Non-finite physical timing row {element!r}")
            matches.append(values)
    if not matches and optional: return (0.0,0.0)
    if len(matches) != 1: raise ValueError(f"Expected one timing row {element!r}, found {len(matches)}")
    return matches[0]

def parse_paths(report: Path, check: str) -> list[dict]:
    body = report.read_text(encoding="utf-8", errors="strict")
    if "-detail full_path" not in body or f"-{check}" not in body:
        raise ValueError(f"Unrecognized report provenance/options: {report}")
    paths = []
    blocks = re.split(r"(?m)^Path #(\d+): (?:Setup|Hold) slack is ", body)
    for index in range(1, len(blocks), 2):
        block = blocks[index+1]
        if "; Data Arrival Path" not in block or "; Data Required Path" not in block:
            raise ValueError(f"Missing full path details: {report}, path {blocks[index]}")
        prefix, arrival = block.split("; Data Arrival Path", 1)
        arrival, required = arrival.split("; Data Required Path", 1)
        properties = {}
        for line in prefix.splitlines():
            if not line.lstrip().startswith(";"): continue
            fields = [value.strip() for value in line.strip().strip(";").split(";")]
            if len(fields) == 2 and fields[0] in {"From Node", "To Node", "Launch Clock", "Latch Clock", "Slack", "Data Arrival Time", "Data Required Time", "Setup Relationship", "Hold Relationship"}:
                properties.setdefault(fields[0], fields[1])
        for key in ["From Node", "To Node", "Launch Clock", "Latch Clock", "Slack"]:
            if key not in properties: raise ValueError(f"Missing {key}: {report}")
        from_node,to_node = canonical(properties["From Node"]),canonical(properties["To Node"])
        data_total,data_increment = numeric_row(arrival, "data path")
        launch_total,launch_increment = numeric_row(arrival, "clock path", optional=(from_node,to_node) not in OUTPUT_PAIRS)
        capture_total,capture_increment = numeric_row(required, "clock path", optional=not (from_node == "IO_SDA" and to_node in INPUT_FULL))
        slack = float(properties["Slack"].split()[0])
        relationship_text = properties.get("Setup Relationship" if check == "setup" else "Hold Relationship")
        relationship = None if relationship_text in {None,"n/a","(none)"} else float(relationship_text)
        if not math.isfinite(slack) or (relationship is not None and not math.isfinite(relationship)):
            raise ValueError(f"Non-finite timing property: {report}")
        paths.append({"path": int(blocks[index]), "from": from_node, "to": to_node,
                      "raw_from": properties["From Node"], "raw_to": properties["To Node"],
                      "launch_clock": properties["Launch Clock"], "latch_clock": properties["Latch Clock"],
                      "slack": slack, "data_delay_ns": data_increment,
                      "launch_clock_latency_ns": launch_increment, "capture_clock_latency_ns": capture_increment,
                      "clock_plus_data_delay_ns": launch_increment+data_increment,
                      "relationship_ns": relationship,
                      "report": str(report)})
    if not paths: raise ValueError(f"No full paths parsed: {report}")
    return paths

def collect(manifest_path: Path, input_runs: list[Path], output_runs: list[Path], receipt_path: Path) -> dict:
    if receipt_path.exists():
        raise ValueError("Refusing to overwrite an existing physical pad receipt")
    if not receipt_path.resolve().is_relative_to(ROOT/"build"):
        raise ValueError("Diagnostic gate receipts must stay within ignored build/")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures = []
    receipt = {"result": "FAIL", "diagnostic_rejections_expected": True, "release_timing_accepted": False,
               "helper_sha256": helper_hashes(), "provenance": str(manifest_path.resolve()), "provenance_sha256": sha(manifest_path), "corners": {}, "failures": failures}
    if manifest.get("helper_sha256") != helper_hashes():
        failures.append("Prepared diagnostic helper bytes changed")
    if manifest["parser_only"] or manifest["compiled_source_mismatch"]:
        failures.append("Parser-only compiled/source mismatch cannot qualify physical pads")
    original = Path(manifest["original_workspace"])
    if manifest["original_sources"].get("rtl/bt_platform_io.sdc") != PLATFORM_SDC_SHA256:
        failures.append("Original fitted platform SDC differs from reviewed exact source/phase/budget contract")
    if catalog(original) != manifest["original_sources"] or catalog(original,True) != manifest["original_database"]:
        failures.append("Original fitted source/database changed after preparation")
    receipt["diagnosed_database_changes"] = {}
    for group in ["input", "output"]:
        if group not in manifest["copies"]: continue
        info = manifest["copies"][group]
        target = Path(info["path"])
        if catalog(target) != info["sources_after_preparation"]:
            failures.append(f"{group}: source inputs changed outside recorded preparation/focus")
        current_db = catalog(target,True)
        if physical_db(current_db) != manifest["original_physical_database"]:
            failures.append(f"{group}: fitted physical database changed during diagnostic")
        receipt["diagnosed_database_changes"][group] = {name: digest for name,digest in current_db.items() if info["database"].get(name) != digest}
    conditions = {}
    routed_outputs = None
    actual_aliases = None
    receipt["native_topology"] = {}
    for group,runs in [("input",input_runs), ("output",output_runs)]:
        for run in runs:
            try:
                topology = keeper_catalog(run, Path(manifest["copies"][group]["project"]))
                inventory = diagnostic_inventory(run, topology)
                native_log = (run/"all-corners.log").read_text(encoding="utf-8")
                marker = re.findall(r"(?m)^.*BT_IO_DIAGNOSTIC_GROUP=([^;\r\n]+);TARGETS=([^\r\n]*)$", native_log)
                if len(set(marker)) != 1 or marker[0][0] != group:
                    raise ValueError("Missing or inconsistent executed diagnostic stress group/targets")
                selected_targets = set(marker[0][1].strip().split())
                permitted_stress_hashes = {hashlib.sha256(stress_text(group, selected_targets).encode()).hexdigest()}
                if selected_targets == (INPUT_NODES if group == "input" else OUTPUT_NODES):
                    permitted_stress_hashes.add(hashlib.sha256(stress_text(group).encode()).hexdigest())
                if not any(row["sha256"] in permitted_stress_hashes and set(row["targets"]) == selected_targets for row in manifest["copies"][group]["stress_history"]):
                    raise ValueError("Executed diagnostic scope lacks an exact generated stress/source history edge")
                counts = fresh_corners(run)
                pairs = {tuple(pair) for pair in topology["output_pairs"]}
                aliases = tuple(inventory["present_scl_names"])
                if routed_outputs is not None and (routed_outputs != pairs or actual_aliases != aliases):
                    raise ValueError("Exact fitted pad topology/register aliases changed across diagnostic runs")
                routed_outputs, actual_aliases = pairs, aliases
                receipt["native_topology"][str(run)] = {"catalog": topology, "inventory": inventory, "fresh_corners": counts}
            except (ValueError, OSError, KeyError) as failure:
                failures.append(f"{run}: {failure}")
                continue
            corners = sorted((run/"all-corners").glob("corner_*"))
            if len(corners) != 8: failures.append(f"{run}: expected eight native corners, found {len(corners)}")
            for corner in corners:
                condition_file = corner/"condition.txt"
                if not condition_file.is_file(): failures.append(f"Missing condition: {corner}"); continue
                condition = condition_file.read_text(encoding="utf-8").strip()
                if corner.name in conditions and conditions[corner.name] != condition:
                    failures.append(f"Corner condition mismatch: {corner.name}")
                conditions[corner.name] = condition
                record = receipt["corners"].setdefault(corner.name,{"condition": condition, "input":{}, "output":{}})
                for check in ["setup", "hold"]:
                    report = corner/(check+".txt")
                    try: paths = parse_paths(report,check)
                    except (ValueError,OSError) as failure:
                        failures.append(str(failure)); continue
                    saved = record[group].setdefault(check,{"paths":[],"reports":{}})
                    saved["reports"][str(report)] = sha(report)
                    for path in paths:
                        valid = (path["from"] == "IO_SDA" and path["to"] in INPUT_FULL) if group == "input" else ((path["from"],path["to"]) in routed_outputs)
                        if not valid: continue
                        if path["slack"] >= -500:
                            failures.append(f"Diagnostic stress not observable: {report} path {path['path']}")
                        if path["data_delay_ns"] < 0 or path["launch_clock_latency_ns"] < 0 or path["capture_clock_latency_ns"] < 0:
                            failures.append(f"Negative physical timing metric: {report} path {path['path']}")
                        if group == "input":
                            if path["data_delay_ns"] > 100 or path["capture_clock_latency_ns"] > 50:
                                failures.append(f"Input physical/clock budget exceeded: {report} path {path['path']}")
                            if path["latch_clock"] != "FPGA_CLK2_50":
                                failures.append(f"Input capture clock changed: {report}")
                        else:
                            limit = 20 if path["to"] == "IO_SCL" else 50
                            if path["clock_plus_data_delay_ns"] > limit or path["clock_plus_data_delay_ns"] < 1:
                                failures.append(f"Output clock-plus-data budget exceeded: {report} path {path['path']}")
                            if path["launch_clock"] != "FPGA_CLK2_50":
                                failures.append(f"Output launch clock changed: {report}")
                        saved["paths"].append(path)
    if len(receipt["corners"]) != 8 or len(set(conditions.values())) != 8:
        failures.append("Eight distinct matched native corner conditions are required")
    for corner,record in receipt["corners"].items():
        for group in ["input","output"]:
            for check in ["setup","hold"]:
                paths = record[group].get(check,{}).get("paths",[])
                found = {path["to"] for path in paths} if group == "input" else {(path["from"],path["to"]) for path in paths}
                expected = INPUT_FULL if group == "input" else (routed_outputs or OUTPUT_PAIRS)
                missing = expected-found
                if missing: failures.append(f"{corner} {group} {check}: missing exact source/endpoint coverage {sorted(missing)}")
    if not failures: receipt["result"] = "PASS_NATIVE_PHYSICAL_PAD_BUDGETS"
    receipt["limitations"] = ["Physical board edge-rate/pull-up/loading envelope is a separate hardware gate.",
                              "Diagnostic STA intentionally fails; release timing and zero unconstrained paths require separate exact-image approval.",
                              "Each source/capture endpoint must appear in setup AND hold at all eight corners; focused reruns may be aggregated."]
    receipt_path.parent.mkdir(parents=True,exist_ok=True)
    receipt_path.write_text(json.dumps(receipt,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    return receipt

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode",required=True)
    for mode in ["prepare","prepare-parser"]:
        command = commands.add_parser(mode)
        command.add_argument("--workspace", type=Path, required=True)
        command.add_argument("--project")
        command.add_argument("--output",type=Path,required=True)
    command = commands.add_parser("focus")
    command.add_argument("--manifest",type=Path,required=True)
    command.add_argument("--group",choices=["input","output"],required=True)
    command.add_argument("--targets",nargs="+",required=True)
    command = commands.add_parser("collect")
    command.add_argument("--manifest",type=Path,required=True)
    command.add_argument("--input-run",type=Path,action="append",required=True)
    command.add_argument("--output-run",type=Path,action="append",required=True)
    command.add_argument("--receipt",type=Path,required=True)
    args = parser.parse_args()
    if args.mode.startswith("prepare"):
        path = prepare(args.workspace,args.project,args.output,args.mode=="prepare-parser")
        print("Provenance: "+str(path))
        manifest = json.loads(path.read_text(encoding="utf-8"))
        for group,info in manifest["copies"].items(): print(group+" project: "+info["project"])
        print("No Quartus process launched. Use the approved QuartusFast diagnose frontend.")
        return 0
    if args.mode == "focus":
        focus(args.manifest,args.group,set(args.targets))
        print("Updated diagnostic-only stress focus; rerun approved diagnose and aggregate the report handles.")
        return 0
    receipt = collect(args.manifest,args.input_run,args.output_run,args.receipt)
    print(receipt["result"]+": "+str(args.receipt))
    for failure in receipt["failures"][:12]: print(failure)
    return 0 if receipt["result"].startswith("PASS_") else 1

if __name__ == "__main__":
    raise SystemExit(main())
