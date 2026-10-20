# Resource and timing audit, 8 October 2026

## Acceptance

Preserve game behavior, all memory address ranges, sound, all players, pause,
NVRAM, ROM loading, scaler, rotation, analog/direct video and HQ2x. The final
RBF must come from an immutable, source-matching fitted snapshot that meets
every resource hard limit and all eight operating-condition timing models.
Setup, hold, recovery, removal, pulse width and documented external interfaces
must pass. The user explicitly requested the final RBF build in this chat.

| Resource | Target | Hard limit |
| --- | ---: | ---: |
| ALMs | 75% | 80% |
| Partially/completely used LABs | 85% | 90% |
| Peak interconnect, higher of H/V | 80% | 85% |
| Average interconnect | 50% | 60% |
| M10Ks | 85%, at most 470 | 90%, at most 497 |
| Block memory bits | 80% | 85% |
| DSP blocks | 80% | 90% |

The device has 41,910 ALMs, 4,191 LABs, 553 M10Ks, 5,662,720 block-memory
bits and 112 DSP blocks. A RAM's physical cost depends on port geometry and
byte enables as well as its useful bits. Moving storage into MLABs exchanges
M10K capacity for LABs, ALMs and routing; it is not a free saving.

## Baseline integrity

The latest complete successful baseline available at the start of this audit is
`D:/vibes/fpga/temp/bt-graphics-6e109c39bb7c4293bbb1d5eaf0e4e5f8`.
It uses 23,429 ALMs (55.90%), 492 M10Ks (88.97%), 4,316,800 block-memory
bits (76.23%) and 35 DSP blocks (31.25%). Its detailed fitter report is missing;
its summary therefore cannot establish current LAB or routing percentages.
Earlier fits recorded in RESOURCE_OPTIMIZATION.md are historical evidence.

The reported batch-7 -1.12 ns / approximately -29 ns TNS corresponds to the
baseline's slow 1100 mV, -40 C corner: SYS -1.124 ns / TNS -23.814 ns;
MEM -0.534 ns / TNS -5.369 ns. The 100 C corner has worse worst setup
slack: SYS -1.174 ns and MEM -0.437 ns. These are failed timing results.
Several current RTL/SDC files differ from that fit, so it cannot qualify them.

`bt-graphics-62e116eed7014a6199c3675a12586973` failed while reading SDC:
the DSP RAM's stored-data endpoints did not yet exist in the fitter's early
netlist. Its summary's zero RAM-block count is not a resource result. Endpoint
absence is tolerated at the early fitter stage, but the routed eight-corner
audit now requires both CPU and DSP stored-memory endpoints in every corner.

## Safe storage candidates

### HQ2x tails

The existing depth split preserves all 520 input and 1,040 output entries.
Its small tails (two 8x24 stores and one 16x96 store) lacked a placement
attribute. The available RAM report places those 1,920 useful bits into five
M10Ks. Direct MLAB placement alone is unsafe: the actual Intel post-synthesis
model returned current write data on a same-address collision, despite a
passing registered-read RTL equivalence test.

The MLAB tails now buffer each write for one clock, with pending write enable
initialized to zero. The following clock commits the preceding write and
forwards its data when the read address matches. Each read therefore sees the
logical memory state through the preceding clock, excluding the current write.
This preserves old-data reads, addresses, data bits, write enables and the
existing registered output latency. Expected whole-HQ2x allocation is 19 -> 14
M10Ks; routed resources and timing remain pending.

The complete production RTL passes 400,000 cycles: 398,960/399,480 defined-word
comparisons and 6,321/6,168 output/input tail reads, including main/tail crossings.
Two Quartus-generated Intel atom designs test the full physical data widths
below ModelSim Starter Edition's design-size threshold. The output tail passes
400,000 cycles, 399,984 full 96-bit comparisons and 75,178 collision cycles.
Both input tails pass 400,000 cycles, 399,992 full 24-bit comparisons per write
owner and 125,347 collision cycles across the independent owners, at 160 MHz.
These are functional proofs; the routed timing gate is still required.

The normalized `tests/graphics/evidence/hq2x_mlab_tail/receipt.json` records
`exit_code: 0`, `hardware_equivalence_passed: true`, lowercase source SHA256s,
and separate logs and PASS markers for the complete RTL and both physical
proofs. Acceptance checks PASS/error text because ModelSim can return zero
after a SystemVerilog `$fatal`. The existing equivalence bench
is strengthened with a complete initial address sweep and explicit tail-read
coverage. Savings are accepted only after primitive/probe and full-fit checks.

### Foreground bank geometry

Each foreground page uses sixteen 4 KiB banks, each costing four M10Ks:
64 blocks per page. Four 16 KiB banks can use the existing 5+2+1 bit slicing
with the 5-bit slice's depth limited to 2,048. Each larger bank costs fourteen
blocks, giving 56 per page and a sixteen-block saving across both pages.

The candidate keeps the complete capacity and byte enables, two-clock serial
read latency and CPU/sprite write arbitration. It reduces the external serial
bank selection from sixteen inputs to four. The larger RAM's internal mux is
a timing risk, so production primitive equivalence, transaction regressions,
native replay and a full routed fit decide whether to retain it. Background
RAM geometry and latency remain unchanged.

Together, these measured geometry opportunities predict 492 -> 471 M10Ks,
85.17%, before the final fit. Predictions are not fitted results.

### DSP firmware ROM

The canonical 4,096x16 BSMT firmware ROM originally consumed eight M10Ks.
Its 5+5+5+1 partition uses three two-block 5-bit stores and one one-block
1-bit store. The isolated Quartus fit confirms **seven M10Ks and eight ALMs**.
Slice initialization reconstructs and compares every canonical address.
The firmware remains byte-for-byte unchanged, SHA256
`cb773c8f5687b2c15aa038215b2f91d4d02b47657e7064ec25232d1b3d102815`.

The Intel primitive test passes all 4,096 words, 20,000 clocked reads and
19,999 between-edge held-output checks, including the unchanged generic
filename fallback. The actual Quartus-generated Intel atom netlist independently
passes all 4,096 words, 20,000 clocked reads and 19,999 held-output checks
against canonical golden data. Input-address registration and unregistered
output latency remain unchanged; main-core routed timing is pending.

The normalized `tests/graphics/evidence/bsmt_rom_slices/receipt.json` records
`exit_code: 0`, `hardware_equivalence_passed: true`, `expected_m10k: 7`, and
lowercase SHA256s for production memory RTL, the canonical MIF, four slice
MIFs, generator and bench. It names generator, primitive, synthesized-netlist
and component-fit evidence. The primitive test compares the
actual clocked ROM outputs against the original 16-bit primitive. The SIM
branch retains the existing canonical firmware behavior. This extra block
would bring the combined prediction to 470/553 = 84.99%, at the target.

### Physical M10K allocation before these candidates

Allocation from the available detailed report corroborates the successful
baseline's 492-block total, but the report's failed placement cannot establish
final routing or LAB use:

| Storage | M10Ks | Audit decision |
| --- | ---: | --- |
| Four background stores | 224 | Keep every byte; existing bit slices retained |
| Two foreground stores and mirrors | 132 | Consolidate banks; retain mirrors and both pages |
| Z80 ROM and RAM | 56 | Keep capacity and loader arbitration |
| Scaler | 26 | Keep supported video modes and widths |
| HQ2x | 19 | Verified delayed-commit MLAB tails; expected 14 (-5) |
| BSMT firmware ROM | 8 | Verified slices; component fit 7 (-1) |
| NVRAM | 8 | Keep all 8 KiB and save/restore behavior |
| VGA and HDMI OSD buffers | 8 | Keep independently clocked displays |
| Video DDR FIFO | 4 | Keep backpressure and burst buffering |
| Sprite registered mirror | 2 | Keep blitter/copy read timing |
| Palette | 2 | Keep full palette and readback |
| Credits text, gamma and shadowmask | 3 | Keep useful display/attribution functions |
| Total | 492 | Expected 470 / 553 = 84.99%; routed result pending |

## Retained capacity and rejected shortcuts

- Background words contain two pixels; deleting their high bytes changes
  rendered output. The current 5+2+1 slicing already improves their packing.
- Both foreground pages and the offscreen DDR window are addressable by the
  game. They cannot be truncated to the visible rectangle.
- The audio CPU writes its full upper 32 KiB RAM window. ROM and RAM capacities
  and loader byte ordering are retained.
- HQ2x requires its margin above a power-of-two line depth. Removing those
  entries or the scandoubler would change video behavior.
- The sprite serial copy uses MLABs and has a separate read address. Removing
  it needs transaction and timing evidence; its apparent duplication alone
  is not sufficient.
- The standalone CREDITS donor has smaller optional artwork, but the current
  host fit does not instantiate that artwork ROM. Importing it would not free
  the claimed two M10Ks in this core.
- Broad RAM-to-MLAB migration previously exceeded LAB/MLAB resources. Use
  MLABs for tiny shallow tails, and measure the complete fit afterwards.
- Lowering game clocks, deleting sound/video options or adding broad timing
  exceptions is not an accepted way to meet these limits.

## Clock and proof boundaries

The game keeps its 80 MHz master, related 160 MHz memory clock, 10 MHz pixel
enable, original CPU/sound enable schedules and phase-shifted SDRAM receive
clock. The latter has a separately qualified external-data sampling window.
MiSTer HDMI/HPS/platform clocks are retained. Converting all of these to a
single clock would require a substantial interface redesign and new external
memory qualification.

Current phase exceptions require endpoint ownership and minimum age checks
in native execution. CPU opposite phases keep their actual interval. DDR
DATA_OLD is excluded from the two-memory-clock metadata exception. A source
hash or a successful Quartus process exit alone does not establish timing.

`tests/graphics/resource_audit.py` records actual routed resource values and
refuses incomplete/missing evidence or any hard-limit excess. `assemble.py`
requires that audit as well as the existing source-bound eight-corner and
functional gate before running the assembler.

Final fitted values, regression receipts, timing slacks and RBF hashes are
recorded below when those checks complete.

## First completed resource-reduction fit

The frozen `bt-graphics-823deb4d9ed441878bbf8da7f3d5184f` fit completed successfully.
Its resource audit records the actual routed counts, rather than estimated
allocation or the rounded summary percentages:

| Resource | Routed result | Target met | Hard limit met |
| --- | ---: | :---: | :---: |
| ALMs | 23,642 / 41,910 = 56.41% | Yes | Yes |
| LABs partially/completely used | 3,657 / 4,191 = 87.26% | No | Yes |
| Peak interconnect, maximum H/V | 72.4% | Yes | Yes |
| Average interconnect, conservative maximum total/H/V | 34.9% | Yes | Yes |
| M10K blocks | 470 / 553 = 84.99% | Yes | Yes |
| Block memory bits | 4,314,880 / 5,662,720 = 76.20% | Yes | Yes |
| DSP blocks | 35 / 112 = 31.25% | Yes | Yes |

Thus the measured M10K reduction is exactly 22 blocks. LAB use remains above
the preferred 85% target, while staying below its 90% hard limit. The
source-bound receipt is in
`tests/graphics/evidence/quartus/bt-graphics-823deb4d9ed441878bbf8da7f3d5184f/resource_audit.json`.

This fit is **not eligible for an RBF**. Its complete eight-corner audit found
worst setup -1.003 ns, hold +0.014 ns, recovery +0.405 ns, removal +0.186 ns
and pulse width +0.625 ns. Four partial-multicycle constraint warnings also
remain in every corner. The leading setup failures involve foreground
completion status into CPU wait/pending registers, a foreground copy input
passing through the top-level address-dependent return mux, and sprite data
into the foreground write-bank controls. Subsequent fixes must preserve
the qualified transfer data, readiness publication and clock rates, then
repeat the frozen fit and all-corner gate.

## Routed selector/cache fit and stricter return-path audit

The subsequent immutable fit is
`D:/vibes/fpga/temp/bt-graphics-03288534efee409690844448d35a5c56`.
It contains the raw foreground DDR connection, staged return selectors,
local sprite write-bank predicates and 50-bit cache packing. It predates
the newly reproduced pause/controller repairs and further VRAM pipelines.
The fitter and ordinary TimeQuest run both completed successfully; this
does not establish timing closure.

| Resource | Routed result | Target met | Hard limit met |
| --- | ---: | :---: | :---: |
| ALMs | 23,483 / 41,910 = 56.03% | Yes | Yes |
| LABs partially/completely used | 3,623 / 4,191 = 86.45% | No | Yes |
| Peak interconnect, maximum H/V | 78.4% | Yes | Yes |
| Average interconnect, conservative maximum total/H/V | 34.1% | Yes | Yes |
| M10K blocks | 470 / 553 = 84.99% | Yes | Yes |
| Block memory bits | 4,314,880 / 5,662,720 = 76.20% | Yes | Yes |
| DSP blocks | 35 / 112 = 31.25% | Yes | Yes |

All numeric hard limits pass. LAB usage needs another 61 occupied LABs
removed to meet the preferred 85% target. The cache/control changes remove
159 ALMs and 34 LABs relative to the preceding routed fit. Their placement
raises the peak vertical interconnect percentage, which remains below its
80% target. The cache uses logic memory, so its narrower representation
does not reduce the reported block-memory bits. The resource receipt is
`tests/graphics/evidence/quartus/bt-graphics-03288534efee409690844448d35a5c56/resource_audit.json`.

The clock-wide MEM-to-CPU-return multicycle exception has been removed.
Only individually named DDR-owned register sources retain the qualified
DDR return exception. Ordinary foreground/background RAM reads must now
meet the real 6.25 ns memory-to-system relationship. Consequently these
results cannot be compared numerically with the old -1.003 ns audit as if
the timing constraints were identical: the previous exception concealed
several RAM and control paths.

The complete eight-corner audit reports worst setup **-6.321 ns**, hold
**+0.046 ns**, recovery **+1.072 ns**, removal **+0.213 ns** and pulse width
**+0.625 ns**. This snapshot is not eligible for assembly. Its retained
timing receipt and all detailed reports are under the same evidence folder.
The dominant path is a background RAM write/address register through the
unregistered RAM output, return selection and cache metadata decode into
the cache RAM: 10.434 ns data delay, -1.877 ns clock skew and a 6.250 ns
relationship at the -40 C slow model. Foreground RAM has the same problem.
Smaller memory-domain failures include foreground copy-state selection
into serial RAM write enables (-0.396 ns), foreground copy ownership into
DDR read arbitration (-0.338 ns) and video command FIFO control (-0.208 ns).
The sprite-bank fanout path is absent from this model's ten leading
memory-domain paths after its local-predicate fix.

The combined 128-frame replay for this exact selector/cache revision
passed 8,408,774 CPU return captures, 5,167,437 physical DDR return checks,
2,573,046 accepted write edges and 12,792,856 DSP phase checks. All 24
retained pre/post raster images are byte-identical to the original native
baseline. Evidence is
`tests/graphics/evidence/native/native-d6622a1c6dac4cb18374dbf81dcc46ac/receipt.json`
and its `raster_comparison.json`. This replay does not cover every pause
phase or prove the failing physical RAM paths safe.

The independent real-MC/cache adversarial test subsequently reproduced
two existing pause defects. Resuming on F after skipping R could clear
the read/fetch latch before the external strobes were released. A fetch
could also write cache data before R had prepared its owner address and
tag. Private repairs retain the bus-close event until R and gate cache
payload writes until preparation has actually occurred. Their proof also
checks EN0 before and after preparation, both resume phases, late palette
updates, extended reads, RMW, both foreground pages/all four banks,
background pages, DDR drawing and transfer handoffs. The accepted private
receipt is
`tests/graphics/evidence/selector-bridge/selector-bridge-10397a91964641ffad0e8cd0626bb829/receipt.json`:
223 actual captures, 175 independently checked cache write addresses and
148 cached-word/tag checks, with all guards enabled. Any later pipeline
change requires a fresh source-bound run; these receipts cannot qualify
different source bytes.


## Final registered-memory and cache stage functional qualification

The source-frozen candidate `bt-graphics-ea17f5d2d85d4590a9bee8dde38c61dc` includes the registered FG/BG port-A memory outputs, local serial-bank controls, narrowed cache word stage, pause-controller repair and factored DDR arbitration. Its map and fit completed; all-corner timing qualification is still required before assembly.

The corresponding native run `native-44ef2d1c731c476f84101b052126e0a5` completed 128 frames and 172,308,065 SYS cycles with 2,878,478 DDR commands. The original reference `native-420798b04be444c29f867aea732b88d1` and this candidate have 24 saved raster frames that compare byte for byte. The run retained 5,185,357 normal reads, 2,573,046 accepted writes, 12,792,856 DSP phase checks, 8,408,774 return captures, 2,085 cache patches and 5,167,437 physical return captures. The replay's sprite source phase check count is zero, so this run does not claim coverage of all sprite gameplay transfers.

The final QA memory receipt is `build/qa_reg_experiment/receipt.json`: paired Intel atoms cover 46 output-register segments, latency and collision behavior; the FG/BG transaction proof covers 840 consuming edges, including writes, RMW, pauses and drawing; serial equivalence covers 20,192 cycles. All 41 input bindings and 14 log bindings match the final sources. The refreshed legacy VRAM receipt `tests/graphics/evidence/vram-physical/vram-banks-baafa6785dc042e3b0134821f02a2851/receipt.json` passed AW14/SQ1 (56,631 cycles), the frozen 16-to-4 foreground bank oracle (95,539 cycles, 238 boundaries), and AW16/SQ0 (136,503 cycles). The final MC/cache bridge receipt `selector-stage-bridge-6ed13c42a17240b482ba2c7594689830` covers 183 real cache writes, 157 held memory words, 26 live SYS words, 16 late NVRAM changes and independent F/R pause/resume phases. These proofs preserve the logical storage, collision, bus and feature contracts; they do not substitute for routed timing closure.


## Routed candidate ea17: remaining paths and next reductions

All required source-bound functional and I/O families passed when this fit was qualified. The all-corner gate rejected it for setup and hold timing only. No assembly was performed.

| Metric | Measured | Target | Hard limit |
| --- | ---: | ---: | ---: |
| alms | 55.944% | 75% | 80% |
| labs | 85.254% | 85% | 90% |
| m10k | 84.991% | 85% | 90% |
| block_bits | 76.198% | 80% | 85% |
| dsp | 31.250% | 80% | 90% |
| peak_interconnect | 83.100% | 80% | 85% |
| average_interconnect | 34.400% | 50% | 60% |

The maximum H/V routing utilization is 83.1%; the preferred 80% routing target is still exceeded. LAB use is 3,573 of 4,191, only 11 LABs above the 85% target, while meeting the 90% hard limit. M10K use remains 470 of 553.

The worst eight-corner slacks in ns are setup -2.001, hold -0.010, recovery +0.911, removal +0.224, pulse_width +0.625.

The cache metadata path has left the worst SYS set. The remaining worst setup path is the registered BG1 RAM output to MC.READ_WORD[4], with -2.001 ns slack, 7.031 ns data delay, -0.960 ns clock skew and a genuine 6.250 ns relationship; the next paths feed MC.DATA_OLD. The MEM worst path is FG0.READ_DDR_R to DDR.busy_reg (-0.830 ns, six logic levels); related tag capture and write flags also fail. Two FG1 serial write-enable paths originate in COPY_ADDR and MEM_ROW, rather than the previously repaired COPY_STATE control.

Only the fast 1100mV/-40C hold report is negative: sprite DRAW_RAM_BANK_WE to FG1 synchronized draw enable (-0.010 ns) and BG1 WRITE_DATA[0] to three RAM port-A input registers (-0.010, -0.003 and -0.001 ns). These paths retain their ordinary zero-cycle hold relationship and must pass on the next full fit.

A further real DDR reduction was promoted after exact proof: local completion flags are reduced before adding each late read/write request, and each physical tag bank has a local capture enable with the original read-over-invalidation priority. The independent original-priority oracle passed all 4,194,304 complete busy combinations. The DDR test passed 3,080 writes, 2,176 reads and 176 read commands with unchanged command/busy cycles; the 45,000-cycle video comparison also passed. Receipt: tests/graphics/evidence/ddr-arbiter/ddr-arbiter-ab78881f8bb5400d8cf7ef132c0d15f6/receipt.json. Promoted DDR SHA-256: d6809443baf5c86f4830e3b994c1c031cb93dc95c4ba05aac3316727cadc065a. Routed benefit is not yet claimed.


### Routed candidate fc435: hard resources pass; setup remains open

The completed `bt-graphics-fc435ae0ce2e42d09a3d87e1c82ed412` snapshot includes the MC continuous word stage, narrow foreground serial-write-enable fix, and exact DDR late-request factoring. Production input hashes are frozen in that snapshot's `snapshot.json`. The complete map/fit/standard-STA process and independent eight-corner timing audit completed; no RBF assembly was run.

| Resource | Actual | Target | Hard limit | Result |
| --- | ---: | ---: | ---: | --- |
| ALMs | 23,540 / 41,910 (56.168%) | 75% | 80% | Target passes |
| Used LABs | 3,594 / 4,191 (85.755%) | 85% | 90% | Hard limit passes; 32 LABs above the integral preferred budget |
| Peak interconnect, maximum H/V | 78.4% | 80% | 85% | Target passes |
| Average interconnect, maximum H/V | 34.8% | 50% | 60% | Target passes |
| M10K blocks | 470 / 553 (84.991%) | 85% | 90% | Target passes |
| Block-memory bits | 4,314,880 / 5,662,720 (76.198%) | 80% | 85% | Target passes |
| DSP blocks | 35 / 112 (31.25%) | 80% | 90% | Target passes |

Horizontal/vertical peak routing is 54.5%/78.4%; horizontal/vertical average is 31.0%/34.8%. All hard resource limits pass. The core clock frequencies are preserved.

Eight-corner worst slacks are setup **-1.692 ns**, hold **+0.082 ns**, recovery **+1.324 ns**, removal **+0.178 ns**, and pulse width **+0.625 ns**. Full release eligibility remains false solely because the all-corner setup audit fails. Fresh mandatory hardware, functional, I/O and native proof inputs were accepted by the gate; no proof was waived.

The slow 1100 mV / 100 C setup paths identify the next physical work:

- BG0 depth output to `CPU.MC_MEM_WORD[16]`: -1.692 ns, 6.642 ns data delay, -1.040 ns skew; the same source to `CACHE_MEM_WORD[16]` is -1.676 ns.
- DDR `read_word_sel[0][2]` to the MC/CACHE word stages: -1.528/-1.527 ns; its path contains two DDR return LUTs and two BT return-selection LUTs before the SYS capture.
- CPU slot decode to BG `WE_N_M`: -0.556 ns; slot decode to foreground copy prefetch: -0.411 ns.
- Foreground `SREG_POS[8]` through the hole-address/tag comparator into DDR busy: -0.406 ns.

Moving selection work behind existing registers, preserving exact capture edges, is the next candidate direction. No additional timing exception, reduced clock frequency, or feature removal is justified by these reports.

The exact current 128-frame native run is `native-2bc5c638ab8844fc97ea2e6c32c1a43f`: 172,308,065 SYS cycles, 2,878,478 DDR commands, 5,185,357 ordinary reads, 2,573,046 accepted writes, 12,792,856 DSP phase checks, 8,408,774 return captures, 2,085 cache patches, and 5,167,437 physical return captures. All 24 saved raster images match the original `native-420798b04be444c29f867aea732b88d1` reference byte-for-byte. This boot replay does not replace separate gameplay and sprite source coverage.

The current CPU opcode proof `io-cpu_opcodes-03198196b9aa41b280f1c1d532c467b9` passed 6,291,456 complete control comparisons (65,536 opcodes x 32 field states x 3 condition profiles). Actual RAM proof `build/qa_reg_experiment/receipt.json` binds 81 current inputs: all six Intel-model address-width/serial-mode cases, both physical byte lanes, and actual consuming-edge read/write/RMW/pause and serial tests passed. The gate's grouped adverse-proof verification rejected 47 deliberately invalid proof variants and hashed 186 retained inputs.

Evidence: the snapshot's `resource_audit.json`, `timing_audit/`, `timing_receipt.json`, and `rbf_gate.json`; `tests/graphics/evidence/native/native-2bc5c638ab8844fc97ea2e6c32c1a43f/`; `build/resource_audit/final_mc_serial_gate_verification.json`. This snapshot is diagnostic evidence, not a timing-closed release.


### Routed candidate 59b2: ordinary held-word timing improved; residual paths remain

The exact combined DDR/RAM channel split, registered CPU phase predicates, and post-mux foreground/background QA stages were routed in `D:/vibes/fpga/temp/bt-graphics-59b2ab8e9b3e4647bd4be4c9322e6e27`. Its 193 synthesis inputs are bound by `snapshot.json`. The full fit and all eight timing corners completed. No assembly was run.

| Resource | Actual | Preferred target | Hard limit |
| --- | ---: | ---: | ---: |
| ALMs | 23,508 / 41,910 (56.092%) | 75% | 80% |
| Used LABs | 3,602 / 4,191 (85.946%) | 85% | 90% |
| Peak interconnect, maximum H/V | 79.4% | 80% | 85% |
| Average interconnect, maximum H/V | 34.9% | 50% | 60% |
| M10K blocks | 470 / 553 (84.991%) | 85% | 90% |
| Block-memory bits | 4,314,880 / 5,662,720 (76.198%) | 80% | 85% |
| DSP blocks | 35 / 112 (31.25%) | 80% | 90% |

Every hard resource limit passes; the LAB preferred budget remains 40 LABs below actual use. Horizontal/vertical peak routing is 55.9%/79.4%, and average is 30.6%/34.9%. No clock frequency or required feature was reduced.

The strict all-corner worst slacks are setup **-0.524 ns**, hold **+0.059 ns**, recovery **+1.309 ns**, removal **+0.177 ns**, and pulse width **+0.625 ns**. The slow 1100 mV / 100 C setup totals are SYS -15.222 ns and MEM -9.625 ns (total -24.847 ns). SDRAM shifted-clock setup is +0.032 ns and scaled HDMI setup is +0.051 ns, so those clocks require continued checks on every final route. New MC/CACHE held-word registers retain the ordinary 6.25 ns MEM-to-SYS setup budget, with no new exception.

The remaining slow-corner critical paths identify further physical work:

- DDR bank selector to `CACHE_DDR_WORD[6]`: -0.524 ns; the corresponding MC path is -0.498 ns.
- FG0 `MRT_EXEC` through ready selection into MC pending control: -0.433 ns.
- MC `DBUS_BE[3]` through CPU CAS, byte-enable reduction, and DDR next-busy logic: -0.367 ns.
- FG1 `SREG_POS[8]` through hole selection, address selection, and word decoding into DDR read-word metadata: -0.357 ns.
- FG1 draw bank mask through bank-mask reduction, byte/segment gating, and physical RAM write enable: -0.320 ns.

The promoted post-mux QA stages no longer appear among the worst SYS paths. Current physical qualification binds 239 inputs, including every full-depth FG/BG RAM partition and all six actual Intel-model address-width/serial-mode cases. The combined actual MC/CACHE DDR bridge proof covers 88,263 cycles, ordinary FG/BG reads, queued draw handoffs, full/byte DDR returns, cache placement, and pause/resume; its eight acceptance flags pass. The current opcode proof covers 6,291,456 complete control comparisons.

Native `native-cb16e0c977ec4c1da433129ced271a67` completed 128 frames with the same command/read/write/capture counts as the preceding candidate. A separate source/command/event-bound diagnostic comparison verifies identical applied initial-plus-128-frame input bytes and all 24 saved raster hashes against `native-420798b04be444c29f867aea732b88d1`. This run omitted the explicit journal argument, so it remains supplementary evidence: the release gate's journal check is retained and the next production replay must supply the exact reference journal. This boot replay does not establish whole-gameplay or MAME equivalence.

Evidence: the snapshot's `resource_audit.json`, `timing_audit/`, `timing_receipt.json`, and `rbf_gate.json`; `build/post_mux_qa_experiment/receipt.json`; `tests/graphics/evidence/ddr-split-bridge/ddr-split-bridge-cff53cd1e9934cd8857da7e14218400e/receipt.json`; `build/resource_audit/overlay_validation/native_cb16_stimulus_rasters.json`. This remains a diagnostic snapshot until setup closes and every final source-bound gate passes.


## Frozen request-predecode route 34cbc: resource pass, timing rejected

The frozen production snapshot `D:/vibes/fpga/temp/bt-graphics-34cbc75e811d4ef3baf8e9173f9f9b01` completed MAP, FIT, standard STA, the resource audit, and the full eight-corner timing audit. No assembler was run. Its `snapshot.json` records 193 inputs; the current-source RBF gate passed functional, native, physical-model, resource and IO checks but rejected four timing conditions.

| Resource | Measured | Target | Hard limit |
| --- | ---: | ---: | ---: |
| ALMs | 23,505 / 41,910 (56.08%) | 75% | 80% |
| LABs used | 3,604 / 4,191 (85.99%) | 85% | 90% |
| Peak interconnect, higher H/V | 79.2% | 80% | 85% |
| Average interconnect, higher H/V | 34.0% | 50% | 60% |
| M10K blocks | 470 / 553 (84.99%) | 85% | 90% |
| Block memory bits | 4,314,880 / 5,662,720 (76.20%) | 80% | 85% |
| DSP blocks | 35 / 112 (31.25%) | 80% | 90% |

All hard resource limits pass. LAB use is 42 LABs above the 85% target. The M10K count remains 22 below the original 492-block fit; the framebuffer capacity, CPU, audio, graphics features and established clock frequencies remain covered by their preservation proofs.

Across all eight corners the worst setup is **−0.939 ns**, hold **−0.004 ns**, recovery **+1.271 ns**, removal **+0.175 ns** and pulse width **+0.625 ns**. Slow 1100 mV / 100 C setup TNS is −22.245 ns on SYS and −12.136 ns on MEM (−34.381 ns combined). This route does not close timing and must not produce a release RBF.

The largest physical SYS setup failures are the sprite packet-write flag to `MC_WRITE_PEND` (−0.939 ns), foreground serial-write state to `MC_SCRREF_WAIT` (−0.424 ns), and CPU barrel-shifter/ALU output to register-file write data (−0.421 ns). The DDR return-selector flattening improved its former return-data bottleneck; it is absent from this route's top ten SYS paths. The new worst MEM path to the live DDR `read_bank_sel` register (−0.638 ns) exposed an endpoint-list omission in the existing qualified metadata constraint. The register survived synthesis even though output selection was flattened; restoring its original endpoint membership is a constraint-identity correction, with unchanged budgets. Held CPU return-capture registers retain their ordinary 6.25 ns checks.

The remaining foreground read path to DDR `read_return_sel` is −0.546 ns: the foreground read flag crosses the hole-selection and CPU address-class network before reaching DDR selector enable. A private split of foreground and CPU read branches now passes 524,288 exhaustive cases compiled from the literal board/top expressions and the actual FG selection/read predicates. Candidate MAP and subsequent routing must establish its physical effect before promotion. Sprite/foreground same-edge ready predictors and CPU register-file write-source factoring are separate private candidates under functional and mapped-logic qualification.

The −0.004 ns hold violation occurs only in the Fast 1100 mV / −40 C corner, from the SYS blitter's `DRAW_RAM_BANK_WE[0][15]` to FG0's existing MEM ingress `DRAW_RAM_BANK_ACTIVE_M[3]`; measured data delay is 0.526 ns and clock skew 0.360 ns. It remains a real routed hold requirement.

Fresh native receipt `tests/graphics/evidence/native/native-048fecd9ea65435aa39333c63081794b/receipt.json` passes 128 frames with the original recorded input journal: 172,308,065 SYS cycles, 2,878,478 DDR commands, 5,185,357 reads and 2,573,046 accepted writes. All 24 saved raster comparisons pass. Full current CPU/MC, DDR byte masks, foreground, sprite packet, Intel memory-model and regression proofs are source-bound in `build/resource_audit/functional_readiness_34cbc_final.json`; this does not claim full-game MAME or hardware equivalence.

The predicted 32-bit DDR return-register candidate is rejected despite exact cycle and million-step state equivalence: MAP adds approximately 411 estimated ALMs and creates a six-LUT MEM D cone. Private MC ready/cause mirror variants are also rejected because they preserve the same primary ready-to-pending depth while adding logic/registers. Neither candidate was promoted.

Recovery handles: the snapshot's `resource_audit.json`, `timing_audit/`, `rbf_gate.json`; root route driver `build/resource_audit/route-runs/route-77c515215d9744298d7a205832d33542`; read-split proof `build/resource_audit/ddr-read-split/evidence/bt-ddr-read-split-1cf66b30b5cc48df9fdf0523ecf21cd6/receipt.json`. No timing-closed RBF exists for this batch.


## Joint ready and CPU fit e378: all eight corners, no assembly

Snapshot: `D:\vibes\fpga\temp\bt-graphics-e378d0047c7a49c7bf516c5c75e2d062`. Canonical ready and flat CPU RF batch; foreground readiness source1d31 retains an unused-helper strict lint failure. The private cleanup and subsequent timing candidates are not included in this fit.

The original 22 M10K savings remain:470/553. All hard resource limits pass. Actual fitted resource metrics:

```json
{
  "alms": {
    "used": 23381,
    "capacity": 41910,
    "percent": 55.78859460749224,
    "report_label": "Logic utilization (in ALMs)",
    "target_percent": 75,
    "hard_limit_percent": 80,
    "meets_target": true,
    "meets_hard_limit": true
  },
  "labs": {
    "used": 3586,
    "capacity": 4191,
    "percent": 85.56430446194226,
    "report_label": "Total LABs:  partially or completely used",
    "target_percent": 85,
    "hard_limit_percent": 90,
    "meets_target": false,
    "meets_hard_limit": true
  },
  "m10k": {
    "used": 470,
    "capacity": 553,
    "percent": 84.99095840867993,
    "report_label": "M10K blocks",
    "target_percent": 85,
    "hard_limit_percent": 90,
    "meets_target": true,
    "meets_hard_limit": true
  },
  "block_bits": {
    "used": 4314880,
    "capacity": 5662720,
    "percent": 76.19801084990958,
    "report_label": "Total block memory bits",
    "target_percent": 80,
    "hard_limit_percent": 85,
    "meets_target": true,
    "meets_hard_limit": true
  },
  "dsp": {
    "used": 35,
    "capacity": 112,
    "percent": 31.25,
    "report_label": "Total DSP Blocks",
    "target_percent": 80,
    "hard_limit_percent": 90,
    "meets_target": true,
    "meets_hard_limit": true
  },
  "peak_interconnect": {
    "percent": 80.2,
    "reported_percentages": [
      57.8,
      55.9,
      80.2
    ],
    "target_percent": 80,
    "hard_limit_percent": 85,
    "meets_target": false,
    "meets_hard_limit": true
  },
  "average_interconnect": {
    "percent": 35.2,
    "reported_percentages": [
      32.6,
      31.7,
      35.2
    ],
    "target_percent": 50,
    "hard_limit_percent": 60,
    "meets_target": true,
    "meets_hard_limit": true
  }
}
```

The missing detailed fit report was exported as raw Quartus17 Fitter report API panels. Before/after QPF/QSF and fitted database hashes remain identical. The exported panels were installed byte-exactly; no placement rerun. Provenance: `D:\vibes\fpga\temp\bt-graphics-e378d0047c7a49c7bf516c5c75e2d062\resource_report_export\audit_receipt.json`.

Eight-corner worst slacks (ns): `{"setup": -0.55, "hold": 0.033, "recovery": 1.118, "removal": 0.18, "pulse_width": 0.625}`. IO minima (ns): `{"sdram_input_setup": 0.032, "sdram_input_hold": 0.925, "sdram_output_setup": 2.616, "sdram_output_hold": 4.006, "hdmi_video_setup": 0.04, "hdmi_video_hold": 0.951, "hdmi_audio_setup": 197.013, "hdmi_audio_hold": 118.415}`. Negative setup remains; no RBF assembly was run. Gate failures: `["all-corner audit failed", "held-word capture endpoints, ordinary6.25ns relationship, or timing failed", "setup has negative slack: -0.55", "functional/phase proof missing or stale: foreground-ddr"]`.

Native replay `tests/graphics/evidence/native/native-f14b07de40f14f98b3edd53cc4c9ddbe` passes128 frames and all24 recorded rasters against native420798. It covers172308065SYS edges,2878478DDR commands,5185357reads and2573046accepted writes. Boot replay does not establish full gameplay or sprite-source-phase coverage; independent sprite and bridge proofs remain required.

Remaining routed paths include IC_MATCHES→ALU_B operand extension−0.550ns, foreground COPY_STATE→DDR selector−0.353ns, COPY_ADDR[5]→tag match−0.350ns, and sprite mirror nibble→draw bank mask−0.247ns. These are being addressed with private same-edge or combinational transformations, not relaxed clock periods. MC_WRITE_PEND clock-enable disabling was rejected: its late ready path moves from2LUTs intoENA to3LUTs intoD and the current ready-path bottleneck is already removed.


## Five-file foreground, sprite and DDR batch: snapshot7f279, qualification in progress

The guarded batch installed exact FGbb629, DDRb902, SPR480442, blittera5ee and BT5897. CPUebd, top425 and SDC7966 remain unchanged. Complete prior file bytes and mutation receipts are retained at `build/resource_audit/before/fg-sprite-ddr-8e1fc90f9b854b42a681808bc096afde/promotion_manifest.json`. Snapshot: `D:/vibes/fpga/temp/bt-graphics-7f279bab89e2412ca9448aec0cab4c20`. No RBF assembly has run.

The foreground change removes the unused-helper lint failure, registers HOLE_RD at its original MEM edge and registers only HOLE_A[5] at the same edge. All18 address bits and48 states passed546065 official mapped checks over182007 cycles, including150000 arbitrary cycles and43 asynchronous resets. The address output becomes directQ; newFF D depth3LUT, with no wide carry path. PerFG cost over shipping1d31:6ALUT and2FF, unchanged memory geometry. Pure source and proof ancestry1d31→cleanup3c→HOLE27cc→addressbb remains archived in `build/fg_ready_next_experiment/final_hole_a5/receipt.json`.

The sprite mirror retains the exact address and twoMEM data latency, moving the64-bit output stage to externalFFs and capturing16 nibble-nonzero flags alongside it. Actual nibble metadata is wired to the optional blitter predicate. The original readiness/packet/memory-owner state machines remain byte-exact. LogicalSPR compared23703444 defined bits; mapped mirror compared2724480 defined bits with681120 NZ checks,10940 collisions and1920 truly identical writes; mapped wholeblitter checked402114 cycles and all103 outputs. Source/physical proofs: `build/resource_audit/sprite_nonzero_v2/publisher/receipt.json` and its fresh normalized current receipt. Target data-to-strobe depth5→4LUT and data-to-draw-data3→2;14estimatedALMs/80logicFF added, memory geometry unchanged. These are MAP measurements, not routed slack claims.

The DDR change adds three identical16-bit selector replicas at the existing clock edge, one per additional return byte. Init/reset/read/write-invalidations and hold priority are identical by source substitution; each byte retains all16rbuf terms and does not assume one-hot selectors. Paired complete-controllerMAP: selector fanout33→9, outputdepth3LUT unchanged, FF1656→1704 and combinational cells1647→1734. All64 selector enables arevcc and use the original clock. The raw candidateb902 has CRLF;8c9c is only its normalizedLF hash. Immutable before2817 and pure exact reconstruction are retained at `build/resource_audit/ddr-return-lanes-v2/final/receipt.json`; independent review at `build/resource_audit/ddr-return-lanes-independent-review/receipt.json`. No new clock, edge or return latency is introduced.

Fresh canonicalcontrollerde392 passes3080writes/2176reads/176commands with all-cycle equivalence. Boundaryc492 passes1048576write-mask cases and10240source-word cases; legacycache4f630 passes. CurrentstrictFGDDRa3e38 passes196608clearwrites/128maskedwrites/512copybytes. CurrentMC/DDRbridge8d39 passes88263cycles/5957reads/11918writes/all2048fields; spritepacket591f passes512packets/528completions and page09649 passes100000cycles. The promoted fullnative128 replay7cafa5 passed172308065SYS cycles and2878478DDR commands, with the same5185357reads/2573046writes/8408774returncaptures/2085patches/5167437physicalreturns as the reference. All24 saved rasters match native420798 exactly (`tests/graphics/evidence/native/native-7cafa5a023d64cac92b01040ce699e3b/raster_comparison.json`). Independent exact-gate slice b25294 accepts all20 non-native functional/preservation roles and all5IO proof families against snapshot7f279 and frozen gateeeb5ba. Fit and eight-corner timing remain pending; this chapter does not qualify a release. Sprite-source phase is0 in the boot replay; independent sprite proofs remain mandatory.

Two private CPU extension candidates were rejected despite34703008 exact operand comparisons each. Fullword pre-extension deepened the complete mappedCPU path12→14LUT at+278estimatedALM/+365ALUT; sign-only retained12LUT and the actualIC_MATCHES40 path11LUT at+163estimatedALM/+304ALUT. CPU source remains unchanged. Same-edge AS/EO instruction-decode mirrors are being investigated separately.
