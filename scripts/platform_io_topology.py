"""Strict parser for the approved QuartusFast keeper-catalog-v1 observer.

This is topology evidence only. It cannot accept timing or a compiled image.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from pathlib import Path

OBSERVER_SHA256 = "f452e01ad660e6391bccd97ac6dbbc11677a500fc8a0c172d8dede9b7c51473d"
SCL_BASE = {"mcp23009|i2c|I2C_CLOCK", "mcp23009|i2c|SCLK"}
SCL_OPTIONAL = {"mcp23009|i2c|SCLK~DUPLICATE"}
SDA_SOURCE = "mcp23009|i2c|SDO[3]"
INPUTS = {"mcp23009|i2c|ACK", *(f"mcp23009|i2c|rdata[{i}]" for i in range(5))}
PAIRS = {(name, "IO_SCL") for name in SCL_BASE | SCL_OPTIONAL} | {(SDA_SOURCE, "IO_SDA")}
UCP_PROPERTIES = {"Illegal Clocks", "Unconstrained Clocks", "Unconstrained Input Ports",
                  "Unconstrained Input Port Paths", "Unconstrained Output Ports",
                  "Unconstrained Output Port Paths"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(name: str) -> str:
    return name.replace("mcp23009:mcp23009|", "mcp23009|").replace("i2c:i2c|", "i2c|")


def validate_scl_names(names: list[str]) -> set[str]:
    found = [canonical(name) for name in names]
    if len(set(found)) != len(found) or not SCL_BASE <= set(found) or not set(found) <= SCL_BASE | SCL_OPTIONAL:
        raise ValueError(f"Missing, foreign or repeated physical SCL alias: {names}")
    return set(found)


def unconstrained(report: Path) -> dict[str, dict[str, int]]:
    values = {}
    for line in report.read_text(encoding="utf-8").splitlines():
        fields = [field.strip() for field in line.strip().strip(";").split(";")]
        if len(fields) == 3 and fields[0] in UCP_PROPERTIES:
            if fields[0] in values or not all(re.fullmatch(r"\d+", value) for value in fields[1:]):
                raise ValueError(f"Malformed or repeated unconstrained summary: {report}")
            values[fields[0]] = {"setup": int(fields[1]), "hold": int(fields[2])}
    if set(values) != UCP_PROPERTIES or any(any(row.values()) for row in values.values()):
        raise ValueError(f"Missing or nonzero native unconstrained summary: {report}")
    return values


def fresh_corners(run: Path) -> dict[str, dict]:
    corners = sorted((run / "all-corners").glob("corner_*"))
    if [corner.name for corner in corners] != [f"corner_{i}" for i in range(1, 9)]:
        raise ValueError(f"Exactly corner_1 through corner_8 required: {run}")
    result = {}
    for corner in corners:
        condition = (corner / "condition.txt").read_text(encoding="utf-8").strip()
        if not condition:
            raise ValueError(f"Empty native corner condition: {corner}")
        report = corner / "unconstrained.txt"
        result[corner.name] = {"condition": condition, "unconstrained": unconstrained(report),
                               "condition_sha256": sha(corner / "condition.txt"),
                               "unconstrained_sha256": sha(report)}
    if len({row["condition"] for row in result.values()}) != 8:
        raise ValueError(f"Eight distinct native corner conditions required: {run}")
    return result


def parse_route_report(report: Path, port: str, direction: str, count: int) -> list[dict]:
    body = report.read_text(encoding="utf-8")
    expected_command = f"-{direction} [get_ports {{{port}}}]"
    if "report_path -show_routing" not in body or expected_command not in body or "-npaths 25" not in body:
        raise ValueError(f"Wrong native topology command: {report}")
    found_count = re.findall(r"Report Path: Found (\d+) paths\.", body)
    if found_count != [str(count)] or not 0 <= count < 25:
        raise ValueError(f"Truncated/mismatched native topology count: {report}")
    matches = list(re.finditer(r"(?m)^Path #(\d+): Delay is ([\d.eE+-]+)\s*$", body))
    if [int(match[1]) for match in matches] != list(range(1, count + 1)):
        raise ValueError(f"Missing/repeated topology path: {report}")
    result = []
    for index, match in enumerate(matches):
        block = body[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(body)]
        properties = {}
        for line in block.splitlines():
            fields = [field.strip() for field in line.strip().strip(";").split(";")]
            if len(fields) == 2 and fields[0] in {"From Node", "To Node", "Delay"}:
                if fields[0] in properties:
                    raise ValueError(f"Repeated topology property: {report}")
                properties[fields[0]] = fields[1]
        if set(properties) != {"From Node", "To Node", "Delay"}:
            raise ValueError(f"Missing topology properties: {report}")
        delay = float(match[2])
        if not math.isfinite(delay) or delay < 0 or abs(delay - float(properties["Delay"])) > 0.001:
            raise ValueError(f"Invalid topology delay: {report}")
        endpoint = properties["From Node" if direction == "from" else "To Node"]
        if endpoint != port:
            raise ValueError(f"Topology port endpoint changed: {report}")
        if "; Data Arrival Path" not in block or "; Statistics" not in block:
            raise ValueError(f"Missing complete native route detail: {report}")
        result.append({"path": int(match[1]), "from": canonical(properties["From Node"]),
                       "to": canonical(properties["To Node"]), "raw_from": properties["From Node"],
                       "raw_to": properties["To Node"], "first_corner_route_delay_ns": delay})
    return result


def keeper_catalog(run: Path, expected_project: Path | None = None) -> dict:
    directory = run / "all-corners" / "keeper-catalog"
    binding_path = run / "keeper-catalog-binding.json"
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    if binding.get("observer_sha256") != OBSERVER_SHA256:
        raise ValueError("Native keeper observer changed; review its bounded complete topology contract")
    project = Path(binding["project"]).resolve()
    if expected_project is not None and project != expected_project.resolve():
        raise ValueError("Keeper catalog belongs to a different diagnostic project")
    if Path(binding["workspace"]).resolve() != project.parent or binding["qpf_sha256"] != sha(project) or binding["qsf_sha256"] != sha(project.with_suffix(".qsf")):
        raise ValueError("Native keeper QPF/QSF binding changed")
    log = (run / "all-corners.log").read_text(encoding="utf-8")
    if "keeper-catalog-v1" not in log or "quartus_sta -t" not in log or "all-corners.tcl" not in log:
        raise ValueError("Missing approved native keeper observer invocation")
    scope_path = directory / "scope.txt"
    scope = dict(re.findall(r"([a-z_]+)=([^;\s]+)", scope_path.read_text(encoding="utf-8")))
    if scope.get("catalog_complete") != "1" or scope.get("paths_per_direction_cap") != "25" or scope.get("corner") != "first":
        raise ValueError("Incomplete or unreviewed native topology scope")
    with (directory / "ports.tsv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream, delimiter="\t"))
    if rows[0] != ["id", "port", "direction", "native_node_type"]:
        raise ValueError("Unrecognized native port catalog")
    ports = {}
    for row in rows[1:]:
        if len(row) != 4 or row[0] in ports or row[2] not in {"input", "output", "inout"} or row[3] != "port":
            raise ValueError("Malformed or repeated native port")
        ports[row[0]] = {"port": row[1], "direction": row[2]}
    if len(ports) != int(scope["actual_native_ports"]) or len({row["port"] for row in ports.values()}) != len(ports):
        raise ValueError("Incomplete/repeated native ports")
    with (directory / "coverage.tsv").open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if reader.fieldnames != ["id", "port", "direction", "collection_size", "paths", "delay", "status", "report"]:
            raise ValueError("Unrecognized native topology coverage table")
        coverage = list(reader)
    expected = {(number, direction) for number, row in ports.items()
                for direction in (["from", "to"] if row["direction"] == "inout" else ["from" if row["direction"] == "input" else "to"])}
    keys = [(row["id"], row["direction"]) for row in coverage]
    if len(set(keys)) != len(keys) or set(keys) != expected or len(keys) != int(scope["requested_directions"]):
        raise ValueError("Incomplete/repeated native port-direction coverage")
    selected = {}
    report_hashes = {str(path): sha(path) for path in [binding_path, scope_path, directory / "ports.tsv", directory / "coverage.tsv"]}
    for row in coverage:
        if ports[row["id"]]["port"] != row["port"] or row["collection_size"] != "1":
            raise ValueError("Native port collection identity/count changed")
        if (row["port"], row["direction"]) not in {("IO_SCL", "to"), ("IO_SDA", "to"), ("IO_SDA", "from")}:
            continue
        count = int(row["paths"])
        if not 0 < count < 25 or row["status"] != "paths" or row["report"] != f"{row['id']}-{row['direction']}.rpt":
            raise ValueError("Missing or capped platform native topology")
        report = directory / row["report"]
        paths = parse_route_report(report, row["port"], row["direction"], count)
        if abs(float(row["delay"]) - max(path["first_corner_route_delay_ns"] for path in paths)) > 0.001:
            raise ValueError("Native coverage delay/count disagrees with route report")
        selected[(row["port"], row["direction"])] = paths
        report_hashes[str(report)] = sha(report)
    if set(selected) != {("IO_SCL", "to"), ("IO_SDA", "to"), ("IO_SDA", "from")}:
        raise ValueError("Platform topology directions omitted")
    output_paths = selected[("IO_SCL", "to")] + selected[("IO_SDA", "to")]
    output_pairs = {(row["from"], row["to"]) for row in output_paths}
    input_pairs = {(row["from"], row["to"]) for row in selected[("IO_SDA", "from")]}
    if not output_pairs <= PAIRS or (SDA_SOURCE, "IO_SDA") not in output_pairs or not any(port == "IO_SCL" for _, port in output_pairs):
        raise ValueError("Foreign/missing native platform pad driver")
    if input_pairs != {("IO_SDA", node) for node in INPUTS}:
        raise ValueError("Foreign/missing native platform input capture endpoint")
    return {"schema": "bt-native-platform-topology-v1", "run": str(run), "binding": binding,
            "report_sha256": report_hashes, "output_pairs": sorted(output_pairs),
            "input_pairs": sorted(input_pairs), "output_paths": output_paths,
            "input_paths": selected[("IO_SDA", "from")], "native_catalog_complete": True,
            "path_cap": 25, "scope": "Complete bounded first-corner topology; no timing acceptance"}


def diagnostic_inventory(run: Path, topology: dict) -> dict:
    log = (run / "all-corners.log").read_text(encoding="utf-8")
    records = re.findall(r"(?m)^.*BT_IO_DIAGNOSTIC_SCL_NAMES=([^\r\n]*)$", log)
    if len(set(records)) != 1:
        raise ValueError("Missing/inconsistent executed diagnostic alias guard receipt")
    names = validate_scl_names(records[0].strip().split())
    routed = {tuple(row) for row in topology["output_pairs"]}
    if not {name for name, port in routed if port == "IO_SCL"} <= names:
        raise ValueError("Native routed SCL driver absent from actual guarded register collection")
    all_pairs = {(name, "IO_SCL") for name in names} | {(SDA_SOURCE, "IO_SDA")}
    return {"present_scl_names": sorted(names), "routed_output_pairs": sorted(routed),
            "zero_pad_path_pairs": sorted(all_pairs - routed),
            "zero_path_basis": "Complete approved nonsaturated report_path topology over every path to each pad; actual guarded register names recorded by diagnostic only",
            "all_present_aliases_accounted": True}
