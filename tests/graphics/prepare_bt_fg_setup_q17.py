"""Quartus-17 spelling of the frozen v18 setup edge; original proof is retained."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OLD_EDGE = ROOT/'build/fg_setup_v18_v1'
OLD_MANIFEST_SHA = '113dfa0c55b8c061f3aa5c17c22e6a25923cee85349934d8dc8d926f3489f7b7'
OLD_CANDIDATE_SHA = 'ed7d3ad9a4360e6fe459e2018ecb815f4d391c8fd49300580032c5f6bbb92c01'
SHA = lambda raw: hashlib.sha256(raw).hexdigest()
OLD_CAPTURE = "\t\tCOPY_READ_REQUEST_M <= {8{!bit'(RAS_N) && !bit'(OE_N) && bit'(WE_N) && bit'(TRANSFER)}};"
NEW_CAPTURE = '\t\tCOPY_READ_REQUEST_M <= {8{FG_READ_COMMAND(RAS_N, OE_N, WE_N, TRANSFER)}};'
FUNCTION = '''\t// Bit-valued automatic arguments reproduce the original flag captures\n\t// before evaluating the predicate, including four-state simulator inputs.\n\tfunction automatic bit FG_READ_COMMAND;\n\t\tinput bit ras_n, oe_n, we_n, transfer;\n\t\tbegin\n\t\t\tFG_READ_COMMAND = !ras_n && !oe_n && we_n && transfer;\n\t\tend\n\tendfunction\n'''
ANCHOR = "\t(* preserve, dont_merge *) bit [7:0] COPY_READ_REQUEST_M = '0;\n"


def old_helper():
    raw = (OLD_EDGE/'manifest.json').read_bytes()
    assert SHA(raw) == OLD_MANIFEST_SHA
    manifest = json.loads(raw)
    path = Path(manifest['helper_path'])
    assert SHA(path.read_bytes()) == manifest['helper_sha256']
    spec = importlib.util.spec_from_file_location('frozen_v1_setup_preparer', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def spelling(v1: bytes):
    assert SHA(v1) == OLD_CANDIDATE_SHA
    text = v1.decode().replace('\r\n','\n')
    assert text.count(ANCHOR)==1 and text.count(OLD_CAPTURE)==1
    text = text.replace(ANCHOR,FUNCTION+ANCHOR,1).replace(OLD_CAPTURE,NEW_CAPTURE,1)
    return text.replace('\n','\r\n').encode(), [
        {'old':ANCHOR,'new':FUNCTION+ANCHOR},{'old':OLD_CAPTURE,'new':NEW_CAPTURE}]


def transform(parent: bytes):
    v1, edits = old_helper().transform(parent)
    candidate, spelling_edits = spelling(v1)
    return candidate, edits+spelling_edits


def reverse(candidate: bytes, edits: list[dict]):
    text = candidate.decode().replace('\r\n','\n')
    assert edits[-2:] == [{'old':ANCHOR,'new':FUNCTION+ANCHOR},{'old':OLD_CAPTURE,'new':NEW_CAPTURE}]
    for edit in reversed(edits[-2:]):
        assert text.count(edit['new'])==1
        text = text.replace(edit['new'],edit['old'],1)
    return old_helper().reverse(text.replace('\n','\r\n').encode(),edits[:-2])


def verify_source(parent: bytes, candidate: bytes, edits: list[dict]):
    helper = old_helper()
    v1, original_edits = helper.transform(parent)
    expected, spelling_edits = spelling(v1)
    assert candidate==expected and edits==original_edits+spelling_edits
    assert reverse(candidate,edits)==parent
    coverage = helper.verify_source(parent,v1,original_edits)
    assert candidate.count(b"bit'(")==0
    assert candidate.count(FUNCTION.replace('\n','\r\n').encode())==1
    for value in (NEW_CAPTURE+'\n').encode(), b'FG_READ_COMMAND = !ras_n && !oe_n && we_n && transfer;':
        assert value.rstrip(b'\n') in candidate
    coverage.update(quartus_spelling_edge_inverse=True, scalar_casts_remaining=0,
        function_argument_type='four automatic scalar bit inputs; conversion occurs inside original capture edge',
        v1_candidate_sha256=OLD_CANDIDATE_SHA)
    return coverage


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    output=args.output.resolve();output.relative_to(ROOT/'build')
    assert not output.exists(), 'Preserve all v1 and failed evidence'
    helper=old_helper();parent=helper.PARENT.read_bytes()
    candidate,edits=transform(parent);coverage=verify_source(parent,candidate,edits)
    output.mkdir(parents=True)
    for name,raw in [('candidate/rtl/fg_vram.sv',candidate),('immutable_parent/rtl/fg_vram.sv',parent),
                     ('immutable_v1/rtl/fg_vram.sv',transform(parent)[0] if False else helper.transform(parent)[0])]:
        path=output/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    manifest={'schema':'bt-fg-setup-v18-q17-source-edge-v2','parent_path':str(helper.PARENT),
        'parent_sha256':helper.PARENT_SHA,'candidate_path':str(output/'candidate/rtl/fg_vram.sv'),
        'candidate_sha256':SHA(candidate),'helper_path':str(Path(__file__).resolve()),
        'helper_sha256':SHA(Path(__file__).read_bytes()),'edits':edits,
        'v1_manifest':str(OLD_EDGE/'manifest.json'),'v1_manifest_sha256':OLD_MANIFEST_SHA,
        'v1_candidate_sha256':OLD_CANDIDATE_SHA,'spelling_edits':edits[-2:],
        'source_line_endings':'Original raw CRLF','constraints_modified':False,
        'original_capture_edges_preserved':True,'new_register_bits':15,
        'compiled_gate_claim':False,'mapped_or_timing_claim':False}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    receipt={'schema':'bt-fg-setup-v18-q17-source-proof-v2','status':'PASS',
        'manifest_sha256':SHA((output/'manifest.json').read_bytes()),'candidate_sha256':SHA(candidate),
        'parent_sha256':helper.PARENT_SHA,'coverage':coverage,'compiled_gate_claim':False}
    (output/'source-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'candidate':str(output/'candidate/rtl/fg_vram.sv'),'sha256':SHA(candidate),
        'manifest_sha256':receipt['manifest_sha256'],'source_receipt_sha256':SHA((output/'source-receipt.json').read_bytes())},separators=(',',':')))


if __name__=='__main__':main()
