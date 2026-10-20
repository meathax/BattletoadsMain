"""Losslessly split the canonical BSMT firmware into M10K geometry slices."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
WIDTHS = (5, 5, 5, 1)


def read_mif(path: Path, width: int) -> list[int]:
    text = re.sub(r"--[^\n]*|%.*?%", "", path.read_text(encoding="ascii"), flags=re.S)
    for name, expected in (("WIDTH", str(width)), ("DEPTH", "4096"),
                           ("ADDRESS_RADIX", "HEX"), ("DATA_RADIX", "HEX")):
        found = re.search(rf"\b{name}\s*=\s*([^;\s]+)\s*;", text, re.I)
        if not found or found.group(1).upper() != expected:
            raise ValueError(f"{path}: expected {name}={expected}")
    body = re.search(r"\bCONTENT\s+BEGIN\s*(.*?)\bEND\s*;", text, re.S | re.I)
    if not body:
        raise ValueError(f"{path}: missing CONTENT BEGIN/END")
    words: list[int | None] = [None] * 4096
    for line in body.group(1).splitlines():
        if not line.strip():
            continue
        entry = re.fullmatch(r"\s*([\da-f]+)\s*:\s*([\da-f]+)\s*;\s*", line, re.I)
        if not entry:
            raise ValueError(f"{path}: invalid entry {line!r}")
        address, value = (int(item, 16) for item in entry.groups())
        if address >= 4096 or value >= 1 << width or words[address] is not None:
            raise ValueError(f"{path}: duplicate/out-of-range entry {line!r}")
        words[address] = value
    if any(word is None for word in words):
        raise ValueError(f"{path}: missing ROM words")
    return [int(word) for word in words]


def render_mif(words: list[int], width: int) -> str:
    digits = (width + 3) // 4
    return (f"WIDTH={width};\nDEPTH=4096;\nADDRESS_RADIX=HEX;\nDATA_RADIX=HEX;\n"
            "CONTENT BEGIN\n" +
            "".join(f"    {address:04X} : {word:0{digits}X};\n"
                    for address, word in enumerate(words)) + "END;\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify without rewriting slices")
    parser.add_argument("--write-hex", type=Path, help="Write canonical words for simulation")
    args = parser.parse_args()
    canonical = ROOT / "rtl/bsmt2000.mif"
    words = read_mif(canonical, 16)
    slices = []
    offset = 0
    for index, width in enumerate(WIDTHS):
        path = ROOT / f"rtl/bsmt2000_slice{index}.mif"
        values = [(word >> offset) & ((1 << width) - 1) for word in words]
        expected = render_mif(values, width)
        if args.check:
            if path.read_text(encoding="ascii") != expected:
                raise ValueError(f"{path}: stale generated slice")
        else:
            path.write_text(expected, encoding="ascii", newline="\n")
        slices.append(read_mif(path, width))
        offset += width
    for address, word in enumerate(words):
        reconstructed = sum(slices[index][address] << (index * 5) for index in range(4))
        if reconstructed != word:
            raise ValueError(f"ROM reconstruction differs at {address:03X}")
    if args.write_hex:
        args.write_hex.parent.mkdir(parents=True, exist_ok=True)
        args.write_hex.write_text("".join(f"{word:04X}\n" for word in words),
                                 encoding="ascii", newline="\n")
    print(f"PASS BSMT ROM slices: all 4096 words reconstruct exactly; "
          f"canonical SHA256={hashlib.sha256(canonical.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
