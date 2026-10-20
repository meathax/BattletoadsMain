"""Source/DB-bound native alias parser check, with omission/rejection controls.

The original fitted v11 image fails core setup. This receipt accepts only the
reviewed constraint parser/topology, never its timing or a future fitted image.
"""
from __future__ import annotations
import argparse
import json
import shutil
import sys
import tempfile
import tkinter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import qualify_platform_io_diagnostics as io
import platform_io_topology as topology
import prepare_platform_io_sclk_alias as alias


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--inventory-manifest", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    if args.receipt.exists() or not args.receipt.resolve().is_relative_to(ROOT / "build"):
        raise ValueError("New parser receipt must stay in ignored build/")
    manifest = json.loads(args.inventory_manifest.read_text())
    original = Path(manifest["original_workspace"])
    copy = Path(manifest["copy"]["path"])
    original_sources = io.catalog(original)
    original_database = io.catalog(original, True)
    assert original_sources == manifest["original_sources"], "Original fitted sources changed"
    assert original_database == manifest["original_database"], "Original fitted DB changed"
    assert io.physical_db(io.catalog(copy, True)) == manifest["original_physical_database"], "Diagnostic physical DB changed"
    old_sdc = original / "rtl/bt_platform_io.sdc"
    new_sdc = copy / "rtl/bt_platform_io.sdc"
    assert alias.transform(old_sdc.read_bytes()) == new_sdc.read_bytes(), "Alias constraint edge is not exact/reversible"
    actual_sources = io.catalog(copy)
    differences = {name: digest for name, digest in actual_sources.items() if original_sources.get(name) != digest}
    assert set(differences) == {"Arcade-Battletoads.qsf", "rtl/bt_platform_io.sdc", "bt_inventory_only.sdc", "inspect_platform_io.tcl"}, differences
    assert "GENERATE_RBF_FILE OFF" in (copy / "Arcade-Battletoads.qsf").read_text()
    assert not list(copy.glob("*.rbf")), "Diagnostic RBF unexpected"
    corners = topology.fresh_corners(args.run)
    keeper = topology.keeper_catalog(args.run, copy / "Arcade-Battletoads.qpf")
    expected_pairs = {("mcp23009|i2c|I2C_CLOCK", "IO_SCL"), ("mcp23009|i2c|SCLK~DUPLICATE", "IO_SCL"), ("mcp23009|i2c|SDO[3]", "IO_SDA")}
    assert {tuple(pair) for pair in keeper["output_pairs"]} == expected_pairs
    names = topology.validate_scl_names(sorted(topology.SCL_BASE | {node for node, port in expected_pairs if port == "IO_SCL"}))
    zero_pairs = sorted({(name, "IO_SCL") for name in names} - expected_pairs)
    controls = []
    def rejected(name, operation):
        try:
            operation()
        except (ValueError, AssertionError, OSError, KeyError):
            controls.append(name)
        else:
            raise AssertionError("Negative control accepted: " + name)
    for name, values in [("missing_base", ["mcp23009|i2c|I2C_CLOCK"]),
                         ("foreign_alias", [*sorted(names), "mcp23009|i2c|SCLK~DUPLICATE1"]),
                         ("repeated_alias", [*sorted(names), "mcp23009|i2c|SCLK"]),
                         ("foreign_hierarchy", [name.replace("mcp23009|", "foreign|") for name in names])]:
        rejected(name, lambda values=values: topology.validate_scl_names(values))
    with tempfile.TemporaryDirectory(prefix="io-topology-controls-", dir=ROOT / "build") as temp:
        root = Path(temp)
        source = args.run / "all-corners/keeper-catalog/30-to.rpt"
        body = source.read_text()
        test = root / "route.rpt"
        for name, changed in [("missing_path", body.replace("Path #2:", "Removed #2:")),
                              ("repeated_path", body.replace("Path #2:", "Path #1:")),
                              ("wrong_command", body.replace("-npaths 25", "-npaths 1")),
                              ("count_mismatch", body.replace("Found 2 paths.", "Found 1 paths.")),
                              ("wrong_pad", body.replace("; IO_SCL", "; FOREIGN_PAD")),
                              ("missing_detail", body.replace("; Data Arrival Path", "; Removed Data Arrival Path")),
                              ("nonfinite_delay", body.replace("Delay is 8.542", "Delay is nan"))]:
            test.write_text(changed)
            rejected(name, lambda: topology.parse_route_report(test, "IO_SCL", "to", 2))
        rejected("cap_saturation", lambda: topology.parse_route_report(source, "IO_SCL", "to", 25))
        shutil.copytree(args.run / "all-corners", root / "all-corners")
        for name, mode in [("missing_corner", "missing"), ("duplicate_corner", "duplicate"), ("nonzero_ucp", "nonzero"), ("missing_ucp_summary", "summary")]:
            trial = root / name
            shutil.copytree(root / "all-corners", trial / "all-corners")
            if mode == "missing": shutil.rmtree(trial / "all-corners/corner_8")
            if mode == "duplicate": shutil.copyfile(trial / "all-corners/corner_1/condition.txt", trial / "all-corners/corner_8/condition.txt")
            if mode in {"nonzero", "summary"}:
                report = trial / "all-corners/corner_8/unconstrained.txt"
                data = report.read_text()
                data = data.replace("; Unconstrained Input Port Paths  ; 0     ; 0", "; Unconstrained Input Port Paths  ; 1     ; 0") if mode == "nonzero" else data.replace("Unconstrained Input Port Paths", "Removed Input Port Paths")
                report.write_text(data)
            rejected(name, lambda trial=trial: topology.fresh_corners(trial))
        source_run = root / "native"
        source_run.mkdir()
        for relative in ["keeper-catalog-binding.json", "all-corners.log"]:
            shutil.copyfile(args.run / relative, source_run / relative)
        shutil.copytree(root / "all-corners", source_run / "all-corners")
        keeper_dir = source_run / "all-corners/keeper-catalog"
        scope = keeper_dir / "scope.txt"
        initial = scope.read_text()
        scope.write_text(initial.replace("catalog_complete=1", "catalog_complete=0"))
        rejected("incomplete_catalog", lambda: topology.keeper_catalog(source_run))
        scope.write_text(initial)
        report = keeper_dir / "30-to.rpt"
        report.write_text(report.read_text().replace("SCLK~DUPLICATE", "SCLK~FOREIGN"))
        rejected("foreign_actual_driver", lambda: topology.keeper_catalog(source_run))
    numeric_paths = 0
    for corner in sorted((args.run / "all-corners").glob("corner_*")):
        for check in ["setup", "hold"]:
            numeric_paths += len(io.parse_paths(corner / (check + ".txt"), check))
    # Execute the exact generated diagnostic selector in native Tcl. Collection
    # stubs model only object iteration, so this proves selection/guard logic;
    # actual TimeQuest parsing/routing still requires the subsequent native run.
    selector_cases = []
    tcl_setup = r'''
        proc foreach_in_collection {var collection body} {
            foreach object $collection {uplevel 1 [list set $var $object]; uplevel 1 $body}
        }
        proc get_node_info {option object} {return $object}
        proc get_collection_size {collection} {return [llength $collection]}
        proc get_registers {names} {return $names}
        proc set_max_delay {args} {lappend ::constraints [linsert $args 0 max]}
        proc set_min_delay {args} {lappend ::constraints [linsert $args 0 min]}
        proc puts {message} {lappend ::messages $message}
        set constraints {}
        set messages {}
        set bt_io_sda IO_SDA
        set bt_io_scl IO_SCL
        set bt_io_sda_reg {mcp23009|i2c|SDO[3]}
    '''
    for label, scl, group, targets, expected in [
        ("base_default", topology.SCL_BASE, "output", None, 6),
        ("clone_default", names, "output", None, 8),
        ("clone_focus", names, "output", {"SCLK~DUPLICATE"}, 2),
        ("base_focus", names, "output", {"SCLK"}, 2),
        ("all_inputs", names, "input", None, 2),
        ("input_focus", names, "input", {"ACK"}, 2),
    ]:
        interp = tkinter.Tcl()
        interp.eval(tcl_setup)
        interp.eval(alias.ALIAS_PROC)
        interp.setvar("bt_io_scl_regs", tuple(sorted(scl)))
        interp.setvar("bt_io_scl_raw_names", tuple(sorted(scl)))
        interp.eval(io.stress_text(group, targets))
        constraints = interp.splitlist(interp.getvar("constraints"))
        assert len(constraints) == expected, (label, constraints)
        if group == "output":
            selected = {str(interp.splitlist(interp.splitlist(row)[3])[0]) for row in constraints}
            wanted = (set(scl) | {topology.SDA_SOURCE}) if targets is None else {"mcp23009|i2c|" + name for name in targets}
            assert selected == wanted, (label, selected, wanted)
        selector_cases.append(label)
    for label, scl, targets in [
        ("missing_requested_clone", topology.SCL_BASE, {"SCLK~DUPLICATE"}),
        ("foreign_selector_alias", names | {"mcp23009|i2c|SCLK~FOREIGN"}, None),
        ("missing_selector_base", {"mcp23009|i2c|I2C_CLOCK"}, None),
    ]:
        interp = tkinter.Tcl()
        interp.eval(tcl_setup)
        interp.eval(alias.ALIAS_PROC)
        interp.setvar("bt_io_scl_regs", tuple(sorted(scl)))
        interp.setvar("bt_io_scl_raw_names", tuple(sorted(scl)))
        try:
            interp.eval(io.stress_text("output", targets))
        except tkinter.TclError:
            controls.append(label)
        else:
            raise AssertionError("Diagnostic selector accepted " + label)
    receipt = {"schema": "bt-platform-alias-native-parser-v1", "result": "PASS_NATIVE_CONSTRAINT_PARSER_AND_TOPOLOGY",
               "release_timing_accepted": False, "physical_pad_budgets_accepted": False,
               "run": str(args.run), "inventory_manifest_sha256": io.sha(args.inventory_manifest),
               "original_source_sha256": original_sources, "original_database_sha256": original_database,
               "original_unchanged": True, "diagnostic_only_source_edges": differences,
               "actual_diagnostic_source_sha256": actual_sources, "physical_database_unchanged": True,
               "alias_sdc_old_sha256": io.sha(old_sdc), "alias_sdc_new_sha256": io.sha(new_sdc),
               "fresh_corners": corners, "keeper_catalog": keeper,
               "present_aliases_basis": "Reviewed native SDC requires original I2C_CLOCK/SCLK anchors; complete native route reports prove the observed optional SCLK~DUPLICATE exists and drives the pad",
               "present_aliases": sorted(names),
               "zero_pad_path_pairs": zero_pairs, "negative_controls": controls,
               "numeric_full_paths_parsed": numeric_paths, "native_tcl_selector_positive_cases": selector_cases,
               "helper_sha256": {str(path.relative_to(ROOT)): io.sha(path) for path in [Path(__file__), ROOT / "scripts/platform_io_topology.py", ROOT / "scripts/qualify_platform_io_diagnostics.py", ROOT / "scripts/prepare_platform_io_sclk_alias.py"]},
               "scope": "Exact closed v11 fitted DB with explicitly reversible reviewed alias constraint overlay. Core setup still fails; final-image physical budgets require fresh stressed setup/hold reports at all eight corners."}
    args.receipt.parent.mkdir(parents=True)
    args.receipt.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"result": receipt["result"], "corners": len(corners), "fresh_ucp": 0,
                      "routed_pairs": keeper["output_pairs"], "zero_pairs": zero_pairs,
                      "negative_controls": len(controls), "numeric_full_paths": numeric_paths,
                      "selector_cases": len(selector_cases), "receipt": str(args.receipt)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
