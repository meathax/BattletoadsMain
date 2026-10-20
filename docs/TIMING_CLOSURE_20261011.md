# Timing closure implementation, 11 October 2026

The requested audit items 1, 2 and 4 are implemented. The system clock remains
80 MHz, memory clock 160 MHz, and SDRAM sample clock 80 MHz with its existing
8.75 ns phase. Existing qualified internal clock relationships are preserved.

The selected private candidate, v25, passes setup, hold, recovery, removal and
pulse-width checks at all eight operating conditions, with zero unconstrained
paths. Its source, replay and release gates are described below.

* `bt_video_ddr` no longer contains the unused rotation FIFO, rotation head or
  rotation arbitration. The memory command register, delayed reset and one-entry
  skid buffer retain their original interface cycles and priorities.
* The wrapper now instantiates core-local `bt_video_mixer` and `bt_scandoubler`.
  Ordinary 2x line repetition retains the native 24-bit pixels, gamma, freeze,
  blanking and sync pipeline. It replaces the disabled HQ2x pixel-block storage.
  The upstream `sys` framework is unchanged.
* Foreground address trackers capture preserved local cache metadata on the
  original edges. DDR return selectors use equivalent local predecoded terms.
  Normal execution retains its interface cycles, CPU phases and game raster.
* The remaining foreground copy-word control uses local byte-pair replicas.
  Sprite serial-select logic is factored into its original address predicate.
  The CPU captures a one-hot ALU field-size selector alongside its existing
  instruction/state updates; status and pixel-size fields remain live.
* The CPU line decision now uses the equivalent predicate for each ALU operation,
  removing the shifter and global zero-detection mux from that control path.
  Foreground hole and copy-address groups use local flag/history replicas and
  equivalent priority selection, with full-width carry before address slicing.
* CPU shift flags use equivalent prefix/threshold predicates. Foreground
  transfer decode uses the original address predicate directly. The final RAM
  changes register each foreground serial segment enable and the background
  ordinary-port address on their existing edges; local foreground serial
  history removes a shared priority route. Physical RAM geometry, modes,
  output-register edges and byte masks retain their original behavior.
* A palette predictor supplies the early CPU return stage with the value that
  the existing palette register will capture. Pause completes the current R
  edge and resumes with F. NVRAM upload waits for the completed closing write
  and an acknowledged CPU halt. Preparatory memory snapshots remain current
  during EN holds; architectural CPU/bus updates remain EN-gated.

## Functional evidence

The frozen DDR bridge oracle checks 565,530 cycles, all 65,536 four-cycle control
sequences, 22,078 ordered commands, 4,096 full-rate commands, prolonged stalls,
full-skid recovery and all byte masks/burst values. Its scope assumes the removed
rotation producer remains inactive, as it does in the current wrapper.

The ordinary video path matches the real upstream mixer with HQ2x disabled over
32,896,000 clock comparisons and 5,046,272 visible 24-bit pixels. The cases cover
native and doubled output, forced/CRT selection, gamma, freeze, phase offsets and
fractional pixel enables. Separate four-state and Intel Quartus 17 primitive RAM
checks cover 400,000 cycles, including tail forwarding and old-data collisions.

Foreground and DDR equivalence use immutable baseline commit
`6b66897664bda6cace6da60752fe57f5dc4f3e76`. All three focused suites pass:
260 foreground transactions with 83,411 comparisons; 3,080 writes and 2,176 reads
through the compared controllers; and the shipping FG/DDR path with 196,608
reset-clear writes, 128 masked writes and 512 copy bytes under backpressure.
The platform test also passes both 32 MHz CPU phases, the 10 MHz pixel enable,
all 8,192 NVRAM bytes and the wrapper/MRA integration assertions.

The expanded foreground proof compares the complete 64-bit copy word every
clock, including eight restart/capture collisions, eight RAM abort/capture
collisions, resets at collect, DDR wait abort and clear-only restart. Local
copy-word controls use the existing state and unaligned replicas on their
original capture edges. A separate source-bound 16,384-case proof shows the
simplified sprite serial-select predicate preserves the original RAS input.

The CPU selector proof compares the committed decoder over 50,331,648
opcode/state/flag combinations and 25,165,824 live field-size tuples. Its
131,072 real control clocks cover reset, interrupt, stalls, enable/CE holds,
both instruction fetch halves and all immediate-word load branches. Both
compile and run pass against immutable commit
`0ecfb2fa6075ec2aef7d19ea796b0771dff8e5b3`. The source-bound receipt is
`tests/graphics/evidence/cpu_alu_fsi_20261011_v3/receipt.json`. The new register
joins only the existing qualified CE_R pool and its identity/stability guards.

The `8f048ee`, `b537263` and private CPU-shift/transfer-decode sources each pass
the 128-frame real-CPU board replay and match all 24 retained raster captures
against the same frozen reference, ROM and input journal. The latter receipts
are `tests/graphics/evidence/native/native-ee7bfa3bc6ff4586b472b33e95b10773`
and `native-6cfa02c52c4c44189c5bce206fa352f0`. These intro replays exercise
172,308,065 SYS cycles and 2,878,478 DDR commands each; they do not exercise
sprite-source requests or constitute whole-MiSTer/MAME/hardware qualification.
The complete final candidate requires its own exact replay.

The line predicate matches immutable `8f048ee` over 9,469,952 ALU comparisons
and 32,768 complete pixel/line state cycles, including all 16 ALU encodings,
all eight ADDXY flag/IC7 tuples, reset, enable holds and stalls. It leaves
all ALU results and flags unchanged. Receipt: `build/cpu_line_gz_promoted_v1`.

The local foreground address controls also match immutable `8f048ee`: 262
transactions and 107,750 full-state/interface comparisons check every bit of
the hole address, next copy address and copy word. Directed coverage includes
13,036 RAM and 309,223 DDR transfer cycles, completion/restart collisions,
103 mode changes, two aborts, 202 active resets, 757 history transitions and
920 hole-select changes. The actual FG/DDR workload passes again. Receipt:
`build/item4-equivalence-7c7a366fa8ec47b0bc6416ceb07e4b0f/receipt.json`.

The final foreground serial controls match immutable `b537263` over another
262 transactions and 107,750 complete state/interface comparisons, including
every bank's RAM capture pins, 1,024 segment-enable truth cases, local history,
18-bit next-address carry, restart/abort/collect priorities and reset collisions.
The shipping DDR workload again completes 196,608 clear writes, 128 masked
writes and 512 copy bytes. Receipt:
`build/item4-equivalence-c68d2f635c4f4ae2b1e3a7119f0fc2ce/receipt.json`.
The appended optional RAM ports retain the original positional API.

The background address register matches the original RAM capture pins over
1,769,915 comparisons at six CPU/MEM phase offsets, with 148,682 masked writes,
384 active resets and 13,824 refresh starts. Receipt:
`build/bg_port_address_b537_v1/receipt.json`.

CPU shift flags have a universal Boolean equivalence proof, plus 1,082,368
function, 9,469,952 ALU, 65,536 operand/status and 32,768 pixel-state comparisons.
The palette predictor passes 1,507,339 cycles, including writes, reset,
late-owner masks and 54,007 palette changes with EN low. Promoted helpers are
`tests/run_bt_cpu_shift_flags.py` and `tests/run_bt_palette_early.py`.

The actual board pause bridge passes 995,609 cycles and all 40,960 bounded
request patterns across five phase positions and OSD/NVRAM requests. Its
NVRAM proof checks five complete 8,192-byte uploads, 20,480 restore words,
closing writes, reset/download/manual-upload collisions and registered-read
ownership. Save-to-halt is at most three SYS cycles; upload is at least one
SYS cycle after the final write. Receipts are in
`build/pause_nvram_b537_v2/{phase_proof,nvram_proof}/receipt.json`.

The complete memory-return stage passes production and alternating clock
profiles against an immutable full memory-controller oracle, including EN
holds. Each checks the original 2,048 field cases plus 4,096 reads over all
64 encoded sizes, 32 alignments and two banks, with 1,024 resume-at-F cases.
All byte-enable, owner, tuple and two-SYS-clock age checks remain active on
admitted consumers. The full CPU return checker now qualifies R with EN,
matching the architectural consumer; its operands and failure check remain
unchanged. Complete final-source bindings are renewed separately.

Fresh field-helper proof uses complete immutable Git blobs before extracting
the original byte-enable and extension functions. It passes 2,048 byte-enable
and 33,280 extension comparisons; opcode proof passes 12,582,912 complete
control comparisons. Helpers are `tests/graphics/qualify_bt_current_fields.py`
and `tests/graphics/qualify_bt_current_opcode.py`. Their scope is the compiled
functions/control, with whole-stage behavior checked by the separate proof.

Reproducible helpers are in `tests/verify_platform_features.py`,
`tests/verify_bt_video_ddr_memory.py`, `tests/run_bt_ordinary_doubler.py`,
`tests/run_bt_ordinary_sd_native_ram.py` and
`tests/graphics/qualify_item4_equivalence.py`, `tests/run_bt_cpu_line_gz.py` and
`tests/graphics/qualify_fg_local_controls.py`. Retained receipts and logs are under
`build/bt_video_ddr_memory`, `build/item4-equivalence-*` and
`tests/graphics/evidence/bt_ordinary_doubler`. These are simulation proofs; they
do not claim complete MiSTer platform, MAME or physical hardware qualification.

## Native synthesis and remaining sign-off

The corrected integration passes Quartus 17 synthesis. Its scandoubler main
stores are two 512x24 inputs and one 1024x24 interleaved output: 49,152 embedded
bits. The short tails map to 768 storage flip-flops, giving 49,920 pixel-storage
bits overall, versus 124,800 in the former HQ2x buffers. The completed initial
integration fit uses 458 M10Ks, 22,462 required ALMs and 3,380 LABs, versus the
fresh baseline's 469 M10Ks, 23,090 required ALMs and 3,512 LABs. Its mixer uses
eight M10Ks (seven pixel stores and one gamma store), with zero HQ2x instances.

The fresh baseline misses setup by -0.510 ns; the initial integrated fit improves
this to -0.348 ns across all eight operating conditions. Its remaining routed
paths identify foreground copy-word control, CPU field-size decode to ALU
operands, and sprite serial-address decode. These results do not qualify an RBF.

The completed `8f048ee` fit checks all eight operating conditions with zero
unconstrained paths. Setup still fails by -0.461 ns in line-decision/address
control, while hold (+0.061 ns), recovery (+0.467 ns), removal (+0.343 ns) and
pulse width (+0.625 ns) pass. It uses 22,530 required ALMs and 458 M10Ks. An
isolated seed-2 experiment still fails setup by -0.438 ns; placement tuning
alone is insufficient. The subsequent source fixes require a new complete fit.

The completed `b537263` fit improves the worst setup result to -0.212 ns,
identifying the foreground serial segment write enable. The private CPU-shift
and transfer-decode fit improves it to -0.166 ns, identifying the background
RAM address/segment write-enable path and smaller foreground serial/DDR paths.
Both have zero unconstrained paths. Their minimum hold results are +0.045 ns
and +0.003 ns respectively; neither qualifies an RBF. The complete 144-source
candidate `build/timing_closure_20261011/integrated_v9_private` completes all
eight corners at -0.231 ns setup, +0.062 ns hold, +1.161 ns recovery,
+0.263 ns removal and +0.625 ns pulse width, with zero unconstrained paths.
It uses 22,626 ALMs, 24,359 registers and 458 M10Ks. Its exported negative
setup paths are CPU address-to-VRAM request decoding and sprite owner-to-DDR
write-data selection. Its exact 128-frame replay `native-c2774075` completes
172,308,065 system cycles and all 24 reference raster comparisons pass.
This remains an intro-board replay, with no exercised sprite-source checks.

The next correction publishes four address classes on the existing DBUS_A
load edge, with identical reset, load priority, enable and hold behavior.
Foreground and background consumers reuse those bits with the original live
code/display bits. The two phase-profile proofs retain 360,673 immutable
full-MC bus/final comparisons and add 360,675 class checks; each also covers
65,536 complete decoder combinations. Independent source-parsed comparison
checks every selector and request/transfer pin. Physical FG/BG/BT_mem source
and Intel collision contracts are unchanged.

The parallel DDR correction captures all four raw words and their owner on
the original write-prepend acceptance edge, selecting the captured word for
the existing cache and DDR consumers. The standalone full-controller proof
passes 37,204 state/metadata comparisons, 2,560 acceptance checks, 34,619
holds, all 60 owner/nonzero-byte-mask combinations, resets, backpressure and
simultaneous I/O/cache/DDR events. Default serial mode is compared separately.
The original named multicycle amounts and qualified source groups remain
unchanged; DATA_OLD remains excluded and owner registers remain single-cycle.
Actual CPU operand reload age is a separate fresh-native obligation.

The complete private candidates retain the original 80 MHz SYS and 160 MHz MEM
clocks and timing budgets. The v10 fit misses setup by 0.277 ns. The v11 fit's
platform I/O selector initially rejects an actual fitter-created SCLK duplicate;
a strictly scoped selector repair recognizes that duplicate without changing any
timing budget. Fresh analysis of the v11 database then reports a 0.109 ns setup
miss, 0.058 ns hold margin and zero unconstrained paths at all eight corners.

The v12 registered VRAM requests remove the old CPU address-decode path to the
foreground request inputs. Its all-corner fit reports setup -0.349 ns and hold
+0.012 ns; the new worst path routes foreground serial data to a RAM write port.
The v13 local copy-mode registers use the original capture edge and data. Its
all-corner fit improves the worst setup result to -0.150 ns, with +0.080 ns hold,
+0.710 ns recovery, +0.255 ns removal, +0.625 ns minimum pulse width and zero
unconstrained paths. The worst path is now CPU ALU_B to WSTART; foreground write
enable routing also remains slightly negative. These failed candidates are
retained as evidence and do not authorize assembly.

The exact v12 native replay completes 128 frames and 172,308,065 SYS cycles.
All 24 retained raster captures match the accepted reference. Actual MC reload
probes verify 171,038,303 loads, with minimum EXT/FS/BA ages of five MEM cycles
and BUF age of three. Its 2,573,046 accepted raw write captures and launch-age
checks pass. This replay covers the intro and does not exercise sprite-source
write captures or constitute MAME, full-platform or hardware qualification.

The core-local platform I/O contract qualifies the active I2C and optional USER
I2S paths and scopes asynchronous status/HPS/analogue-pad exceptions to the
source-bound inactive interfaces. The MCP23009 bus uses the datasheet's 100 kHz
standard mode; only expander initialization and GPIO polling slow down, with
about 1.7 kHz polling still measured in the controller proof. Game clocks and
game timing do not change. All 500 starting accumulator phases, 1,500 bus
transactions, initialization, polling and injected NACK/retry pass. The stated
board loading and edge-rate envelope remains a physical qualification limit.

A disposable copy of the older fit validates constraint syntax and endpoint
coverage: every fresh corner report has zero unconstrained ports/paths and the
forwarded USER I2S clock. That copy deliberately retains the older 500 kHz
compiled database, so it cannot qualify the final image. The diagnostic helper
records this mismatch and refuses to accept it for physical pad sign-off.

The exact `8f048ee` fit subsequently passes the separate physical pad gate:
176 native paths cover all six input endpoints and three output source/pad
pairs, setup and hold at all eight corners. Worst input data delay is 7.095 ns
(100 ns bound), capture-clock arrival 6.027 ns (50 ns), SCL clock plus data
13.860 ns (20 ns), SDA 12.927 ns (50 ns), and earliest output 5.033 ns (1 ns
minimum). Receipt: `build/platform_io_v6_exact_20261011/physical_pad_receipt.json`.
Its release timing acceptance remains false; this gate will be repeated against
the accepted fit and completed release database.

`scripts/timing_snapshot.py` freezes source and hashes into isolated workspaces
with RBF generation disabled for partial checks. Baseline and integration fits
use original settings through the reviewed QuartusFast frontend. The retained
10 October fit predates its source commit and cannot qualify this implementation.

## Selected final candidate

The selected source is
`build/timing_closure_20261011/bg_hold_v25_private-snapshot.json`, SHA-256
`7799e521f7e02bae511dbd8fdf2637cac1c9daa311aa9f726f1ec97ca6243ddb`.
It retains all 144 project inputs. The native compiler uses the same 134 active
inputs and ten individually pinned support-file omissions. The QSF settings,
clock frequencies, phase, multicycle amounts and accepted timing budgets remain
the original values. Each source transformation retains its complete inverse
and its own immutable parent and proof receipts.

The remaining setup fixes keep their original consumer edges. CPU zero and
pixel predicates use equivalent operation-specific logic. Foreground transfer,
completion and DDR write-start controls use local copies of the original data
and history. The background scroll adder operates between the two existing MEM
capture edges, after capturing the raw operands on the first edge. It adds no
architectural pipeline stage and preserves reset and four-state coercion.

The sprite path captures both raw foreground words in 128 local registers on
the original MEM edge. Its existing live foreground-priority mux supplies the
CPU packet register on the original SYS edge. Eight hard RAM mirrors provide
local foreground bank reads; different address permutations are pure wiring,
applied to both RAM ports. The actual fitter uses sixteen distinct M10K
locations for these mirrors. Registered outputs, old-data collision modes,
byte masks and packet edges retain their original behavior.

The final background source routes write-data bit 15 through a kept identity
LCELL before the RAM input. The shipping Quartus 17 primitive and complete
background twins check known values, X/Z values, coincident edges and off-edge
resets. No register or clock edge is added. Compiler output-wire protection
assignments are retained; primitive instance-name removal alone does not prove
physical cell removal. The exported path reports do not establish connected
LCELL retention, so no physical cell-count claim is made.

The actual accepted partial fit is
`v2-20261011-121806-53332-turbo_fit`, using original settings. Its minimum slacks
over all eight operating conditions are:

| Check | Minimum slack |
| --- | ---: |
| Setup | +0.030 ns |
| Hold | +0.087 ns |
| Recovery | +1.210 ns |
| Removal | +0.259 ns |
| Minimum pulse width | +0.625 ns |

There are zero unconstrained paths. The default four-model per-clock reports
show SYS setup +0.047 ns / hold +0.099 ns and MEM setup +0.211 ns / hold
+0.087 ns; the table above is the separate, complete eight-condition gate.
The fitter reports 23,002 ALMs, 24,735 registers, 3,374 LABs, 474 M10Ks and
4,264,704 block-memory bits. The reviewed startup critical warnings retain
their exact baseline text and counts: 18010 occurs 53 times and 18061 once.
The existing inferred-latch and ignored-max-fanout reports are reviewed;
the previous congestion and timing-failure warnings are absent.

The independent report and warning receipts are
`build/timing_closure_20261011/v25_warning_review/final-review-r1.json` and
`warning-delta-addendum-r1.json`. Fresh physical pad diagnostics of this exact
fitted database pass all eight conditions with zero budget failures:
`build/timing_closure_20261011/v25_platform_pad_physical_r1/physical-pad-receipt-r1.json`.
Those diagnostics use disposable database copies and do not alter production
constraints. The same pad gate must run again on the complete release database.

The current-source composition receipt is
`build/final_v25_current_input_qualification_r1/receipt.json`. Its callback,
`tests/graphics/bind_bt_final_bg_hold_inputs.py`, verifies all 144 sources, the
exact final background inverse, 143 unchanged parent inputs, the complete
shipping-primitive proof and the inherited source and component proofs.
The separate `tests/graphics/bind_bt_v25_native_replay.py` release gate requires
a fresh exact-source 128-frame replay, all 24 raw raster comparisons, the actual
compiler input list and argv, active assertions, and the frozen ROM/input journal.
This remains an intro-board replay; directed component proofs separately cover
sprite writes and RAM collision behavior. Whole-platform, MAME and physical
hardware qualification remain separate scopes.

Integration requires the accepted eight-condition fit and the strict current
native callback before writing production RTL. The committed sources then feed
an isolated full release workspace. Complete compilation and assembly follow
the shared FIFO, preserve the original pre/post-flow hooks, and recheck all
eight conditions, warning/resource limits, source inventories and physical pads
before collecting a new RBF. A partial fit or component proof alone cannot
qualify a timing-closed RBF.
