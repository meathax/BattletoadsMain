"""Fresh v2 execution with two explicit immutable dependency-path bindings.

The v1 worker/verifier bytes are unchanged. Only PREPARER in each newly loaded
module is bound to the strict Q17 source adapter. No filesystem API is patched.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
PREPARER = ROOT / "tests/graphics/prepare_bt_sprite_bank_mirrors_q17.py"
WORKER = ROOT / "tests/graphics/qualify_bt_sprite_bank_mirrors.py"
WORKER_SHA = "bb993daa409d0de4347d23342e407c3d38078f11e808e45f4f1001da7355d077"
VERIFIER = ROOT / "tests/graphics/verify_bt_sprite_bank_mirror_proof.py"
VERIFIER_SHA = "7dd20807646176ab2a4d37c9302051987b6e1f00eb2f8314005972a13a2852e7"
OLD_PREPARER = ROOT / "tests/graphics/prepare_bt_sprite_bank_mirrors.py"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(path,name,expected=None):
    if expected is not None:
        assert sha(path.read_bytes()) == expected
    spec = importlib.util.spec_from_file_location(name,path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_composition_receipt(path):
    path = Path(path).resolve()
    sidecar = json.loads(path.read_bytes())
    assert sidecar["schema"] == "bt-v20-sprite-bank-mirror-q17-declaration-qualification-v1"
    assert sidecar["status"] == "PASS_FRESH_VENDOR_CONSUMERS_AND_PINS"
    assert sidecar["adapter_sha256"] == sha(Path(__file__).read_bytes())
    source = load(PREPARER,"strict_q17_bank_source")
    parents,candidates,manifest = source.verify_edge(Path(sidecar["edge"]))
    assert sidecar["edge_sha256"] == sha((Path(sidecar["edge"])/"manifest.json").read_bytes())
    assert sidecar["candidate_sources"] == {rel:sha(raw) for rel,raw in candidates.items()}
    verifier = load(VERIFIER,"unchanged_v1_bank_verifier",VERIFIER_SHA)
    assert verifier.PREPARER == OLD_PREPARER
    verifier.PREPARER = PREPARER  # One declared dependency of this fresh module.
    validated = verifier.verify_proof(sidecar["edge"],sidecar["worker_receipt"])
    assert sidecar["validated_evidence"] == validated
    assert sidecar["worker_sha256"] == WORKER_SHA
    assert sidecar["verifier_sha256"] == VERIFIER_SHA
    assert sidecar["source_adapter_sha256"] == sha(PREPARER.read_bytes())
    assert sidecar["new_v1_receipt_retagged"] is False
    return {"status":"PASS_SOURCE_INPUT_LOG_AND_COVERAGE_BINDING",
            "bound_evidence_files":{**validated["bound_evidence_files"],str(path):sha(path.read_bytes()),
                str(PREPARER):sha(PREPARER.read_bytes()),str(Path(__file__).resolve()):sha(Path(__file__).read_bytes()),
                str(WORKER):WORKER_SHA,str(VERIFIER):VERIFIER_SHA},
            "source_edge":str(Path(sidecar["edge"])/"manifest.json"),
            "declaration_only_edge":manifest["syntax_edits"],
            "physical_timing_or_retention_accepted":False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--edge",required=True)
    parser.add_argument("--output",required=True)
    args = parser.parse_args()
    edge,output = Path(args.edge).resolve(),Path(args.output).resolve()
    assert output.is_relative_to(ROOT/"build") and not output.exists()
    source = load(PREPARER,"strict_q17_bank_source")
    parents,candidates,manifest = source.verify_edge(edge)
    worker = load(WORKER,"unchanged_v1_bank_worker",WORKER_SHA)
    assert worker.PREPARER == OLD_PREPARER
    worker.PREPARER = PREPARER  # Named source guard only; all fixtures/assertions survive.
    argv = sys.argv
    try:
        sys.argv = [str(WORKER),"--edge",str(edge),"--output",str(output)]
        worker.main()
    finally:
        sys.argv = argv
    verifier = load(VERIFIER,"unchanged_v1_bank_verifier",VERIFIER_SHA)
    assert verifier.PREPARER == OLD_PREPARER
    verifier.PREPARER = PREPARER
    validated = verifier.verify_proof(edge,output/"receipt.json")
    sidecar = {"schema":"bt-v20-sprite-bank-mirror-q17-declaration-qualification-v1",
               "status":"PASS_FRESH_VENDOR_CONSUMERS_AND_PINS",
               "edge":str(edge),"edge_sha256":sha((edge/"manifest.json").read_bytes()),
               "candidate_sources":{rel:sha(raw) for rel,raw in candidates.items()},
               "worker_receipt":str(output/"receipt.json"),"worker_sha256":WORKER_SHA,
               "verifier_sha256":VERIFIER_SHA,"source_adapter_sha256":sha(PREPARER.read_bytes()),
               "adapter_sha256":sha(Path(__file__).read_bytes()),
               "dependency_bindings":[{"module":"fresh worker","field":"PREPARER","old":str(OLD_PREPARER),"new":str(PREPARER)},
                                      {"module":"fresh verifier","field":"PREPARER","old":str(OLD_PREPARER),"new":str(PREPARER)}],
               "validated_evidence":validated,"new_v1_receipt_retagged":False,
               "new_native_fit_or_board_replay":False}
    (output/"executed_q17_adapter.py").write_bytes(Path(__file__).read_bytes())
    target = output/"q17-declaration-qualification.json"
    target.write_text(json.dumps(sidecar,indent=2)+"\n")
    verify_composition_receipt(target)
    print(json.dumps({"status":sidecar["status"],"receipt":str(target),"sha256":sha(target.read_bytes())}))


if __name__ == "__main__":
    main()
