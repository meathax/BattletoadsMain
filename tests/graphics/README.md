`run.py` exercises shipping graphics with CPU bus transactions. The separate
native harness executes the production CPUs, graphics and DDR controller.

They include palette raw-byte readback and six-bit DAC output, pen masks,
graphics-register byte lanes, and shared foreground/sprite shift-register copies
between both pages. The row tests cover all sixteen palette banks with flip and
shadow. `capture_mame.lua` also exports unique graphics-register configurations
observed during gameplay. Pass that capture's `configurations.txt` with
`--configurations <path>` to exercise those configurations against MAME's exact
row renderer. Add `--sprite-sources <sprite_sources.bin>` to use a captured
gameplay source row instead of varied synthetic pixels. This is component and
configuration coverage; it does not replay CPU execution or native raster timing.

Directed foreground tests cover independent DDR-backed upper halves, unaligned
copies across logical rows, delayed DDR responses, exact ordinary address maps,
and preservation of the video serial stream during CPU shift-register copies.
Off-screen sprite writes and CPU shift writes share the same backing store and
wait for DDR completion. The separate foreground-clear test verifies
initialization before CPU release and exclusion of the on-chip visible columns.

Run `python tests/graphics/run.py --mame-source <btoads.cpp>` with the pinned
MAME 0.289 source. The test builds through the configured safe Verilator wrapper
in a unique R:/Verilator workspace, with assertions and strict X flags.
The reference row renderer is extracted verbatim, with its class qualifier
adapted. The UCRT compiler/linker and C++17 runtime settings are explicitly pinned.
The sources and generated oracle are frozen in that workspace before compiling.
Private logs, hashes and receipts are retained in `build/after/` or
`build/after-captured/` when captured sprite sources are selected.

`--baseline` checks the original graphics revision, pinned to
`ace68a15e944c2090651080a59502ae47ae31b44`. Baseline declarations make procedural
output variable types explicit for strict SystemVerilog; the debug grid's
combinational assignment uses blocking syntax. Rendering behavior is retained.

`capture.py --mame <mame.exe> --rompath <directory>` audits the ROM set and
records a fresh, isolated headless gameplay reference with native snapshots.
It is diagnostic reference coverage, not a paired simulator comparison.

`synthesize.py` checks an isolated source snapshot with Quartus analysis,
fitting and timing. It does not assemble or generate an RBF. Each completed
check retains its source manifest, raw log and reports under `evidence/`.

After a successful fit, `timing_audit.tcl` reports setup, hold, recovery, removal
and pulse width at all available operating conditions, plus unconstrained paths
and constraint checks. Review all of those reports before assembling an RBF.

`qualify_raster.py` uses the real video I/O, shipping graphics and actual MiSTer
mixer enable. It compares the consumer's pre-edge RGB and blanking against the
exact MAME scanline function. Synthetic patterns cover all modes, pages and
pixel phases. `--capture <capture-directory>` replays recorded VRAM/DAC/I/O and
display-write positions, then compares directly with the completed MAME PNGs.
The capture runner records those writes alongside all 1,800 input frames.

```powershell
python tests/graphics/qualify_raster.py
python tests/graphics/qualify_raster.py --capture <MAME-capture-directory>
python tests/graphics/qualify_scanline.py
python tests/graphics/qualify_memory.py
python tests/graphics/qualify_carry.py
python tests/graphics/qualify_vram_write.py
python tests/graphics/qualify_foreground_ddr.py
python tests/graphics/qualify_ddram_cache.py
python tests/graphics/native_run.py --frames 1800 --input-journal <MAME-inputs.txt>
python tests/graphics/synthesize.py
python tests/graphics/timing_run.py <fitted-snapshot-directory>
python tests/graphics/verify_timing.py <fitted-snapshot-directory>
```

Run analysis/synthesis and fit after production RTL changes. The timing gate
requires all eight operating corners, setup/hold/recovery/removal/pulse-width
acceptance, current source hashes and permanent constraints. Extra-SDC
experiments remain provisional. `assemble.py <fitted-snapshot-directory>` is
reserved for an explicitly requested RBF after that gate passes; its receipt
binds the RBF and SOF hashes to the accepted source and timing results.
