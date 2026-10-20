#!/usr/bin/env python3
"""Bind exact v22 sources to immutable v20 evidence and four scoped fresh edges.

This helper runs no compiler, simulator, STA, assembly, or hardware operation.
Each standalone execution remains attached to its actual source. Whole-file
inverse composition, rather than a retag, establishes applicability to v22.
"""
from __future__ import annotations
import argparse
import base64
import copy
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build"
FLOW = BUILD / "timing_closure_20261011"
SNAPSHOT = FLOW / "q17_local_paths_v22_private-snapshot.json"
SOURCE_ROOT = FLOW / "q17_local_paths_v22_private"
SCHEMA = "bt-v22-current-input-local-path-composition-v1"
STATUS = "PASS_SCOPED_COMPOSITION"
CHANGED = ("rtl/BT.sv", "rtl/fg_vram.sv", "rtl/spr_vram.sv", "rtl/ddram.sv")
PINS = {
 "snapshot": (SNAPSHOT, "339bf281bad4f0235b0effb5b1b468a9ac6854421634aaec8d489bcc93520aed"),
 "parent_snapshot": (FLOW/"fg_sprite_controls_v20_private-snapshot.json", "e889eac9badb82a3ab654cf7b6b22c05235849300c70b45734b5bc8725064ab4"),
 "parent_receipt": (BUILD/"final_v20_current_input_qualification_r2/receipt.json", "2d3362d2ad929c2df0b8c5f8764e493d92580a7d6a7776f7285b4231a65066cb"),
 "parent_helper": (ROOT/"tests/graphics/bind_bt_final_sprite_fg_inputs.py", "2499c4ae6afb59c41cd5bac254dc1092766209c5a583415f0e74e31f3bf4ff09"),
 "parent_native": (BUILD/"native_lcell_link_v20_v1/qualified-128-r3/receipt.json", "0045422f3d4fb925ba9f730c89e37cd2e5feb99079c4e9044ce6919aae538909"),
 "sprite_edge": (BUILD/"sprite_bank_mirrors_v20_v2/source-edge/manifest.json", "d70c1ce3302a795f14cce2512f7842579bfd7ec91a963638195cb5280a1ed73b"),
 "sprite_preparer": (ROOT/"tests/graphics/prepare_bt_sprite_bank_mirrors_q17.py", "037aba88bddd1c1d54d5cab671c47fd38f6c712c5d71609a9190cc559a1d200c"),
 "sprite_qualifier": (ROOT/"tests/graphics/qualify_bt_sprite_bank_mirrors_q17.py", "17d16cf5b93254e693b457ddd4887d2c4d8ea7aa550cc6c88c9fa02dd8844019"),
 "sprite_proof": (BUILD/"sprite_bank_mirrors_v20_v2/proof-r1/q17-declaration-qualification.json", "592cea92366ee665ed318ed70582bd70ef8fe2c8219dc38a3ab2d906358a400e"),
 "fg_edge": (BUILD/"fg_local_controls_v20_v1/source-edge/manifest.json", "1eec5204aaa5d46240a950ea39824b6741ce4abcb0801136a57614ca1c7b0239"),
 "fg_preparer": (ROOT/"tests/graphics/prepare_bt_fg_v20_controls.py", "ff98bb48363dd2b354cb3e39dd3e534abff91c9664b874b4dbd6c57c755282fb"),
 "fg_qualifier": (ROOT/"tests/graphics/qualify_bt_fg_v20_controls.py", "dcb52aecb244fb56d3bf45d6fed2937b117d1d384c50ae8490389bff5e4e2006"),
 "fg_proof": (BUILD/"fg_local_controls_v20_v1/qualification.json", "f76d780f2c790290abbf7afd925a39343587df1ec9d0d079ca6d0f1a7bcf5c0c"),
 "ddr_edge": (BUILD/"ddr_din_local_flags_v20_v2/manifest.json", "7a0fe6bb8015c351403d4e33cb41f2dbf0528ded335a45eef7ec542fc461dc85"),
 "ddr_preparer": (ROOT/"tests/graphics/prepare_bt_ddr_din_local_flags.py", "10a84f846daaa26dccd5d2d9431e96c65d276ed4fca369ce2e77b2d0cc799365"),
 "ddr_qualifier": (ROOT/"tests/graphics/qualify_bt_ddr_din_local_flags.py", "e03487334894c8f74249ddb609d277839c8279c5c9620abbaf2dd12e7a13b166"),
 "ddr_proof": (BUILD/"ddr_din_local_flags_v20_v2/proof-r2/receipt.json", "60d49e56e363d8b5f130215b4022653a6b40fb9699a8eaff451b6ae296093d80"),
 "pixel_edge": (BUILD/"pixel_parallel_v20_v1/source-edge/manifest.json", "cef1aee684116f7dcb2f0d14072f37c12b7a530d49ba2f15426c4b75a00564f0"),
 "pixel_preparer": (ROOT/"tests/graphics/prepare_bt_pixel_parallel.py", "4a43226a9ae2255587b3856c6605beb260ccca9b1dfae0292feef3fd28b00452"),
 "pixel_verifier": (ROOT/"tests/graphics/verify_bt_pixel_parallel.py", "270ce51dfd289c4bc3f6e2ec16792008a20a9d0250f1754b713a6ffcf600bd4a"),
 "pixel_proof": (BUILD/"pixel_parallel_v20_v1/proof-r1/receipt.json", "65d0d84b3a8a818a1829437953b846c898e5dc2a062259267823d65c85503e91"),
}
FG_COUNTS = {"states":31,"ram_banks":4,"ram_pin_fields":13,"state_edges":1263909,
 "bank_edge_checks":10111272,"same_edge_control_checks":1262137,
 "comparison":"case equality before/after every RAM edge"}
FG_NATIVE = {"cold_clear_writes":196608,"masked_writes":128,"copy_bytes":512}
FG_FOUR = {"raw_xz_cases":1024,"position_xz_cases":4194304,"unknown_control_cases":65536,
 "compiled_coercion_negative_rejected":1}

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def require(value, message):
    if not value:
        raise ValueError(message)

def json_normal(value):
    return json.loads(json.dumps(value))

class Evidence:
    def __init__(self):
        self.files = {}
    def file(self, path, expected=None):
        path = Path(path)
        if not path.is_absolute():
            path = ROOT/path
        require(not path.is_symlink(), "Symlink evidence is not accepted: "+str(path))
        path = path.resolve()
        raw = path.read_bytes()
        digest = sha(raw)
        require(expected is None or digest == expected, "Evidence digest changed: "+str(path))
        previous = self.files.get(str(path))
        require(previous is None or previous == digest, "Conflicting evidence identity")
        self.files[str(path)] = digest
        return raw
    def json(self, path, expected=None):
        return json.loads(self.file(path, expected))
    def record(self, value):
        raw = self.file(value["path"], value["sha256"])
        if "bytes" in value:
            require(len(raw) == value["bytes"], "Recorded evidence size changed")
        return raw
    def ingest(self, files):
        for path, digest in files.items():
            self.file(path, digest)
    def recheck(self):
        for path, digest in tuple(self.files.items()):
            self.file(path, digest)

def load(path, expected, name, evidence):
    evidence.file(path, expected)
    spec = importlib.util.spec_from_file_location("strict_v22_"+name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

def pinned(key, evidence):
    return evidence.file(*PINS[key])

def pinned_json(key, evidence):
    return json.loads(pinned(key, evidence))

def pinned_module(key, evidence):
    return load(*PINS[key], key, evidence)

def bind_record_tree(value, evidence):
    """Accept explicit path/digest record shapes, never arbitrary string paths."""
    if isinstance(value, dict):
        if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
            evidence.record(value)
        for child in value.values():
            if isinstance(child, (dict,list)):
                bind_record_tree(child, evidence)
    elif isinstance(value, list):
        for child in value:
            bind_record_tree(child, evidence)

def compose_sources(raw, parent, modules, edges, sprite_candidates):
    """Check both guarded transform orders against the ACTUAL merged files."""
    spr, fg, ddr, pix = (modules[k] for k in ("sprite","fg","ddr","pixel"))
    se, fe, de, pe = (edges[k] for k in ("sprite","fg","ddr","pixel"))
    require(set(raw) == set(CHANGED), "Complete four-file edge required")
    for rel in ("rtl/BT.sv","rtl/fg_vram.sv","rtl/spr_vram.sv"):
        require(spr.inverse(sprite_candidates[rel], se["files"][rel]["edits"]) == parent[rel],
                "Sprite edge parent differs from immutable v20")
    fg_ops = fe["edits"]
    bank_ops = se["files"]["rtl/fg_vram.sv"]["edits"]
    expected_control = fg.forward(parent["rtl/fg_vram.sv"],fg_ops)
    expected_bank = sprite_candidates["rtl/fg_vram.sv"]
    require(fg.forward(expected_bank,fg_ops) == raw["rtl/fg_vram.sv"], "FG bank-first composition changed")
    require(spr.forward(expected_control,bank_ops) == raw["rtl/fg_vram.sv"], "FG control-first composition changed")
    require(fg.reverse(spr.inverse(raw["rtl/fg_vram.sv"],bank_ops),fg_ops) == parent["rtl/fg_vram.sv"],
            "Actual FG complete inverse order one changed")
    require(spr.inverse(fg.reverse(raw["rtl/fg_vram.sv"],fg_ops),bank_ops) == parent["rtl/fg_vram.sv"],
            "Actual FG complete inverse order two changed")
    pixel_ops = pe["edits"]
    sprite_bt_ops = se["files"]["rtl/BT.sv"]["edits"]
    expected_pixel = pix.forward(parent["rtl/BT.sv"], pixel_ops)
    require(pix.forward(sprite_candidates["rtl/BT.sv"],pixel_ops) == raw["rtl/BT.sv"],
            "BT sprite-first composition changed")
    require(spr.forward(expected_pixel,sprite_bt_ops) == raw["rtl/BT.sv"],
            "BT pixel-first composition changed")
    require(spr.inverse(pix.reverse(raw["rtl/BT.sv"],pixel_ops),sprite_bt_ops) == parent["rtl/BT.sv"],
            "Actual BT inverse order one changed")
    require(pix.reverse(spr.inverse(raw["rtl/BT.sv"],sprite_bt_ops),pixel_ops) == parent["rtl/BT.sv"],
            "Actual BT inverse order two changed")
    require(raw["rtl/spr_vram.sv"] == sprite_candidates["rtl/spr_vram.sv"],
            "Q17 sprite source changed")
    require(spr.inverse(raw["rtl/spr_vram.sv"],se["files"]["rtl/spr_vram.sv"]["edits"])
            == parent["rtl/spr_vram.sv"], "Full SPR raw inverse changed")
    expected_ddr, expected_ops = ddr.transform(parent["rtl/ddram.sv"])
    require(expected_ops == de["edits"] and expected_ddr == raw["rtl/ddram.sv"],
            "Full DDR transform/source changed")
    require(ddr.reverse(raw["rtl/ddram.sv"],de["edits"]) == parent["rtl/ddram.sv"],
            "Full DDR inverse changed")
    return {
     "actual_combined_sources":{rel:sha(data) for rel,data in raw.items()},
     "v20_parents":{rel:sha(data) for rel,data in parent.items()},
     "BT_both_inverse_orders_raw_equal":True,
     "FG_both_inverse_orders_raw_equal":True,
     "SPR_Q17_three_declaration_ops_and_all_body_inverse_raw_equal":True,
     "DDR_complete_same_D_flag_inverse_raw_equal":True,
     "extra_clock_edges":0,
     "applicability":"Independent exact source induction and consumer-pin equivalence lift; standalone executions keep their original full-file hashes."}

def rejection_controls(raw, parent, modules, edges, candidates):
    """Corrupt each distinct source edge and ensure the complete inverse rejects."""
    spr, fg, ddr, pix = (modules[k] for k in ("sprite","fg","ddr","pixel"))
    cases=[]
    # Use actual guarded replacement blocks, rather than invented fixture proxies.
    for family,rel,ops,spelling in [
      ("sprite-bank-ABI","rtl/fg_vram.sv",edges["sprite"]["files"]["rtl/fg_vram.sv"]["edits"],"b64"),
      ("sprite-consumer","rtl/BT.sv",edges["sprite"]["files"]["rtl/BT.sv"]["edits"],"b64"),
      ("sprite-Q17","rtl/spr_vram.sv",edges["sprite"]["syntax_edits"],"b64"),
      ("FG-local-control","rtl/fg_vram.sv",edges["fg"]["edits"],"text"),
      ("DDR-local-flag","rtl/ddram.sv",edges["ddr"]["edits"],"oldnew"),
      ("pixel-priority","rtl/BT.sv",edges["pixel"]["edits"],"oldnew")]:
        for index,op in enumerate(ops[:2]):
            if spelling=="text":
                new,old=op["after"].encode("latin1"),op["before"].encode("latin1")
            else:
                new,old=(base64.b64decode(op[k],validate=True) for k in
                         (("after_b64","before_b64") if spelling=="b64" else ("new","old")))
            require(new and raw[rel].count(new)>=1, "Negative edge anchor absent: "+family)
            mutant=dict(raw);mutant[rel]=mutant[rel].replace(new,old,1)
            cases.append((family+"-removed-"+str(index),mutant))
    for rel in CHANGED:
        mutant=dict(raw);mutant[rel]+=b"\n// foreign unrelated source mutation\n"
        cases.append(("unrelated-"+rel,mutant))
    swapped=dict(raw);swapped["rtl/fg_vram.sv"]=raw["rtl/BT.sv"]
    cases.append(("foreign-file-identity",swapped))
    missing=dict(raw);del missing["rtl/spr_vram.sv"]
    cases.append(("missing-Q17-source",missing))
    controls=[]
    for name,mutant in cases:
        rejected=False
        try:
            compose_sources(mutant,parent,modules,edges,candidates)
        except (AssertionError,ValueError,KeyError):
            rejected=True
        require(rejected,"Source corruption control accepted: "+name)
        controls.append({"case":name,"rejected":True})
    require(len(controls)==18,"All18 actual source corruption controls required")
    return controls

def render_fg_inputs(q, preparer, parent, candidate, meta, profile, evidence):
    """Reproduce the frozen worker's preparation entirely in memory."""
    generated={}
    for name,expected in q.BOUND.items():
        path=(q.ROOT if name.startswith("tests/") else q.BASE)/name
        generated[Path(name).name]=evidence.file(path,expected)
    generated["fg_vram.sv"]=candidate
    reference=parent.decode("latin1")
    names=re.findall(r"^module\s+(\w+)",reference,re.M)
    for module in sorted(names,key=len,reverse=True):
        reference=re.sub(r"\b"+re.escape(module)+r"\b",module+"_REFERENCE",reference)
    generated["reference-fg_vram.sv"]=reference.encode("latin1")
    vendor=evidence.file(q.VENDOR,q.VENDOR_SHA)
    primitive=re.search(rb"(?m)^module lcell \(in, out\);\r?\n.*?^endmodule",vendor,re.S)[0]
    require(sha(primitive)==q.PRIMITIVE_SHA,"Actual Intel LCELL module changed")
    generated["intel_lcell.v"]=b"\x60timescale 1ps/1ps\n"+primitive+b"\n"
    original=evidence.file(q.TB,q.TB_SHA)
    tb=q.canonical(original).decode("latin1")
    additions=q.extra_assertions()
    require(tb.count("  initial begin\n")==1,"Original full FG fixture insertion changed")
    tb=tb.replace("  initial begin\n",additions+"  initial begin\n",1)
    marker='    $display("PASS serial chunk complete pins/state:'
    require(tb.count(marker)==1,"Original full FG fixture report changed")
    report='    $display("PASS FG v20 controls: checks=%0d",fg_v20_control_checks);\n'
    if profile=="four-state":
        report+='    assert(fg_local_controls_fourstate_tb.done) else $fatal(1,"FG function proof did not finish");\n'
    tb=tb.replace(marker,report+marker,1)
    require(tb.replace(additions,"",1).replace(report,"",1)==q.canonical(original).decode("latin1"),
            "Original full FG assertion/stimulus inverse changed")
    generated["item4_foreground_equivalence_tb.sv"]=tb.encode("latin1")
    template_path=ROOT/"tests/graphics/bt_fg_v20_control_functions_tb.sv"
    template=evidence.file(template_path,meta["function_template"]["sha256"])
    functions,function_hashes=q.extract_functions(candidate)
    template=q.canonical(template).decode("latin1")
    require(template.count("// __ACTUAL_FUNCTIONS__")==1,"Actual function insertion anchor changed")
    generated["fg_local_controls_fourstate_tb.sv"]=template.replace("// __ACTUAL_FUNCTIONS__",functions,1).encode("latin1")
    adapters={}
    if profile=="four-state":
        order=load(q.ORDER,q.ORDER_SHA,"FG_declaration_order",evidence)
        for name in ("fg_vram.sv","reference-fg_vram.sv"):
            raw=generated[name];canonical=q.canonical(raw)
            adapted,details=order.declaration_order(canonical,q.ORDER_NAMES)
            adapters[name]={"raw_sha256":sha(raw),"canonical_sha256":sha(canonical),
                            "newline_edge":"CRLF to LF",**details}
            generated[name]=adapted
        adapted,details=order.declaration_order(generated["item4_foreground_equivalence_tb.sv"],("DRAW_ADDR",))
        adapters["item4_foreground_equivalence_tb.sv"]=details
        generated["item4_foreground_equivalence_tb.sv"]=adapted
    require(meta["declaration_order_adapters"]==adapters,"Compiler-only declaration adapters changed")
    require(meta["oracle_namespace_modules"]==names and meta["function_body_sha256"]==function_hashes,
            "Actual original module namespace or function body changed")
    require(meta["assertion_additions"]==additions and meta["report_addition"]==report,
            "Actual additive assertions/report changed")
    require(meta["original_fixture_canonical_inverse"] is True,"Original fixture inverse is mandatory")
    return generated

def fg_commands(q, output, profile):
    inputs=output/"inputs"
    if profile=="native":
        result=[]
        for label,top,files in [
         ("fg","item4_foreground_equivalence_tb",
          ["fg_vram.sv","reference-fg_vram.sv","ram_models.sv","intel_lcell.v","item4_foreground_equivalence_tb.sv"]),
         ("fg-ddr","foreground_ddr_tb",
          ["fg_vram.sv","ddram.sv","bt_fg_ddr_clear.sv","ram_models.sv","intel_lcell.v","foreground_ddr_tb.sv"])]:
            target=output/label
            result.append(["C:/Windows/System32/wsl.exe","-d","Ubuntu","--cd",str(inputs),"--exec","verilator",
             "--binary","--assert","--timing","-j","4","--threads","1","--x-initial","unique","--x-assign","unique",
             "--top-module",top,"--Mdir",q.wsl(target/"obj"),"-Wno-fatal",*files])
            result.append(["C:/Windows/System32/wsl.exe","-d","Ubuntu","--cd",str(inputs),"--exec",
                           q.wsl(target/"obj"/("V"+top))])
        return result
    tool=Path("D:/q17/modelsim_ase/win32aloem");work=output/"work"
    names=["fg_vram.sv","reference-fg_vram.sv","ram_models.sv","intel_lcell.v",
           "item4_foreground_equivalence_tb.sv","fg_local_controls_fourstate_tb.sv"]
    return [[str(tool/"vlib.exe"),str(work)],
     [str(tool/"vlog.exe"),"-sv","-work",str(work),*[str(inputs/n) for n in names]],
     [str(tool/"vsim.exe"),"-c","-assertdebug","-onfinish","stop","-lib",str(work),
      "item4_foreground_equivalence_tb","fg_local_controls_fourstate_tb","-do","run -all; quit -code 0"]]

def one_marker(text, pattern, expected):
    values=re.findall(pattern,text)
    require(len(values)==1,"Exactly one complete actual coverage marker required: "+pattern)
    actual=tuple(map(int,values[0])) if isinstance(values[0],tuple) else (int(values[0]),)
    require(actual==expected,"Actual coverage marker changed: "+pattern)

def bind_fg(evidence, modules, edge):
    q=modules["fg_qualifier"];preparer=modules["fg"]
    aggregate=pinned_json("fg_proof",evidence)
    require(aggregate["schema"]=="bt-v20-fg-local-controls-qualification-v1" and aggregate["status"]=="PASS",
            "Both decisive current FG profiles required")
    require(aggregate["case_equality_exclusions"]==0 and aggregate["collision_masks_added"]==0,
            "No FG comparison exclusions accepted")
    parent=evidence.record(aggregate["parent"]);candidate=evidence.record(aggregate["candidate"])
    require(sha(parent)==preparer.PARENT_SHA,"Immutable v20 FG parent changed")
    require(preparer.forward(parent,edge["edits"])==candidate
            and preparer.reverse(candidate,edge["edits"])==parent,"Standalone full FG edge changed")
    proof=q.source_proof(preparer,parent,candidate,edge["edits"])
    bind_record_tree(aggregate,evidence)
    profiles={}
    for profile,bound in aggregate["proofs"].items():
        require(profile in ("native","four-state"),"Foreign FG profile")
        rec=evidence.json(bound["receipt"]["path"],bound["receipt"]["sha256"])
        meta=evidence.json(bound["preparation"]["path"],bound["preparation"]["sha256"])
        require(rec["schema"]=="bt-v20-fg-local-controls-current-parent-replay-v1"
                and rec["status"]=="PASS" and rec["profile"]==profile,"Actual FG execution failed")
        require(meta["schema"]=="bt-v20-fg-local-controls-inputs-v1" and meta["profile"]==profile,"FG compiler preparation changed")
        require(meta["source_proof"]==proof,"Regenerated complete FG source induction changed")
        require(meta["case_equality_exclusions"]==0 and meta["collision_masks_added"]==0
                and meta["timing_or_hardware_claim"] is False and meta["intel_ram_claim"] is False,
                "Uncovered FG claim or exclusion")
        q.verify_frozen(meta)
        bind_record_tree(meta,evidence)
        evidence.ingest(meta["executed_helpers"]);evidence.ingest(meta["compiled_inputs"])
        generated=render_fg_inputs(q,preparer,parent,candidate,meta,profile,evidence)
        expected={Path(path).name:digest for path,digest in meta["compiled_inputs"].items()}
        require(len(expected)==len(meta["compiled_inputs"]) and expected=={n:sha(v) for n,v in generated.items()},
                "All original complete FG compiler inputs must regenerate exactly")
        for name,data in generated.items():
            path=Path(bound["receipt"]["path"]).parent/"inputs"/name
            require(evidence.file(path)==data,"Actual FG compiled input differs from regenerated scope")
        output=Path(bound["receipt"]["path"]).parent
        commands=fg_commands(q,output,profile)
        require(len(rec["records"])==len(commands),"All original compiler and simulator steps required")
        for step,(entry,expected_command) in enumerate(zip(rec["records"],commands)):
            require(entry["command"]==expected_command and entry["exit_code"]==0,"Actual FG command/exit changed")
            data=evidence.record(entry["log"])
            text=data.decode("utf8",errors="replace")
            if (profile=="native" and step in (1,3)) or (profile=="four-state" and step==2):
                require(not q.failure_text(text),"Actual FG runtime assertion/error")
            else:
                # Verilator can print -Wno-fatal in a successful compiler log;
                # the original worker applies failure_text only to run logs.
                # Keep compiler errors separate from simulator assertions.
                require(not re.search(r"(?mi)^\s*(?:%Error(?:-[A-Z0-9_-]+)?:|\*\*\s+(?:Fatal|Error)\s*:)|^.+:\d+(?::\d+)?:\s*(?:fatal\s+)?error:",text),
                        "Actual FG compiler error")
        log=output/("fg/run.log" if profile=="native" else "run.log")
        text=evidence.file(log).decode("utf8",errors="replace")
        one_marker(text,r"PASS serial chunk complete pins/state: state_edges=(\d+) bank_edge_checks=(\d+)",(1263909,10111272))
        one_marker(text,r"PASS FG v20 controls: checks=(\d+)",(1262137,))
        require("restart_collisions=8 abort_collisions=8 reset_collects=2" in text
                and "PASS item4 RMT/control corners:" in text,"Original FG collision/transaction assertions missing")
        coverage={**FG_COUNTS,**(FG_NATIVE if profile=="native" else FG_FOUR)}
        if profile=="four-state":
            one_marker(text,r"PASS FG actual control functions: raw_xz=(\d+) position_xz=(\d+) control_xz=(\d+) coercion_negative=(\d+)",
                       (1024,4194304,65536,1))
        else:
            dtext=evidence.file(output/"fg-ddr/run.log").decode("utf8",errors="replace")
            require("PASS shipping DDR controller: 196608 cold-clear writes during reset, 128 masked writes, 512 round-trip copy bytes, cache reads and command backpressure" in dtext
                    and not q.failure_text(dtext),"Original shipping foreground DDR integration failed")
            for label,top in (("fg","item4_foreground_equivalence_tb"),("fg-ddr","foreground_ddr_tb")):
                # This is a new raw retention observation; old receipt/log hashes
                # continue to establish the actual compilation/execution record.
                evidence.file(output/label/"obj"/("V"+top))
        require(rec["coverage"]==coverage and bound["coverage"]==coverage,"Actual FG exact parsed coverage changed")
        require(rec["preparation"]==bound["preparation"] and rec["source_proof"]==bound["source_proof"],
                "Executed FG source/preparation pointers changed")
        profiles[profile]={"receipt":bound["receipt"],"preparation":bound["preparation"],
                           "coverage":coverage,"all_compiler_inputs_regenerated":True}
    require(set(profiles)=={"native","four-state"},"Both FG profiles mandatory")
    return {"standalone_parent_sha256":sha(parent),"standalone_candidate_sha256":sha(candidate),
            "profiles":profiles,"combined_source_relation":"Disjoint same-D control edge lifted through actual raw bank-data ABI inverse.",
            "old_assertions_or_stimulus_removed":0,"case_equality_exclusions":0,"new_intel_storage_claim":False}

def bind_ddr(evidence, q):
    path=PINS["ddr_proof"][0]
    rec=pinned_json("ddr_proof",evidence)
    result=q.verify_composition_receipt(path)
    require(result["status"]=="PASS_SCOPED_DDR_DIN_LOCAL_FLAGS","Full activated/default DDR proof required")
    for name,digest in rec["compiled_inputs"].items():
        evidence.file(path.parent/name,digest)
    for name,expected in [
      ("executed_qualifier.py",PINS["ddr_qualifier"][1]),
      ("executed_preparer.py",PINS["ddr_preparer"][1]),
      ("parent_raw.sv",rec["parent_sha256"]),("candidate_raw.sv",rec["candidate_sha256"])]:
        evidence.file(path.parent/name,expected)
    bind_record_tree(rec,evidence)
    for job in list(rec["jobs"].values())+[rec["tool_versions"]]:
        for step in ("compile","run","verilator_version","iverilog_version"):
            if step in job:
                entry=job[step]
                require(entry["exit_code"]==0,"Actual DDR compiler/simulator failed")
                evidence.file(entry["log"],entry["log_sha256"])
        if "executable" in job:
            evidence.file(job["executable"],job["executable_sha256"])
    return result

def bind_native_parent(evidence, parent_receipt, parent_snapshot):
    rec=pinned_json("parent_native",evidence)
    require(rec["schema"]=="bt-current-v20-native128-lcell-raster-qualification-v1"
            and rec["status"]=="PASS_ACTUAL_NATIVE128_AND_24_RASTERS","Actual v20 native128 required")
    require(rec["selected_snapshot_sha256"]==PINS["parent_snapshot"][1]
            and rec["functional_composition_sha256"]==PINS["parent_receipt"][1],"Native parent source proof changed")
    evidence.file(rec["selected_snapshot"],rec["selected_snapshot_sha256"])
    evidence.file(rec["functional_composition"],rec["functional_composition_sha256"])
    require(rec["native_system_top_reset_partition_compiled"] is False
            and rec["mapped_timing_RBF_hardware_MAME_claim"] is False
            and rec["old_native128_receipts_or_rasters_modified"] is False,"Native scope incorrectly broadened")
    require(rec["requested_frames"]==128 and rec["actual_native_exit_code"]==0
            and rec["actual_complete_cycles"]==172308065
            and rec["actual_logged_phase_frames_checked"]==[1,128],"Complete actual native execution changed")
    # The journal checks assertions on every relevant edge, while its retained
    # phase summaries are emitted at frames 1 and 128. Do not invent 128 logs.
    require(rec["actual_last_frame_DDR_phase"]=={
      "frame":128,"captures":2573046,"cpu":279286,"sprite":0,"fg0":1146880,"fg1":1146880,
      "launch_age_checks":2573046,"ext_reloads":53513164,"fs_reloads":660076,"ba_reloads":1014,
      "buf_reloads":660076,"min_ext":5,"min_fs":5,"min_ba":5,"min_buf":3,
      "probe_checks":171038303,"conservative_false":2486591},"Actual preserved final native phase counters changed")
    require(rec["selected_full144_source_inventory_checked"] is True
            and rec["unchanged_per_capture_assertions_enabled_throughout_128_frames"] is True,
            "Actual native source/phase assertions missing")
    require(rec["failures"]==[] and rec["comparison_count"]==24
            and len(rec["actual_byte_comparisons"])==24,"All24 actual raster comparisons required")
    ledger=rec["retained_inputs_logs_and_executable"]
    require(isinstance(ledger,dict) and len(ledger)==47,"All47 retained actual native artifacts required")
    evidence.ingest(ledger)
    evidence.file(BUILD/"native_lcell_link_v20_v1/qualify_128.py",rec["creator_sha256"])
    evidence.file(ROOT/"tests/graphics/native_lcell_run.py",rec["executed_shim_sha256"])
    actual=evidence.json(rec["native_receipt"],rec["native_receipt_sha256"])
    evidence.file(rec["previous_comparison_receipt"],rec["previous_comparison_receipt_sha256"])
    for row in rec["actual_byte_comparisons"]:
        require(row["byte_equal"] is True,"Actual raster comparison failed")
        a=evidence.file(row["reference_path"],row["reference_sha256"])
        b=evidence.file(row["previous_native_path"],row["previous_native_sha256"])
        c=evidence.file(row["current_path"],row["current_sha256"])
        require(a==b==c and len(c)==row["bytes"],"Retained actual raster bytes changed")
    # The sidecar is immutable and distinguishes actual board compiler inputs
    # from the source inventory and separately proven production reset partition.
    return {"receipt":str(PINS["parent_native"][0]),"sha256":PINS["parent_native"][1],
            "requested_frames":128,"actual_complete_cycles":172308065,"actual_raw_raster_comparisons":24,
            "retained_artifacts":47,"actual_input_journal_sha256":rec["actual_input_journal_sha256"],
            "reported_phase_frames":[1,128],"actual_last_frame_DDR_phase":rec["actual_last_frame_DDR_phase"],
            "compiled_scope":rec["scope"],"production_top_reset_partition_compiled":False,
            "v22_replay_claim":False}

def verify_claim(candidate, expected):
    require(candidate==expected,"The exact current-input composition receipt did not reproduce")

def claim_controls(receipt):
    changes=[("wrong-schema","schema","foreign"),
             ("new-native-retag","new_whole_board_native_run",True),
             ("fake-physical-retention","mapped_replication_proven",True),
             ("fake-timing","core_timing_accepted",True),
             ("fake-RBF","eligible_for_RBF",True),
             ("lost-source-inventory","all144_source_inventory_entries_verified",False)]
    output=[]
    for name,key,value in changes:
        mutant=copy.deepcopy(receipt);mutant[key]=value
        rejected=False
        try:verify_claim(mutant,receipt)
        except ValueError:rejected=True
        require(rejected,"Composition claim corruption accepted")
        output.append({"case":name,"rejected":True})
    return output

def bind_current(source_root):
    source_root=Path(source_root).resolve()
    require(source_root==SOURCE_ROOT.resolve(),"Only the exact selected full144 v22 source root is accepted")
    evidence=Evidence()
    for path,digest in PINS.values():
        evidence.file(path,digest)
    parent_helper=pinned_module("parent_helper",evidence)
    parent_receipt=pinned_json("parent_receipt",evidence)
    parent_validation=parent_helper.verify_composition_receipt(PINS["parent_receipt"][0])
    require(parent_validation["status"]==STATUS,"Immutable v20 functional graph failed")
    evidence.ingest(parent_receipt["bound_evidence_files"])
    immutable_oracles=copy.deepcopy(parent_receipt["immutable_git_oracles"])
    parent_snapshot=pinned_json("parent_snapshot",evidence)
    snapshot=pinned_json("snapshot",evidence)
    require(len(snapshot["sources"])==144 and set(snapshot["sources"])==set(parent_snapshot["sources"]),
            "Exact144 source inventory and keys required")
    parent_root=Path(parent_receipt["source_root"])
    raw={};parent={}
    for rel,digest in snapshot["sources"].items():
        value=evidence.file(source_root/rel,digest)
        old=evidence.file(parent_root/rel,parent_snapshot["sources"][rel])
        if rel in CHANGED:
            raw[rel]=value;parent[rel]=old
        else:
            require(value==old,"An unqualified support/source/clock/settings input changed: "+rel)
    require({rel for rel in snapshot["sources"] if snapshot["sources"][rel]!=parent_snapshot["sources"][rel]}
            ==set(CHANGED),"Only the four exact scoped source files may differ from v20")
    modules={"sprite":pinned_module("sprite_preparer",evidence),
             "fg":pinned_module("fg_preparer",evidence),
             "fg_qualifier":pinned_module("fg_qualifier",evidence),
             "ddr":pinned_module("ddr_preparer",evidence),
             "ddr_qualifier":pinned_module("ddr_qualifier",evidence),
             "pixel":pinned_module("pixel_preparer",evidence),
             "pixel_verifier":pinned_module("pixel_verifier",evidence)}
    edges={k:pinned_json(k+"_edge",evidence) for k in ("sprite","fg","ddr","pixel")}
    sprite_parents,sprite_candidates,sprite_manifest=modules["sprite"].verify_edge(PINS["sprite_edge"][0].parent)
    require(sprite_manifest==edges["sprite"],"Exact Q17 source manifest changed")
    for rel,data in sprite_parents.items():
        require(data==parent[rel],"Sprite source parent differs from selected immutable v20")
    composition=compose_sources(raw,parent,modules,edges,sprite_candidates)
    source_controls=rejection_controls(raw,parent,modules,edges,sprite_candidates)
    sprite_qualifier=pinned_module("sprite_qualifier",evidence)
    sprite_validation=sprite_qualifier.verify_composition_receipt(PINS["sprite_proof"][0])
    require(sprite_validation["physical_timing_or_retention_accepted"] is False,"Sprite physical qualification was not run")
    evidence.ingest(sprite_validation["bound_evidence_files"])
    fg_validation=bind_fg(evidence,modules,edges["fg"])
    ddr_validation=bind_ddr(evidence,modules["ddr_qualifier"])
    pixel_validation=modules["pixel_verifier"].verify_proof(PINS["pixel_edge"][0].parent,PINS["pixel_proof"][0])
    evidence.ingest(pixel_validation["files"])
    # The verifier separately pins and regenerates its exact qualifier inputs.
    pixel_verifier=modules["pixel_verifier"]
    evidence.file(pixel_verifier.QUALIFIER,
                  json.loads(pinned("pixel_proof",evidence))["qualifier_sha256"])
    native_validation=bind_native_parent(evidence,parent_receipt,parent_snapshot)
    receipt={"schema":SCHEMA,"status":STATUS,"helper_sha256":sha(Path(__file__).read_bytes()),
      "source_root":str(source_root),"snapshot":str(SNAPSHOT),"snapshot_sha256":PINS["snapshot"][1],
      "all144_source_inventory_entries_verified":True,"only_changed_sources":list(CHANGED),
      "unchanged_sources":140,"parent_v20_receipt":str(PINS["parent_receipt"][0]),
      "parent_v20_receipt_sha256":PINS["parent_receipt"][1],
      "parent_validation":parent_validation,"raw_source_composition":composition,
      "scoped_proofs":{"sprite_registered_bank_q_and_Q17":sprite_validation,
                       "foreground_local_controls":fg_validation,"DDR_local_DIN_flags":ddr_validation,
                       "pixel_parallel_priority":pixel_validation},
      "actual_parent_v20_native128":native_validation,
      "new_source_corruption_controls":source_controls,
      "case_equality_exclusions":0,"collision_masks_added":0,
      "new_compiler_or_simulator_run":False,"new_whole_board_native_run":False,
      "mapped_replication_proven":False,"core_timing_accepted":False,"timing_accepted":False,
      "eligible_for_RBF":False,"root_RTL_SDC_or_old_evidence_modified":False,
      "limits":["Standalone tests retain their actual full-file/compiler/log hashes; the actual combined sources are related by guarded raw inverses in both disjoint transform orders.",
                "The new eight registered sprite mirrors have actual Intel storage/OLD_DATA/startup/X/Z coverage; projected RAM cost does not establish fitted replication or placement.",
                "Actual foreground physical input pins are covered by the separate unchanged consumer bench; canonical full-FG tests do not add an Intel RAM collision claim.",
                "The v20 native128 receipt applies to its recorded game-board/compiler subset; production top reset partition, exact v22 native replay, all-corner timing, physical pads, RBF and hardware remain separate gates."],
      "immutable_git_oracles":immutable_oracles}
    receipt["new_claim_corruption_controls"]=claim_controls(receipt)
    receipt["bound_evidence_files"]=dict(evidence.files)
    evidence.recheck()
    return json_normal(receipt),evidence

def verify_composition_receipt(path):
    path=Path(path).resolve()
    result=json.loads(path.read_bytes())
    require(result["schema"]==SCHEMA and result["status"]==STATUS,"Wrong current-input receipt")
    require(result["helper_sha256"]==sha(Path(__file__).read_bytes()),"Current binder changed")
    expected,evidence=bind_current(result["source_root"])
    helper=result["executed_helper"]
    require(helper["sha256"]==result["helper_sha256"],"Executed binder preservation changed")
    evidence.record(helper)
    expected["executed_helper"]=helper
    expected["bound_evidence_files"]=dict(evidence.files)
    verify_claim(result,expected)
    evidence.recheck()
    return {"status":STATUS,"receipt":str(path),"receipt_sha256":sha(path.read_bytes()),
            "sources":144,"unchanged_sources":140,"verified_evidence_files":len(evidence.files),
            "verified_immutable_git_oracles":len(result["immutable_git_oracles"]),
            "new_source_corruption_controls":18,"new_claim_corruption_controls":6,
            "parent_native_frames":128,"new_v22_replay_or_timing_claim":False}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root",type=Path,default=SOURCE_ROOT)
    parser.add_argument("--output",type=Path)
    parser.add_argument("--verify",type=Path)
    args=parser.parse_args()
    if args.verify:
        print(json.dumps(verify_composition_receipt(args.verify)));return
    require(args.output is not None,"An exclusive new output directory is required")
    output=args.output.resolve()
    require(not output.exists(),"Preserve existing evidence; choose a new output")
    result,evidence=bind_current(args.source_root)
    output.mkdir(parents=True)
    helper=output/"executed_helper.py"
    helper.write_bytes(Path(__file__).read_bytes())
    evidence.file(helper,result["helper_sha256"])
    result["executed_helper"]={"path":str(helper),"sha256":result["helper_sha256"],"bytes":helper.stat().st_size}
    result["bound_evidence_files"]=dict(evidence.files)
    receipt=output/"receipt.json"
    receipt.write_text(json.dumps(result,indent=2)+"\n")
    verification=verify_composition_receipt(receipt)
    (output/"verification.json").write_text(json.dumps(verification,indent=2)+"\n")
    print(json.dumps(verification))

if __name__=="__main__":
    main()

