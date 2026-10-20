# Standard MRA ROM loading

`releases/Battletoads.mra` uses the unmodified MAME 0.289 `btoads.zip`.
Install it in `_Arcade/`, the matching Battletoads RBF in `_Arcade/cores/`,
and the ZIP in `games/mame/`.

The previous loader required three independent downloads at indices 0, 1
and 2. Each falling edge set one `load_done` bit, and all three bits were
required to release reset. A standard index-0 MRA could never complete
that contract. The Z80 game program also came from `rtl/bt.mif` at synthesis
time rather than from the archive.

The new index-0 stream has this layout:

| Stream range | Destination | ZIP members |
| --- | --- | --- |
| `000000-7fffff` | Main program in DDR | `btc0-p0.u120`, `btc0-p1.u121`, 32-bit word interleave |
| `800000-9fffff` | Samples in SDRAM | `btc0-s.u109` |
| `a00000-a07fff` | Z80 program RAM | `bt.u102` |

The MRA maps `0021`/`2100` reproduce MAME's little-endian `ROM_LOAD32_WORD`.
The loader captures addresses/data and waits for memory acceptance and
completion. It releases reset after a complete sequential `0xa08000`-byte
stream, rejects short/discontinuous loads, and invalidates readiness on reload.
Index 254 updates the game's DIP switches without touching ROM readiness.

The transport regression also exposed an existing DDR read-response bug.
The controller consumed `DDRAM_DOUT_READY` only inside `!DDRAM_BUSY`, losing
returned data during command backpressure and hanging a CPU cache fill.
Read responses now advance independently of command acceptance.

Validation used the supplied ZIP and installed MAME 0.289. All four ROMs
match MAME's sizes, CRCs and SHA1s; every MRA payload byte matches an independent
MAME layout. Payload SHA256:
`47d6b2374d248966c2dfb95870b4862b29ddb2226ec1421e10d4b5158ff6deac`.

Verilator passes the complete payload through the real DDR/SDRAM controllers:
8 MiB of DDR writes, 2 MiB of SDRAM pin writes and 32 KiB of Z80 writes.
CPU cache and reset-vector reads match, including responses under command
backpressure. DIP/foreign indices, reloads and incomplete loads also pass.
The Intel DDR output-clock primitive alone has a simulation substitute.

The timing-closed release at commit
`4c0ba30d38fe08cb1dd1835ff44098512b815a8c` includes this loader and was built
on 11 October 2026. Its full native compile passed all eight timing corners
at 80/160 MHz. Hardware boot and complete gameplay remain unverified;
see `FUNCTIONAL_AUDIT_20261011.md` for the ongoing functionality audit.

Reference: [MAME 0.289 Battletoads driver](https://github.com/mamedev/mame/blob/mame0289/src/mame/rare/btoads.cpp).
