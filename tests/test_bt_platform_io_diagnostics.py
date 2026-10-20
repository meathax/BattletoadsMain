"""Conservative gate tests: synthetic reports are never native evidence."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bt_io_diagnostics",ROOT/"scripts/qualify_platform_io_diagnostics.py")
qualifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualifier)

def report(paths,check):
    text = f"report_timing -{check} -npaths 10 -detail full_path\n"
    for number,(source,target,data,launch,capture) in enumerate(paths,1):
        text += f"""Path #{number}: {check.title()} slack is -1000.000 (VIOLATED)
; From Node ; {source} ;
; To Node ; {target} ;
; Launch Clock ; {'FPGA_CLK2_50' if target.startswith('IO_') else '(none)'} ;
; Latch Clock ; {'FPGA_CLK2_50' if source == 'IO_SDA' else '(none)'} ;
; Slack ; -1000.000 (VIOLATED) ;
; {check.title()} Relationship ; {'-1000' if check == 'setup' else '1000'} ;
; Data Arrival Path ;
; 0 ; {launch} ; ; ; ; ; clock path ;
; 0 ; {data} ; ; ; ; ; data path ;
; Data Required Path ;
; 0 ; {capture} ; ; ; ; ; clock path ;
"""
    return text

class QualificationTests(unittest.TestCase):
    def fixture(self,base):
        original = base/"fitted"
        original.mkdir()
        (original/"test.qpf").write_text("PROJECT_REVISION = test\n")
        (original/"test.qsf").write_text("set_global_assignment -name GENERATE_RBF_FILE ON\n")
        (original/"db").mkdir()
        (original/"db/test.fit.cdb").write_bytes(b"synthetic immutable fitted database")
        target = base/"copies"
        manifest = qualifier.prepare(original,"test.qpf",target,False)
        runs = {}
        for group in ["input","output"]:
            run = base/(group+"-reports")
            runs[group] = run
            paths = [("IO_SDA",node,5,0,8) for node in sorted(qualifier.INPUT_FULL)] if group == "input" else [(a,b,4,8,0) for a,b in sorted(qualifier.OUTPUT_PAIRS)]
            for index in range(1,9):
                corner = run/"all-corners"/f"corner_{index}"
                corner.mkdir(parents=True)
                (corner/"condition.txt").write_text(f"Synthetic distinct condition {index}\n")
                for check in ["setup","hold"]: (corner/(check+".txt")).write_text(report(paths,check))
        return original,manifest,runs

    def test_bounds_coverage_and_original_preservation(self):
        with tempfile.TemporaryDirectory(dir=ROOT/"build",prefix="io-gate-test-") as folder:
            original,manifest,runs = self.fixture(Path(folder))
            before = qualifier.catalog(original,True)
            receipt_path = Path(folder)/"gate.json"
            receipt = qualifier.collect(manifest,[runs["input"]],[runs["output"]],receipt_path)
            self.assertEqual(receipt["result"],"PASS_NATIVE_PHYSICAL_PAD_BUDGETS")
            self.assertEqual(before,qualifier.catalog(original,True))
            copied = json.loads(manifest.read_text())["copies"]
            for group in copied:
                qsf = Path(copied[group]["qsf"]).read_text()
                self.assertNotIn("GENERATE_RBF_FILE ON",qsf)
                self.assertIn("GENERATE_RBF_FILE OFF",qsf)
            bad = runs["input"]/"all-corners/corner_8/setup.txt"
            bad.write_text(bad.read_text().replace("; 0 ; 5 ;", "; 0 ; 101 ;",1))
            receipt = qualifier.collect(manifest,[runs["input"]],[runs["output"]],receipt_path)
            self.assertEqual(receipt["result"],"FAIL")
            self.assertTrue(any("budget exceeded" in problem for problem in receipt["failures"]))

    def test_missing_endpoint_and_corner_cannot_pass(self):
        with tempfile.TemporaryDirectory(dir=ROOT/"build",prefix="io-gate-test-") as folder:
            _,manifest,runs = self.fixture(Path(folder))
            bad = runs["input"]/"all-corners/corner_1/hold.txt"
            bad.write_text(report([("IO_SDA",node,5,0,8) for node in sorted(qualifier.INPUT_FULL) if not node.endswith("rdata[4]")],"hold"))
            receipt = qualifier.collect(manifest,[runs["input"]],[runs["output"]],Path(folder)/"gate.json")
            self.assertTrue(any("missing exact source/endpoint coverage" in problem for problem in receipt["failures"]))
            (runs["output"]/"all-corners/corner_8/condition.txt").unlink()
            receipt = qualifier.collect(manifest,[runs["input"]],[runs["output"]],Path(folder)/"gate.json")
            self.assertEqual(receipt["result"],"FAIL")

    def test_original_mutation_and_parser_mismatch_cannot_pass(self):
        with tempfile.TemporaryDirectory(dir=ROOT/"build",prefix="io-gate-test-") as folder:
            original,manifest,runs = self.fixture(Path(folder))
            (original/"db/test.fit.cdb").write_bytes(b"changed")
            receipt = qualifier.collect(manifest,[runs["input"]],[runs["output"]],Path(folder)/"gate.json")
            self.assertTrue(any("Original fitted source/database changed" in problem for problem in receipt["failures"]))
            body = json.loads(manifest.read_text())
            body["compiled_source_mismatch"] = True
            manifest.write_text(json.dumps(body))
            receipt = qualifier.collect(manifest,[runs["input"]],[runs["output"]],Path(folder)/"gate.json")
            self.assertTrue(any("compiled/source mismatch" in problem for problem in receipt["failures"]))

    def test_missing_physical_clock_rows_cannot_pass(self):
        for group in ["input","output"]:
            with self.subTest(group=group), tempfile.TemporaryDirectory(dir=ROOT/"build",prefix="io-gate-test-") as folder:
                _,manifest,runs = self.fixture(Path(folder))
                bad = runs[group]/"all-corners/corner_1/setup.txt"
                bad.write_text(bad.read_text().replace("; 0 ; 8 ; ; ; ; ; clock path ;\n","",1))
                receipt = qualifier.collect(manifest,[runs["input"]],[runs["output"]],Path(folder)/"gate.json")
                self.assertEqual(receipt["result"],"FAIL")
                self.assertTrue(any("timing row 'clock path', found 0" in problem for problem in receipt["failures"]))

    def test_inapplicable_relationship_uses_strict_json_null(self):
        with tempfile.TemporaryDirectory(dir=ROOT/"build",prefix="io-gate-test-") as folder:
            _,manifest,runs = self.fixture(Path(folder))
            report_path = runs["input"]/"all-corners/corner_1/setup.txt"
            report_path.write_text(report_path.read_text().replace("; Setup Relationship ; -1000 ;\n",""))
            receipt_path = Path(folder)/"gate.json"
            receipt = qualifier.collect(manifest,[runs["input"]],[runs["output"]],receipt_path)
            self.assertEqual(receipt["result"],"PASS_NATIVE_PHYSICAL_PAD_BUDGETS")
            def reject_constant(value):
                raise ValueError("Non-standard JSON number: "+value)
            saved = json.loads(receipt_path.read_text(),parse_constant=reject_constant)
            self.assertTrue(all(path["relationship_ns"] is None for path in saved["corners"]["corner_1"]["input"]["setup"]["paths"]))

    def test_nonfinite_physical_delays_cannot_pass(self):
        with tempfile.TemporaryDirectory(dir=ROOT/"build",prefix="io-gate-test-") as folder:
            _,manifest,runs = self.fixture(Path(folder))
            bad = runs["input"]/"all-corners/corner_1/setup.txt"
            bad.write_text(bad.read_text().replace("; 0 ; 5 ;","; 0 ; nan ;",1))
            receipt = qualifier.collect(manifest,[runs["input"]],[runs["output"]],Path(folder)/"gate.json")
            self.assertEqual(receipt["result"],"FAIL")
            self.assertTrue(any("Non-finite physical timing row" in problem for problem in receipt["failures"]))

if __name__ == "__main__": unittest.main()
