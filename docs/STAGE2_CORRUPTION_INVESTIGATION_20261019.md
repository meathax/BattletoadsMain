# Battletoads stage-2 corruption: root cause and fix plan

Updated 19 October 2026. **The RTL fix now passes the CPU component proof.** A
compressed release RBF build is queued from an isolated checkout; fresh all-corner
timing is still pending. No hardware test or remote write has been performed.

## Confirmed finding

**The latest released TMS34020 incorrectly clips `PIXBLT L,XY` instructions in
the snow stage. It writes background pixels outside the legal window, including
commands whose correct result is no writes at all.** This is a demonstrated CPU
rendering defect upstream of scanout. The stage-2 workload reproduces it without
requiring a missing DDR acknowledgement or sprite deadline overrun. No measured
lost transaction supports the suggestion that sprites “miss the bus”.

The complete, unmodified released CPU replayed **15,920 authentic snow-stage
background instructions** and produced **6,435 wrong pixels** against captured
MAME BG1 VRAM. Reconstruction using correct clipping matches the captured
reference with **zero differences**. Changing only clipping semantics predicts
the actual CPU output with **zero byte/pixel differences**. This connects a real
stage-2 workload, faulty helper/microcode, accepted CPU writes and persistent
VRAM corruption; it is more than a helper counterexample.

The scope is a **component reproduction**, not a clean full-game boot, paired
MAME_EXACT run, hardware capture or cycle-accurate board bus model. MAME stage
entry used a recorded diagnostic dispatcher write and MAME save; the CPU replay
resets before each captured instruction while preserving background memory.
The supplied photographs have not been recreated pixel for pixel and lack a
frame/state identity. This identifies a causal stage-2 corruption mechanism;
exclusive attribution of every photographed black gap remains a gameplay and
hardware acceptance check.

## Release identity and isolation

The user identifies the photographed build as the latest RBF. The latest local
release is `releases/Arcade-Battletoads_20261018.rbf`, 4,113,640 bytes, SHA-256
`91b8fae20526087619bb40579d7379d1cd6dd5a13d105293d171ce181dbaf553`.
This is user-reported device identity, not a readback.

Reproduction source is release commit
`423baf55bb60bb89499c61f350a02a54eeb17705`, exported separately to
`build/stage2_release_20261019/` (**R** below).
`R/release_source.json` inventories its original bytes. All 79 checked RTL,
top-level, project and constraint files remain identical. Concurrent working-tree
changes were neither used nor reverted.

Reference executable: `D:/Arcade/AI/mameexe/mame.exe`, MAME 0.289; launcher
receipts retain executable hashes and commands. The little-endian 8 MiB CPU ROM
has SHA-256 `d1ef483fbc8667e08a82e55023bf62df31daf39f6d5d644b863c085062293e6e`.
Its private diagnostic copy is `R/private/main.bin`; do not distribute it.
Synthetic test instructions modify only the driver's private in-memory ROM copy.

## Responsible logic

Released source is preserved under `R/rtl/TMS34020/`:

- `TMS34020_pkg.sv:639–676`: `XYCompareWin`, `XYWinOffset`, `WinAdjust`.
- `TMS34020_ID.sv:3548–3586`: class-51 XY blit setup and rejection.
- `TMS34020.sv:1266,1443–1444`: offset/dimension calculation and flag capture.

`WinAdjust` limits dimensions to the **whole window size**, independently of the
destination. The decoder checks whether the far corner is before the window
start, but fails to reject a rectangle wholly beyond its right/bottom edge.
An empty intersection can therefore become a nonempty write rectangle. Partial
intersections retain excessive dimensions. Separately, `XYWinOffset` uses unsigned
comparisons, mishandling negative coordinates; that verified helper defect is
not needed for the authentic positive-coordinate counterexample below.

Independent reference: local MAME 0.289 source
`D:/Arcade/AI/mame289/src/devices/cpu/tms34010/34010gfx.hxx:75–145`
(`apply_window`) and `:985–1000` (clipping and nonpositive-extent rejection).
For these positive-coordinate cases, correct clipping is:

```
near = max(destination, window_start)
far = min(destination + size, window_end + 1)
extent = far - near
reject all writes if either extent <= 0
```

Y source cropping uses CONVSP; X cropping uses pixel width. Subsequent rows retain
their source/destination pitches. Authentic snow inputs have CONTROL=00c1,
CONVSP=0018, CONVDP=0011, PSIZE=8, and field-0 signed-16 context (ST low bits 0030).

## Smallest authentic proof

At logical frame **7929**, opcode **0F20** at **FFE20220**, the snow program
submits the following register values:

| Register | Value | Meaning |
|---|---|---|
| B0 | FCA09C00 | Linear ROM source |
| B1 | 00000080 | Source row pitch, bits |
| B2 | 003002F0 | Destination X=752, Y=48 |
| B3 | 00004000 | Destination row pitch, bits |
| B4 | B4000000 | BG1 base |
| B5 | 000002F4 | Window minimum X=756, Y=0 |
| B6 | 002502F9 | Window maximum X=761, Y=37, inclusive |
| B7 | 00100010 | Requested 16×16 pixels |

The sprite starts at Y=48, below the window's last legal Y=37. **Correct writes:
zero.** The released CPU writes X=756..761, Y=48..63: a **6×16 vertical strip,
96 distinct bytes in 32 accepted masked bus transactions**. First/last bit
addresses: B40C17A0/B40FD7C8. All addresses match the faulty clipping calculation.
These are extra accepted writes, not unaccepted sprite requests.

`R/evidence/cpu-snow-v7/footprint-verification.json` retains the original opcode
fetch context, vector, counts and evidence hashes. Inputs were observed before
execution. A write-only reference trace misses this command because MAME writes
nothing; the complete pre-instruction capture is essential.

A second authentic command at FFE1FCD0, logical frame **6677**, draws 16×16 at
(416,48) with window (0,61)..(417,63). Correct extent: **2×3=6 bytes**. The CPU
writes **16×3=48 bytes**, including 42 extras. All 48 addresses **and data values**
match the defective-semantics prediction with zero errors; see
`R/evidence/cpu-snow-v7/byte-verification.json`. An inside-window control has zero
extra/missing bytes. Additional partial/top and right-edge probes show 72 and 24
extra bytes. Driver exit zero means successful diagnostic execution, not a passing
clipping implementation.

## Stage reproduction and evidence

1. MAME loads `R/mame_fighter2/sta/btoads/state-06000.sta.sta`. At logical
   frame 6003 Lua writes dispatcher state 0x17 to bit address 23E10. The original
   ROM dispatcher entry FFD49A50 calls FFD4A9E0 and advances the original stage
   loader. Snow mode starts at 6130; capture continues to 8530. Discovery/save
   state is explicitly tainted and used only by MAME, never restored into RTL.
2. `R/mame_snow_fetch/` retains reference screenshots, BG/FG memory, palette,
   raster display events and instruction inputs. `R/mame_snow_context/` repeats
   the capture with ST/CONVSP/CONVDP. Lua sources and launcher receipts are kept.
   Strict opcode-half filters exclude adjacent instructions/stale samples.
3. `python R/reconstruct_snow.py mame_snow_fetch 8530` reconstructs BG1 from
   all 15,920 commands. Correct clipping matches MAME's accessible 512×256 BG1
   bytes exactly; released clipping produces 6,435 differences. Receipt and
   causal command list: `R/evidence/mame_snow_fetch-reconstruction-8530/`.
4. `R/cpu_scene_top.sv`, `cpu_scene.cpp`, `run_cpu_scene.py` compile the complete
   released CPU and original clock-enable logic. External-memory adapters supply
   ROM/RAM and record accepted masked writes. `verify_cpu_scene.py` and
   `verify_stage2_footprint.py` prove the two authentic failures. These nonvideo
   tests emit no raster screenshots.
5. `R/cpu_snow_batch.cpp` / `run_cpu_snow_batch.py` execute all 15,920 captured
   inputs through the complete CPU with authentic conversion registers and BG1
   physical X/Y wrapping. Result: 11,713,196 diagnostic cycles, 419,659 BG write
   beats. These include the synthetic instruction driver and **do not measure
   gameplay duration, rendering deadlines or board bus utilization**.
6. `R/verify_cpu_snow_batch.py` establishes 6,435 CPU/reference pixel differences,
   zero CPU/clipping-model differences, and zero correct-model/reference errors.
   CPU BG1 SHA-256:
   `34451f7d25c9129097c97e397d741906b208f1a185c15da77137d2a3caf316bc`.
   Proof, logs, raw bytes and build/source identities:
   `R/evidence/cpu-snow-batch/{verification.json,receipt.json,cpu-bg1.bin,run.log,build.log}`.

![CPU-produced BG1 memory view](../build/stage2_release_20261019/evidence/cpu-snow-batch/cpu-bg1.png)

![CPU versus reference: red marks differing pixels](../build/stage2_release_20261019/evidence/cpu-snow-batch/difference.png)

These are unwrapped **background memory views**, not composed gameplay frames.
The difference band reflects this interval's windows; scrolling/composition
changes its screen position. This capture does not recreate the photos one for
one: none of its final differences specifically changes a nonzero index to zero.

The native cold-boot attempt was stopped after unproductive no-input boot frames;
it is not a passed 12,000-frame replay. Displayed screenshots and its receipt
remain in `R/evidence/` and
`R/tests/graphics/evidence/native/native-26f38f9d99374583a19cd73a37499c20/`.
Earlier component v4/v5 data comparisons used the wrong fixture CONVSP=001b and
failed. Authentic input capture proved 0018; corrected fixture v7 passes the data
comparison. Failed logs remain explicitly superseded rather than counted as proof.

## Original fix plan — implementation summarized below

Repair the TMS34020 instruction layer, preserving current clocks and interfaces.

1. Compute signed near/far intersection and explicit empty status, with enough
   intermediate width for destination+size and inclusive end+1. Reject empty
   intersections before source reads/writes. Derive dimensions from the
   intersection, rather than the window's full dimensions.
2. Derive source crop offsets using PSIZE/CONVSP. Preserve row pitches,
   alignment, conversion, physical wrapping and byte enables; preserve
   instruction-defined register updates, V/window status and retirement.
   Verify mode-0 bypass and observed mode 3. Consult instruction semantics before
   extending modes 1/2, direction or pixel-size variants.
3. Correct unsigned near comparisons. Audit XY PIXBLT/FILL classes sharing the
   helpers, requiring a separate failing vector for each changed instruction path.
4. Use existing registered CPU/microcode stages, or a narrowly scoped extra
   stage, to separate near/far/extent arithmetic. Avoid a new long combinational
   subtract/compare/mux chain. Measure added cycles against raster deadlines;
   rejecting invalid work also removes unnecessary writes, but no throughput
   improvement is claimed without measurement.

Functional acceptance after implementation: both authentic commands write
exactly the legal 0 and 6 bytes; inside control remains unchanged. Cover all four
edges, wholly outside rectangles, negative/zero coordinates and dimensions,
inclusive boundaries, signed overflow/wrapping and relevant sizes/window modes.
Replay all 15,920 inputs through the **modified complete CPU**, require zero BG1
differences and verify architectural post-instruction state. Run existing CPU,
blitter and graphics regressions. Then require source-bound full-core stage-2
gameplay with legal input/checkpoint provenance, including the photographed
downhill section, per-layer/writes/page-flip comparison and first bad frame.
A corrected Python model alone is insufficient release acceptance.

## Preserving timing closure

`TIMING.md` records accepted seed 22: minimum setup **+0.027 ns**, system hold
**+0.081 ns**, four reported corners/204 STA entries closed, zero unconstrained
paths. These are historical results, not fresh STA. The small setup margin makes
closure sensitive even to a local functional change.

Keep 80 MHz system/video, 160 MHz memory, steady 10 MHz pixel enable, current PLL
phases, reset/CDC contracts and SDC. No clock increase or timing exception is
justified. SDRAM stores audio samples; the demonstrated fault is CPU-generated
BG1 data, so SDRAM capture-phase changes have no supporting evidence.

Applicable `mister-clock-timing.md` lessons/sections:

| Section | Action and verification |
|---|---|
| 0, clock plan | Preserve clocks/CEs. Shared lesson 15523 records existing plan compliance; recheck if scope changes. |
| 1, transfers/demand | Preserve accepted-write contract; measure full-core stage-2 deadlines after microcode changes. |
| 2, enables | Keep CE paths full-rate timed; nominal slow CPU speed is no exception proof. |
| 3, spacing/edges | Any future exception needs minimum legal spacing, exact endpoints and launch/capture edges, including stalls/reset/restore. None proposed. |
| 4, coherent CDC | No crossing changes planned; preserve bundled address/data/owner behavior. Prove edges if changed. |
| 5, SDRAM | Inapplicable to demonstrated BG1 instruction defect; no SDRAM change proposed. |
| 6, repair | Repair logic within its transfer contract; register computation rather than weaken timing. |
| 7, qualification | Bind corrected source/QSF/SDC/tool/device/seed hashes to fresh fit and all-corner STA. |

Lesson 9100 records broken sprite copies after foreground latency/phase changes;
do not move foreground VRAM to 80 MHz. Lesson 15327's FG_FAST throughput repair
is already enabled; it does not establish a lost request here. The shared guidance
checker passed, including negative controls; it checks documentation, not fit.

After functional proof, use fpga_mcp and the guarded machine-wide queue for an
authorized independent fit/STA. Require all supported corners and setup, hold,
recovery/removal, pulse width, unconstrained endpoint/exception coverage and
resource checks. Fix paths without loosening constraints. **Do not claim the fix
is timing closed until source-bound reports pass**; closure of the existing RBF
cannot transfer to changed RTL. RBF creation requires a separate explicit request.
Retain the accepted RBF until replacement functional/timing/release gates pass.

## Verified implementation and release qualification

The integration-level root cause is the registered source-address predecode. The
class-51/52/53 microcode requested B14 on `DECI.RS` during state 4, but the final
ID output is overwritten from `IC_RF_ADDR`. `DecodeICRFAddress` had no state-4
RS=B14 entry for these XY instructions and fell through to the encoded B7 field
(`IC[8:5]`). At opcode 0F20, the live state-4 `RF_RB_Q` therefore contained the
requested size `00100010` instead of the B14 far corner `00F10020`; the trace
showed the far corner on state 3, then B7 on state 4. `WinAdjust` consequently
received the wrong far corner and produced corrupt extents. This is a CPU-side
accepted-write defect, not evidence of missed DDR bus service.

The fix adds state-4 RS=B14 to the registered `DecodeICRFAddress` predecode for
classes 51/52/53 and feeds `RF_RB_Q` to `WinAdjust`. It computes a signed
destination/window intersection, crops the source by the clipped near edge, and
rejects empty rectangles; the existing three XY decoders reject any window
exclusion flag. The existing register-address pipeline remains in place. No
clock, enable, reset, CDC, SDRAM or SDC changes were made. The QSF explicitly
keeps `COMPRESSION_MODE ON` and `ON_CHIP_BITSTREAM_DECOMPRESSION ON`.

The final CPU tests passed:

- `tests/run_bt_cpu_blit_window.py`: 8,204 rectangles across all three XY
  decoders, with window clipping enabled and disabled.
- Directed CPU extent cases: inside 96/96 bytes, partial 24/24, right-edge
  72/72, visible 6/6, fully outside 0/0.
- Full replay of 15,920 recorded stage-2 commands: 11,528,601 CPU cycles,
  408,370 BG bus writes, and zero reference reconstruction mismatches. Replay
  ROM hash: `d1ef483fbc8667e08a82e55023bf62df31daf39f6d5d644b863c085062293e6e`.

Receipts and traces remain under
`build/stage2_release_20261019/evidence/`; the detailed source-address trace is
in `evidence/cpu-snow-v10/inside-phase.csv`, and the full replay receipt is
`evidence/cpu-snow-batch/verification.json`. These are component-level proofs,
not a full-game frame comparison or hardware acceptance test. The supplied
photos still lack a matching frame/state identity.

Release job `a0b52b8b-0c3a-40d1-81e1-54030c155bf8` is queued at position 1 behind
two active RBF builds. Its single queue plan runs the full Quartus compile and
then `quartus_cpf -c -o bitstream_compression=on` to produce
`releases/Arcade-Battletoads_20261019.rbf`. The plan and source are in the isolated
checkout based on release commit `423baf55bb60bb89499c61f350a02a54eeb17705`.
Fresh timing is not yet qualified. After the job finishes, inspect all four
corners for setup, hold, recovery/removal, pulse width, unconstrained paths and
resources; verify the compressed RBF has a nonzero size no greater than
6,500,000 bytes and record its hash. If any required timing check fails, repair
and rerun the complete queued RBF flow. Commit the project source/configuration
only after source-bound timing reports and compression validation pass. Leave
hardware testing to the user.
