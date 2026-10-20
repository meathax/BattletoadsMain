"""Prepare one immutable-v23 DDR busy-cone edge; never edit production RTL."""
from pathlib import Path
import argparse
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "build/timing_closure_20261011/pixel_cpu_fg_v23_private-snapshot.json"
SNAPSHOT_SHA = "627f642c9490ce2ffeb532313e33e750a1b67997b2d99a46f3a2cc564d6f6e67"
PARENT_SHA = "80b5af022202c55070102c242c0f59cda409a83d71bce5079ea0b93e47ae3f6b"
RELATIVE = "rtl/ddram.sv"

OLD_READ = b'\twire read_busy_next = !read_clear && (read_busy || (rd && !old_rd && read_miss));\n'
NEW_READ = b'''\t// Local controls arrive before the request-address tag comparison.
\t(* keep = "true" *) wire read_hold_local = !read_clear && read_busy;
\t(* keep = "true" *) wire read_permit_local = !read_clear && rd && !old_rd;
\twire read_busy_next = read_hold_local || (read_permit_local && read_miss);
'''
OLD_BUSY = b'''\t(* keep = "true" *) wire read_start_busy = !read_clear && !old_rd && read_miss;
\talways @(posedge clk)
\t\tbusy_reg <= busy_local || (!rst && write_start) || (rd && read_start_busy);
'''
NEW_BUSY = b'''\twire read_start_busy = !read_clear && !old_rd && read_miss;
\t(* keep = "true" *) wire busy_without_new_read = busy_local || (!rst && write_start);
\talways @(posedge clk)
\t\tbusy_reg <= busy_without_new_read || (read_permit_local && read_miss);
'''
IO_HISTORY = b'\t(* preserve, dont_merge *) bit old_io_we_busy = 0;\n'
IO_LOCAL = b'''\t// The original procedural IO conditions accept only a known one. Preserve
\t// that four-state behavior while keeping the busy latch off the data enable.
\tfunction automatic bit BtDdrKnownOne(input logic value);
\t\tBtDdrKnownOne = value;
\tendfunction
\t(* keep = "true" *) wire io_write_finish_local = BtDdrKnownOne(!DDRAM_BUSY && state == 3'd5);
\t(* keep = "true" *) wire io_write_hold_local = io_write_busy && !io_write_finish_local;
\t(* keep = "true" *) wire io_write_permit_local = !old_io_we_busy && !io_write_finish_local;
\twire io_write_request_known = BtDdrKnownOne(|io_we);
\talways @(posedge clk) begin
\t\told_io_we_busy <= |io_we;
\t\tio_write_busy <= io_write_hold_local || (io_write_request_known && io_write_permit_local);
\tend

'''


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def pinned_parent():
    raw = SNAPSHOT.read_bytes()
    if sha(raw) != SNAPSHOT_SHA:
        raise ValueError("Immutable v23 inventory changed")
    snapshot = json.loads(raw)
    if len(snapshot["sources"]) != 144 or snapshot["sources"][RELATIVE] != PARENT_SHA:
        raise ValueError("Immutable v23 DDR scope changed")
    parent = (Path(snapshot["project"]).parent / RELATIVE).read_bytes()
    if sha(parent) != PARENT_SHA:
        raise ValueError("Immutable full parent DDR source changed")
    return parent


def operations(parent):
    if sha(parent) != PARENT_SHA:
        raise ValueError("Only the exact immutable full v23 DDR is supported")
    anchor = b'\talways @(posedge clk) begin\n\t\tbit old_io_rd, old_io_we;\n'
    declaration = b'\treg            io_write_busy = 0;\n'
    pairs = [(OLD_READ, NEW_READ), (OLD_BUSY, NEW_BUSY),
             (declaration, declaration + IO_HISTORY), (anchor, IO_LOCAL + anchor),
             (b'\t\t\tio_write_busy <= 1;\n', b''),
             (b'\t\t\t\t\tio_write_busy <= 0;\n', b'')]
    if parent.count(b"\n") != parent.count(b"\r\n"):
        raise ValueError("The pinned parent must retain its exact CRLF source profile")
    pairs = [(a.replace(b"\n", b"\r\n"), b.replace(b"\n", b"\r\n"))
             for a, b in pairs]
    return [{"old": a.decode(), "new": b.decode(), "offset": parent.index(a)}
            for a, b in pairs if parent.count(a) == 1]


def transform(parent):
    edits = operations(parent)
    if len(edits) != 6:
        raise ValueError("Exact six original source anchors are required")
    raw = parent
    for edit in edits:
        old, new = edit["old"].encode(), edit["new"].encode()
        if raw.count(old) != 1:
            raise ValueError("Source edit anchor changed")
        raw = raw.replace(old, new, 1)
    return raw, edits


def reverse(candidate, edits=None):
    parent = pinned_parent()
    expected = operations(parent)
    if edits is not None and edits != expected:
        raise ValueError("Declared source operations changed")
    # Reverse by offsets in the original source, so deletion edits remain strict.
    reconstructed = bytearray()
    cursor = 0
    for edit in sorted(expected, key=lambda e: e["offset"]):
        offset = edit["offset"]
        unchanged = parent[len(reconstructed):offset]
        if candidate[cursor:cursor + len(unchanged)] != unchanged:
            raise ValueError("Undeclared original byte changed")
        reconstructed.extend(unchanged)
        cursor += len(unchanged)
        new = edit["new"].encode()
        if candidate[cursor:cursor + len(new)] != new:
            raise ValueError("Declared replacement byte changed")
        cursor += len(new)
        reconstructed.extend(edit["old"].encode())
    tail = parent[len(reconstructed):]
    if candidate[cursor:] != tail:
        raise ValueError("Undeclared final source byte changed")
    reconstructed.extend(tail)
    if bytes(reconstructed) != parent:
        raise ValueError("Full raw parent inverse failed")
    return bytes(reconstructed)


def verify_source(candidate, edits=None):
    parent = reverse(candidate, edits)
    if transform(parent)[0] != candidate:
        raise ValueError("Full raw forward source edge failed")
    text = candidate.decode()
    if text.count("old_io_we_busy <= |io_we;") != 1 or text.count("io_write_busy <=") != 1:
        raise ValueError("Local history or busy driver changed")
    return {"status": "PASS_EXACT_SCOPED_SOURCE_EDGE", "parent_sha256": sha(parent),
            "candidate_sha256": sha(candidate), "whole_raw_inverse": True,
            "unchanged_original_IO_metadata_capture_and_history": True,
            "unchanged_reset_initialization_ports_state_and_data_writers": True,
            "read_algebra": "Distribute the original read-clear term and factor local controls before late read_miss.",
            "io_induction": "Both bit histories initialize zero and capture |io_we at every original edge. IO busy initializes zero and original writers assign only literals. Known-one coercion preserves procedural if/case acceptance; completion remains higher priority, including during rst.",
            "behavior_simulation": "UNRUN", "mapped_timing_hardware": "UNRUN"}


def verify_edge(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    raw = (directory / "candidate" / RELATIVE).read_bytes()
    if manifest["parent_sha256"] != PARENT_SHA or manifest["candidate_sha256"] != sha(raw):
        raise ValueError("Declared source hashes changed")
    return verify_source(raw, manifest["edits"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    directory = args.out.resolve()
    if directory.exists() or not directory.is_relative_to(ROOT / "build"):
        raise ValueError("Require a fresh private build directory")
    parent = pinned_parent()
    candidate, edits = transform(parent)
    proof = verify_source(candidate, edits)
    target = directory / "candidate" / RELATIVE
    target.parent.mkdir(parents=True)
    target.write_bytes(candidate)
    (directory / "parent_raw.sv").write_bytes(parent)
    manifest = {"schema": "bt-v23-ddr-busy-local-source-edge-v1", "status": "SOURCE_EDGE_PREPARED",
                "snapshot": str(SNAPSHOT), "snapshot_sha256": SNAPSHOT_SHA,
                "parent_sha256": PARENT_SHA, "candidate_sha256": sha(candidate),
                "preparer_sha256": sha(Path(__file__).read_bytes()), "edits": edits,
                "source_equivalence": proof, "clock_or_constraint_changes": 0,
                "request_data_or_response_cycles_added": 0}
    (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    verify_edge(directory)
    print(json.dumps({"candidate": str(target), "candidate_sha256": sha(candidate),
                      "manifest_sha256": sha((directory / "manifest.json").read_bytes()),
                      "preparer_sha256": manifest["preparer_sha256"]}))


if __name__ == "__main__":
    main()
