"""Separate Quartus17 declaration-only edge over frozen bank-mirror v1.

Move only the four inline genvar declarations to one module-scope declaration.
Every loop label/range/body, instance input, clock and parameter is unchanged.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OLD_HELPER = ROOT / "tests/graphics/prepare_bt_sprite_bank_mirrors.py"
OLD_HELPER_SHA = "8af551fbf36514bd1bcb6751c9c113ee9a1c39a313922ecf7cddb6a5fa8f32bb"
OLD_EDGE = ROOT / "build/sprite_bank_mirrors_v20_v1/source-edge"
OLD_MANIFEST_SHA = "c8bbc80d05497e9ed1fdc04713837066a13757d95f517f4e1f8be2afb7025dc1"
OLD_SPR_SHA = "b7f63ada2c84b884ddb3e227475c8dcc1739b729702fdab10f9139d42536f2a1"
MODE_PROOF = ROOT / "build/sprite_registered_q_v20_v1/mode-probe-r1/receipt.json"
MODE_PROOF_SHA = "e7761704cfd68c9a87d244db7f3b3c1311aacb6d004f1befb3227acf40787cfd"
MEM = ROOT / "build/timing_closure_20261011/fg_sprite_controls_v20_private/rtl/BT_mem.sv"
MEM_SHA = "903aeedc272fd64409ebae8b8624befe82bc1f073d1545310dbeb070afaf6393"
PAIRS = [
    ("module_scope_genvars", 1,
     b" generate if (REGISTERED_FG_BANK_Q) begin : registered_foreground_banks\n",
     b" genvar foreground,bank;\n generate if (REGISTERED_FG_BANK_Q) begin : registered_foreground_banks\n"),
    ("foreground_loop_declarations", 2,
     b"for(genvar foreground=0;foreground<2;foreground=foreground+1)",
     b"for(foreground=0;foreground<2;foreground=foreground+1)"),
    ("bank_loop_declarations", 2,
     b"for(genvar bank=0;bank<4;bank=bank+1)",
     b"for(bank=0;bank<4;bank=bank+1)"),
]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def old_helper():
    assert sha(OLD_HELPER.read_bytes()) == OLD_HELPER_SHA
    assert sha((OLD_EDGE / "manifest.json").read_bytes()) == OLD_MANIFEST_SHA
    spec = importlib.util.spec_from_file_location("sprite_bank_v1_immutable", OLD_HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def syntax_edits():
    return [{"role": role, "count": count, "before_b64": base64.b64encode(before).decode(),
             "after_b64": base64.b64encode(after).decode()} for role,count,before,after in PAIRS]


def forward(data, edits):
    for edit in edits:
        before,after = base64.b64decode(edit["before_b64"]),base64.b64decode(edit["after_b64"])
        assert data.count(before) == edit.get("count", 1), (edit["role"], "forward anchor changed")
        data = data.replace(before,after)
    return data


def inverse(data, edits):
    for edit in reversed(edits):
        before,after = base64.b64decode(edit["before_b64"]),base64.b64decode(edit["after_b64"])
        assert data.count(after) == edit.get("count", 1), (edit["role"], "inverse anchor changed")
        data = data.replace(after,before)
    return data


def transform(data):
    assert sha(data) == OLD_SPR_SHA
    edits = syntax_edits()
    candidate = forward(data,edits)
    assert inverse(candidate,edits) == data
    return candidate,edits


def verify_edge(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_bytes())
    assert manifest["schema"] == "bt-v20-sprite-bank-mirrors-q17-declaration-edge-v1"
    old = old_helper()
    parents,prior_candidates,prior_manifest = old.verify_edge(OLD_EDGE)
    assert manifest["syntax_edits"] == syntax_edits()
    assert manifest["old_source_edge_sha256"] == OLD_MANIFEST_SHA
    assert manifest["helper_sha256"] == sha(Path(__file__).read_bytes())
    candidates = {}
    for rel,parent in parents.items():
        expected = prior_candidates[rel]
        edits = prior_manifest["files"][rel]["edits"]
        if rel == "rtl/spr_vram.sv":
            expected,syntax = transform(expected)
            edits = edits + syntax
        candidate = (directory / "candidate" / rel).read_bytes()
        assert (directory / "oracle" / rel).read_bytes() == parent
        assert candidate == expected
        assert manifest["files"][rel]["edits"] == edits
        assert manifest["files"][rel]["candidate_sha256"] == sha(candidate)
        assert inverse(candidate,edits) == parent
        assert forward(parent,edits) == candidate
        candidates[rel] = candidate
    return parents,candidates,manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    assert output.is_relative_to(ROOT / "build") and not output.exists()
    old = old_helper()
    parents,prior,prior_manifest = old.verify_edge(OLD_EDGE)
    candidate_spr,syntax = transform(prior["rtl/spr_vram.sv"])
    # Exact declaration relocation inverse proves all old edge/ABI expressions.
    assert candidate_spr.count(b"genvar foreground,bank;") == 1
    assert candidate_spr.count(b"for(foreground=0;foreground<2;foreground=foreground+1)") == 2
    assert candidate_spr.count(b"for(bank=0;bank<4;bank=bank+1)") == 2
    assert b"for(genvar " not in candidate_spr
    negatives = []
    for label,before,after in [
        ("lost_bank", b"bank<4", b"bank<3"),
        ("changed_foreground", b"foreground<2", b"foreground<1"),
        ("wrong_instance_input", b".DATA(DATA)", b".DATA(~DATA)"),
        ("changed_clock", b".CLK(CLK)", b".CLK(~CLK)"),
        ("changed_hard_mode", b"#(addr_width,1,1) mirror", b"#(addr_width,1,0) mirror"),
        ("changed_output_reset", b".ACLR(1'b0),.WADDR(WADDR)", b".ACLR(ACLR),.WADDR(WADDR)"),
        ("wrong_alias", b"FG0_Q=FG_BANK_Q[0][0]", b"FG0_Q=FG_BANK_Q[1][0]"),
        ("unrelated_original_Q", b"Q<=raw_q;", b"Q<=~raw_q;")]:
        changed = candidate_spr.replace(before,after,1)
        assert changed != candidate_spr
        try:
            assert sha(inverse(changed,syntax)) == OLD_SPR_SHA
        except AssertionError:
            negatives.append(label)
        else:
            raise AssertionError((label,"negative accepted"))
    files = {}
    for rel,parent in parents.items():
        candidate = candidate_spr if rel == "rtl/spr_vram.sv" else prior[rel]
        edits = prior_manifest["files"][rel]["edits"] + (syntax if rel == "rtl/spr_vram.sv" else [])
        assert inverse(candidate,edits) == parent
        files[rel] = {"parent_sha256": sha(parent), "candidate_sha256": sha(candidate), "edits": edits}
        for role,raw in (("oracle",parent),("candidate",candidate)):
            path = output / role / rel
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(raw)
    manifest = {"schema":"bt-v20-sprite-bank-mirrors-q17-declaration-edge-v1",
                "files":files,"syntax_edits":syntax,
                "old_source_edge":str(OLD_EDGE / "manifest.json"),"old_source_edge_sha256":OLD_MANIFEST_SHA,
                "old_helper":str(OLD_HELPER),"old_helper_sha256":OLD_HELPER_SHA,
                "helper":str(Path(__file__).resolve()),"helper_sha256":sha(Path(__file__).read_bytes()),
                "mode_proof":str(MODE_PROOF),"mode_proof_sha256":MODE_PROOF_SHA,
                "memory":str(MEM),"memory_sha256":MEM_SHA,
                "negative_controls_rejected":negatives,
                "source_induction":{"declarations_only":True,"loops_same_labels_ranges_bodies":True,
                                    "same_all_eight_instance_inputs_parameters_and_edges":True,
                                    "old_original_Q_NZ_and_ABI_unchanged":True},
                "new_simulation_or_Quartus_acceptance_claim":False}
    (output / "manifest.json").write_text(json.dumps(manifest,indent=2)+"\n")
    verify_edge(output)
    print(json.dumps({"edge":str(output),"manifest_sha256":sha((output/"manifest.json").read_bytes()),
                      "candidate_spr_sha256":sha(candidate_spr),"negative_controls":len(negatives)}))


if __name__ == "__main__":
    main()
