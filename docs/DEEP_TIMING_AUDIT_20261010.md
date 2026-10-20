# Battletoads timing and feature audit — 10 October 2026

## Findings and recommended order

The latest retained Quartus results show one failing capture domain: **160 MHz**.
The two misses are temperature corners of that domain, not separate 80 MHz and
160 MHz failures. Preserve the working CPU timing and first remove unnecessary
video infrastructure, then optimize the actual remaining memory-domain cones.

The strongest source/resource candidates are:

1. Finish the rotation removal by eliminating its FIFO and arbitration branch,
   while retaining the two-entry Avalon command register slice.
2. Replace the disabled HQ2x buffer chain with a purpose-built ordinary 2× line
   doubler. Tying `hq2x` low removes interpolation work, but does not remove the
   line storage used by the existing scandoubler.
3. Try the existing `MISTER_DISABLE_ADAPTIVE` scaler switch as a separate,
   reversible feature tradeoff. Retain HDMI and ordinary integer scaling.
4. Use detailed paths from the resulting fit to select local foreground/DDR
   fanout or same-edge predecode changes. Existing reports establish the failing
   domain, but do not expose the current routed failing endpoints.

These are candidates, not measured improvements in slack. **No HDL, QSF, SDC,
clock, game feature or RBF was changed by this audit.** Audit tooling and this
report are the only additions.

## Evidence identity and limits

<!-- PROVENANCE_START -->

The first and final audit captures have identical hashes for the retained tracked HDL/constraint/project/init files and Quartus reports. Current HEAD: `6b66897664bda6cace6da60752fe57f5dc4f3e76`.

Files newer than the retained synthesis report: `Arcade-Battletoads.sv`, `files.qip`. The retained fit therefore cannot qualify these current files.

HEAD commit receipt:
```text
6b66897664bda6cace6da60752fe57f5dc4f3e76
2026-10-10T19:31:07+11:00
remove the HDMI rotation framebuffer tap
```

<!-- PROVENANCE_END -->

The current rotation-removal commit was recorded at 19:31:07 +11:00, after the
retained fit and timing reports. Thus the quoted slack/resource baseline predates
that removal. First qualify the already-removed tap before attributing new savings
to further bridge cleanup. HQ2x tied low and the remaining bridge are verified in
current source; the hierarchy costs are specifically those of the retained fit.

Retained fit: `output_files/Arcade-Battletoads.fit.rpt`, successful
10 October at 17:24:57; retained synthesis report: 15:36:20; timing report:
17:28:57. Times are recorded verbatim from the reports. Evidence recovery:

- `build/deep_timing_audit_20261010/evidence.json`: source/report hashes,
  complete summary timing rows, resource records and warning inventory.
- `build/deep_timing_audit_20261010/verification.json`: source stability,
  files newer than synthesis, current commit and unconstrained-port inventory.
- `build/deep_timing_audit_20261010/extract.py`: reproducible report-only
  extraction and verification; invokes no FPGA tool.
- `build/deep_timing_audit_20261010/paths.tcl`: prepared extraction script for
  the existing routed database; **not executed**.

The host's PreToolUse policy rejected direct `quartus_sta -t` execution, including
a simple check-only invocation, and rejected frontend `--help`. No alternate
executor was used to evade that policy. Thus this audit does **not** claim a fresh
all-corner path extraction, a complete list of failing endpoints, new timing
closure, simulation qualification of a candidate, or hardware readiness.

Source and resource audits cover the wrapper, active clocks and constraints,
CPU/VRAM/DDR interfaces, graphics storage, audio/storage allocation, scaler,
scandoubler, feature macros, platform documentation and existing experiment
evidence. This is not an exhaustive formal equivalence proof or a gameplay audit.

## Correct timing baseline

The Clocks table assigns `general[0]` a 12.500 ns period (80 MHz), `general[1]`
a 6.250 ns period (160 MHz), and `general[2]` a 12.500 ns period (80 MHz)
with an 8.750 ns sampling offset. The shifted SDRAM sample clock is also close
to its setup limit and must remain part of sign-off.

| Domain/check | Slow 1100 mV, 100°C | Slow 1100 mV, −40°C | Interpretation |
|---|---:|---:|---|
| 80 MHz system setup | +0.165 ns | +0.198 ns | Passing, modest margin |
| 160 MHz memory setup | **−0.293 ns** | **−0.203 ns** | Failing |
| 160 MHz endpoint TNS | −3.729 ns | −1.327 ns | More than one failing endpoint; exact count unavailable |
| Shifted 80 MHz sample setup | +0.036 ns | +0.478 ns | Passing, very small hot-corner margin |
| Scaled HDMI output setup | +0.043 ns | +0.041 ns | Passing, very small output margin |

Across the four retained 1100 mV slow/fast temperature summaries, minimum hold is
+0.067 ns, recovery +0.497 ns, removal +0.259 ns, and minimum pulse width
+0.625 ns. These pass the recorded checks. They do not waive unconstrained paths.

The negative memory-domain slack can include paths launched by the system
clock; the capture-clock label alone does not identify a memory-to-memory path.
Do not spend the first optimization iteration rewriting the already-passing CPU.

## Placement pressure, not an exhausted ALM budget

| Fitted resource | Used / capacity | Utilization |
|---|---:|---:|
| ALMs needed | 23,287 / 41,910 | 55.56% |
| LABs partially or completely occupied | 3,571 / 4,191 | **85.21%** |
| M10Ks | 469 / 553 | **84.81%** |
| Useful block-memory bits | 4,304,640 / 5,662,720 | 76.02% |
| Physical block-memory implementation bits | 4,802,560 / 5,662,720 | 84.81% |
| DSP blocks | 33 / 112 | 29.46% |
| Average interconnect, total / horizontal / vertical | — | 32.7% / 31.8% / 35.5% |
| Peak interconnect, total / horizontal / vertical | — | 57.3% / 55.6% / **78.0%** |

The previously recorded resource policy targets LABs at 85%; this fit is nine
LABs above the largest integer count satisfying that target. M10Ks are within
the 85% target. The physical memory-bit utilization is substantially higher than
the useful-bit figure. Average routing is comfortable, but local vertical peaks
and dispersed occupied LABs leave much less freedom than the 56% ALM headline
suggests. Freeing RAM and placement constraints can help routing; it does not
guarantee an improvement on a particular path.

Selected hierarchical fitted costs below include descendants and must not be
added together when rows overlap. ALM values are fractional fitter estimates,
not removable area promises.

| Hierarchy | ALMs needed | Registers | M10Ks | DSP |
|---|---:|---:|---:|---:|
| TMS34020 CPU | 5,839.2 | 2,649 | 0 | 0 |
| Four background VRAM instances, combined | 1,601.0 | 1,091 | **224** | 0 |
| Two foreground VRAM instances, combined | 2,219.2 | 2,350 | **116** | 0 |
| Sprite VRAM | 294.3 | 286 | 2 | 0 |
| DDR controller | 1,048.7 | 1,718 | 0 | 0 |
| HDMI scaler | 3,204.0 | 4,600 | 26 | 23 |
| Video mixer, including scandoubler | 901.6 | 3,125 | 15 | 0 |
| HQ2x hierarchy within scandoubler | 741.4 | 2,687 | **14** | 0 |
| Video DDR bridge | 156.8 | 329 | **4** | 0 |
| Audio output hierarchy | 1,001.4 | 1,092 | 0 | 8 |

Background and foreground stores account for 340 of 469 M10Ks (72.5%). They are
the largest storage costs, but they hold actual board state. The optional video
machinery is a smaller, safer first target.

## Feature removal and simplification candidates

### 1. Rotation FIFO and arbitration: strongest cleanup candidate

Current `Arcade-Battletoads.sv:637` onward drives `FB_EN` and the rotation
write/address/data signals to zero, but still instantiates `bt_video_ddr`.
`rtl/bt_video_ddr.sv:24` onward contains a 512×62 asynchronous FIFO, a 62-bit
head register, rotation ownership, payload muxing and reset fanout.

Use an explicit compile-time no-rotation branch: omit the FIFO, head/popup state,
video hold and video-payload arbitration. Feed memory requests into the existing
registered command/skid path. Preserve reset behavior, accepted command edges,
backpressure, burst count, byte masks and stability while the HPS is busy.

The retained fit's bridge occupies four M10Ks, 156.8 ALMs and 329 registers.
Only the rotation portion is removable; the slice must remain. Four M10Ks are
an upper bound on the FIFO storage opportunity in that baseline, not a measured
post-removal saving. The bridge also carries real 160 MHz memory traffic, making
it more directly relevant than a disconnected cosmetic feature.

**Do not wire the controller straight to HPS wait-request.** That would undo the
existing register slice and could recreate the late hard-block timing path.
Qualification: `tests/rotation_ddr_tb.sv` adapted to the disabled feature plus
the real DDR controller/bridge and native command-journal checks. Preserve the
ordinary memory request stream; rotation behavior is intentionally absent.

### 2. Disabled HQ2x storage: largest optional RAM opportunity

The wrapper connects `.hq2x(1'b0)` at `Arcade-Battletoads.sv:619`. Nevertheless,
`sys/scandoubler.v:102` instantiates `Hq2x` unconditionally and consumes its
output pixels even in ordinary 2× mode. In `sys/hq2x.sv:76`, disabling HQ2x
changes the blending rule, while the line-input and line-output buffers remain.

Consequently, deleting only the OSD option or tying the enable low cannot remove
the buffering chain while the current scandoubler uses it. The code comment that
the HQ2x buffer was removed overstates what the source does. The retained fit
contains 14 M10Ks within `Hq2x`, including ten in `hq2x_out` and four in its input
stores. These are real fitted allocations; verify exact current-image identity
before treating them as the cost after the latest source change.

A core-owned ordinary 2× line doubler, or a separately reviewed framework
parameter supporting a native non-HQ buffer implementation, could replace this
chain. Some line storage is still necessary: **14 M10Ks is the existing cost,
not the net saving**. Preserve normal video, 2× scandoubling, forced scandoubler,
direct video, sync/DE phase and CRT scanline options. Do not silently edit the
shared `sys/` framework in place during this audit.

Qualification must compare complete output rasters, blanking and pixel enables
for native/direct video, 2×, all CRT intensities and HDMI scaling. Existing
`tests/hq2x_buf_split_tb.sv` checks the old memory split; it does not prove a new
line doubler equivalent.

### 3. Disable adaptive scaler filtering: supported optional switch

`sys/sys_top.v:399` and `:730` already implement
`MISTER_DISABLE_ADAPTIVE`: they advertise the reduced capability and instantiate
the scaler with `ADAPTIVE("false")`. This macro is absent from the active QSF.
The scaler's fitted total is 3,204 ALMs, 26 M10Ks and 23 DSPs; adaptive filtering
is only a subset of that total.

This is a reasonable reversible feature experiment if adaptive interpolation is
dispensable. It retains the HDMI scaler and integer-scale options. Measure the
actual reduction with MAP and then a check-only fit; no exact saved resources or
nanoseconds can be inferred from the parent hierarchy. Verify firmware capability
reporting and every remaining scaler mode. Its expected timing contribution is
mostly placement relief; the scaler itself is not the reported failing domain.

### 4. Framebuffer interface macro after rotation removal

The QSF still defines `MISTER_FB=1` while current wrapper framebuffer outputs are
idle. Audit the framework's conditional ports, HPS capability reports and scaler
framebuffer paths before removing that macro. Existing constant propagation may
already remove substantial logic, and the current `PALETTE2("false")` setting
already avoids the second palette. A QSF-only change without matching interface
guards can fail elaboration. This is secondary to removing the explicit FIFO.

### 5. Nearest-neighbor downscale profile

`MISTER_DOWNSCALE_NN` is supported by `sys/sys_top.v:733`; it sets the scaler's
`DOWNSCALE_NN` generic. This can be evaluated if filtered downscaling is not
required, but it changes image quality when reducing output size. It does not
remove the whole scaler and its exact resource effect is unmeasured. Prefer the
adaptive switch first because normal bilinear/downscale behavior can be retained.

### 6. Native-only video profile: larger sacrifice, lower priority

A profile removing the scandoubler can free more optional video state than a
non-HQ implementation, but sacrifices 2× output and CRT scanline processing.
Removing HDMI altogether is much more disruptive: it removes a 3,204-ALM,
26-M10K parent hierarchy but also a primary MiSTer output path. These are useful
diagnostic profiles only if the corresponding feature loss is explicitly wanted;
neither is the recommended first fix for this small miss.

### Already disabled, absent, or unlikely to buy timing

- ALSA and Y/C: active QSF macros `MISTER_DISABLE_ALSA=1` and
  `MISTER_DISABLE_YC=1` already remove them. They are not new savings.
- HDMI rotation: current source has removed the tap and menu; it cannot be
  counted again as a fresh feature cut. Clean up residual bridge infrastructure
  and qualify the current source before estimating its effect.
- HQ2x interpolation: already tied off. Its remaining storage requires a
  structural replacement, not another enable change.
- Crop/aspect scaffold: `vcrop_en=0`, `vcopt=0`, `rotate_90=0`, and fixed 4:3
  inputs permit synthesis to prune unused branches. Removing dead `en216p`,
  `voff`/`ar` source scaffolding mainly cleans warnings, not established area.
- Debug grid/background controls: `DEBUG` is not defined in the active QSF;
  default controls are constants. Do not attribute removable resources merely
  to source lines that synthesis already folds.
- NVRAM/high scores, pause, DIPs, service and three-player inputs: real platform
  behavior, comparatively small costs, no current failing path established.
  Removing them is poor value. The original battery RAM also holds cabinet state.
- Stereo mixing/audio: the output hierarchy is sizeable, but that does not make
  it expendable; BSMT sample timing and the actual stereo game audio must remain.
- Savestates/cheats/crosshairs: no active implementation established in this
  supported set; they cannot be assumed to be removable costs.

## RTL optimization candidates that preserve features

### Foreground copy and DDR request cones

Current foreground logic already has per-bank request/address/enable registers,
`COPY_PREFETCH_B`, per-bit `COPY_LANE_BIN8`, local bank controls and registered
`READ_DDR_R`. The DDR controller already factors local completion terms,
per-bank tag capture, byte-lane return selectors and busy reduction.
Do not re-propose these as untouched opportunities.

Remaining useful directions, conditional on the actual failing path:

- Replicate a request/select register per physical consumer **at the same edge**,
  with `preserve`/`dont_merge` only where the mapped fanout warrants it. Copy reset
  and update priority exactly; avoid extra latency.
- Carry address/lane/bank decode alongside existing pipeline stages, rather than
  repeatedly decoding a shared counter at the RAM write-enable endpoint.
- Factor late `rd`, `we`, completion and tag-hit inputs into shallow local cones
  before the existing capture flop. `ddram.sv:150–190` already performs some of
  this; target what survives in the fitted path, not the original source shape.
- Separate independent CPU, copy and sprite ownership terms where they drive
  dispersed RAM banks. Preserve collisions, return-word ownership and backpressure.

Historical routed results in `docs/RESOURCE_TIMING_AUDIT_20261008.md` and the
shared lessons identify foreground completion/copy controls and DDR arbitration
as previous failures. They justify where to look, but **are not proof that any
named historical endpoint is the current −0.293 ns path**.

### Memory packing and bank geometry

The four background memories alone use 224 M10Ks; two foreground memories use
116. A mixed-width/bank slicing experiment can be valuable if it reduces actual
M10K count or RAM-to-selector routing while preserving capacity and physical port
behavior. Useful-bit utilization leaves some packing overhead, but does not prove
the overhead can be removed with the required dual ports, widths and byte enables.

Keep both foreground pages, the offscreen DDR window, CPU shift cache and sprite
mirror. Existing tests cover unaligned copies, page boundaries, masks, collisions,
serial reads and draw transfers. A more compact memory layout must preserve all
of them and the exact consuming edges. Do not replace storage with a large LUT mux
without measuring its LAB/routing cost. This is a higher-risk second-stage option.

### Clock and CPU choices

Keep 80/160 MHz for the first candidates. `bt_clock_enables.sv` preserves 32 MHz
CPU phases and an exact 10 MHz pixel enable using this system frequency. A casual
PLL change alters pixel cadence, external SDRAM timing or game throughput unless
the clock plan and every affected interface are redesigned together.

Shared verified lessons explicitly rejected moving foreground VRAM to 80 MHz:
sprite-copy mismatches, DDR strobe-age failures and a harness phase inconsistency
were observed. Resolve the simulator's offset versus coincident PLL-edge modeling
before reconsidering that architectural change. Slower-clock conversion is not
a drop-in timing fix.

The CPU is the largest logic consumer but its current setup checks pass. Fullword
and sign-only operand pre-extension experiments in the resource audit were
previously rejected for increased area or unchanged/deeper mapped paths. Do not
remove opcodes, multiply/divide, transparency, zoom, layers or offscreen state
based only on an attract-mode trace; gameplay and service code can use them.

## Fitter settings and rejected approaches

The active QSF already uses standard-fit/high-performance effort, placement
effort multiplier 4.0, maximum router timing optimization, physical logic/register
duplication, speed optimization, MUX restructuring, no automatic resource sharing,
and low ALM register-packing effort. Physical register retiming is OFF, consistent
with the phase/capture-register constraint contracts. These switches are not
unused magic fixes.

After a structural reduction, a small seed comparison can be a legitimate
check-only experiment on the exact same source and constraints. Compare all
corners, TNS, hold and the near-zero sample/HDMI margins, not just a single worst
setup number. There is no measured seed benefit for the current source in this
audit. More effort on an already high-effort fit may cost substantial time with
little benefit.

Do not reapply broad floating auto-size LogicLock regions to FG0/FG1/SPR/DDR.
The 10 October shared lesson records a 70-minute fit that worsened memory slack
from −0.284 to −0.716 ns and hot-corner TNS from about −5 to −39 ns. Keep this
result distinct from the current −0.293 ns baseline.

Do not globally remove `preserve`/`dont_merge`, enable register retiming, increase
resource sharing or force aggressive packing without a paired proof. These can
merge intentional local replicas, change capture identity or trade area for mux
depth. RAM-to-logic placement should follow a small named cone, not a rectangle
around every member of a large VRAM subsystem.

## Constraint and readiness audit

The design has explicit CPU CE_R phase, CPU read-capture CE_F, DDR metadata/return,
foreground gather, audio DSP and external video/SDRAM/audio constraints. The
reviewed CPU and DDR scripts scope multicycles to named registers and carry paired
hold adjustments. DDR request-side timing remains single-cycle where the source
can change on the request edge; ordinary RAM and control paths are not covered
by a clock-wide exception. Any proposed new exception requires a fresh age/
stability proof across reset, pause, collisions, writes and gameplay.

The retained reports identify:

- Zero illegal clocks and zero unconstrained clocks.
- **Four unconstrained input ports / 14 input paths**, and **18 unconstrained
  output ports / 61 output paths**, for both setup and hold. Some may be static or
  asynchronous framework signals, but this audit has not classified them all.
  The retained summary counts are in `verification.json`; detailed port names were
  not exported by this report. Do not claim clean
  external-interface sign-off from the clock summaries alone.
- Ignored SPI clock targets and Y/C filters, consistent with absent/disabled
  logic; the dead `en216p` false-path target; and unmatched optional/dead register
  patterns in CPU/DDR collections. Collection counts alone do not prove every
  intended member survives or is covered. Audit mandatory groups individually.
- Synthesis critical warning 18061, ignored power-up-level options. Its context is
  retained in `verification.json`; review which registers require reset or
  initialized state before release. It is not a setup-slack fix.
- STA critical warning 332148, timing requirements not met. This remains real.

The README and `docs/PLATFORM_FEATURES.md` still advertise HDMI rotation and Y/C
output; the active source/macros disable them. Update that documentation when
the chosen feature profile is finalized. The README also states gameplay remains
unverified. Existing native boot replay and saved raster evidence cannot be
extended to claim whole-game or current post-removal hardware equivalence.

## Finite validation plan

Keep each candidate independently measurable; accept a combination only after
its separate effects and contracts are understood.

| Candidate | First functional proof | Physical decision |
|---|---|---|
| No-rotation FIFO/arbitration branch | Memory-only bridge: busy bursts, back-to-back commands, masks, reset, skid occupancy and command stability; native journal | MAP proves actual FIFO removal; check-only fit compares 160 MHz and HPS paths |
| Ordinary non-HQ 2× doubler | Full raster/DE/sync/pixel-enable equivalence in every remaining video mode | Count replacement buffers and LABs; compare routing and all setup/hold corners |
| Disable adaptive filter | Remaining scaler modes and firmware capability reporting | Measure actual resource delta, then all-corner route |
| Foreground/DDR same-edge local copies | Focused controller/VRAM equivalence plus native transactions | Fanout/delay decrease on a named formerly failing path, with no new failures |

Check-only Quartus work should use the currently reviewed QuartusFast path and
preserve custom preprocessing. This audit could not establish an allowed custom
STA-only export route, so it did not launch a replacement map/fit merely to obtain
a report. Any subsequent fit must remain check-only: **no `--allow-rbf`**, no
assembler/CPF/full compile unless the user explicitly requests an RBF build.

Final acceptance requires exact source/build identity, all applicable setup,
hold/recovery/removal/pulse checks, classified external ports, reviewed critical
warnings, and current-source functional/replay/hardware evidence. A positive
few-picosecond setup result is closure but offers little engineering margin;
prefer useful positive headroom when comparing otherwise equivalent candidates.

The recommended first implementation is the rotation-free bridge cleanup; the
recommended first substantial feature/storage experiment is a non-HQ line
doubler. Neither requires sacrificing game layers, sprite behavior, CPU accuracy,
audio, controls or high scores.
