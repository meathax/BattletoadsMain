# Timing acceptance

Timing is open. The authorized work is to close every required corner, then
review and safely optimize the core and suitable donor implementations, and
qualify the final result again. No RBF/SOF assembly is authorized or run.

The flow uses frozen source copies and runs only Quartus 17 analysis/synthesis,
fitting and TimeQuest. The default TimeQuest process can succeed with negative
slack; it is not an acceptance result. timing_run.py and timing_audit.tcl
recreate the routed timing netlist separately for all eight available Cyclone V
models, with explicit voltage/temperature and forced annotation. This avoids
the HPS annotation failure encountered when reusing a netlist.

verify_timing.py requires successful fitting, nonnegative setup, hold, recovery,
removal and pulse-width slack, all corner and external-interface inventories,
consistent constraints, and unchanged fitted/workspace source hashes.
Diagnostic SDC overrides cannot pass this gate. eligible_for_rbf is a technical
result; it does not grant permission to build an RBF.

## Current evidence

The last complete eight-model snapshot is
bt-graphics-e9471f8829f04ef3ae4d27368eb0fc1e: setup -2.986 ns, hold +0.077 ns,
recovery +0.731 ns, removal +0.175 ns and pulse width +0.625 ns. Its fit uses
20,761 ALMs, 21,161 registers and 537/553 M10Ks. Negative setup paths include
CPU register selection/operand preparation, 160 MHz memory paths and one
internal HDMI path. This snapshot remains a failed baseline, not acceptance.

The earlier bt-graphics-c036dac59690474faff563209eafc766 snapshot contains a
superseded SDRAM receive edge and hold constraint.
Its previously passing SDRAM phase receipt used a model that started CL2 data
one clock late. Those results are retained as failed/diagnostic history, not
current external-memory qualification.

The corrected Micron model starts CL2 data after the first clock following
READ and explicitly checks active DQ drive, including the earliest 1.8 ns
no-load data hold at single-word burst release. The controller captures in
state 5 and publishes through the sys bridge at the original state-6
completion edge. The intervening sys edge has its bridge enable low. The
16.25 ns enabled transfer is checked for every read and constrained only
between the named 16 receive and 16 bridge registers. External hold checks
the first following SDRAM edge, without adding another period.

The corrected SDRAM receipt is
 tests/graphics/evidence/io-phase/io-sdram-954a0d4e3942412dbf47e6f45b2ebc7f/receipt.json.
It checks 768 reads, 769 writes, 1,536 values, 768 active receive windows and
768 bridge intervals, with unchanged six-clock completion. A frozen late
receive candidate fails all 768 active-window checks; the original controller's
data agrees with the corrected model. The corrected SDRAM input setup and
hold pass all eight models in bt-graphics-4d6d72fbf152467689cb1ab94771e44c,
with minima +0.013 ns and +0.929 ns. Internal setup remains open.

Opcode comparisons are captured with IC on its existing instruction-load edge.
The mechanical conversion preserves every case priority, state and condition.
predecode_opcode.py folds 28 upper-word cases and 149 labels into 124 complete,
exclusive instruction classes against the frozen decoder. The remaining
low/full-word case and all state/condition logic are preserved. The current
candidate computes class controls in parallel and selects with AND/OR logic.
The miter compares the complete control word for
65,536 opcodes, 32 states and three condition profiles (6,291,456 checks).
Native assertions independently require instruction identity and CE_R ownership.

native-b54d83f5ad0746ab92de06442dc0997c completes 128 frames, 172,308,065 system
cycles and 2,878,478 DDR commands. All 24 retained rasters match the prior
qualified replay. It includes the corrected SDRAM source and folded decoder,
and predates the parallel control selection and cache/ready changes. Those
candidates are being requalified. Native RAM/DDR/sample-ROM adapters are
regression models, not whole-MiSTer or MAME lockstep validation.

## Constraint boundaries

System, memory and pixel rates remain 80, 160 and 10 MHz. CPU F/R enables each
average 32 MHz. Opposite phases can be one sys cycle apart; there is no blanket
two-cycle CPU exception. Named R-owned registers have a minimum two-sys-cycle
R-to-R interval, checked in the native harness. RF stored MLAB data and
unconditional operand pipeline registers retain their own timing.

DDR request fields are qualified individually at actual captures. DATA_OLD
failed a two-memory-cycle age check and remains excluded from the write
metadata exception. CPU memory-return captures and BSMT register ownership
also have phase assertions. DDR tag comparisons and busy qualification are
optimized without changing requests, commands or busy cycles.

The gate requires current audio/SDRAM phase proofs, CPU field/opcode and DDR
parallel-tag equivalence, DDR cache/command/busy equivalence, and sprite
packet/read equivalence. Unexpected unclocked fabric, multiple-clock nodes
or undocumented I/O boundaries fail qualification. Remaining HPS/platform
boundaries, SDRAM grades and HDMI profile are in TIMING_INTERFACES.md.

Only a final source-matching fit and successful eight-corner gate establish
timing readiness. A later build and hardware qualification are separate work
requiring an explicit RBF build request.
## Routed diagnostic update — 2026-10-06

The latest completed eight-corner run is
`bt-graphics-9b251150b9d144d982ec6dfab13d401f`. It remains **OPEN**:
setup −1.481 ns, hold +0.080 ns, recovery +0.572 ns, removal +0.191 ns,
and minimum pulse width +0.625 ns. Its fail-closed readiness report has only
the failed all-corner audit and negative setup as failures. No FPGA image
was assembled.

The decoder now selects opcode-specific differences from common control
values. The foreground serial RAM uses its existing synchronous read mode
in place of an equivalent external output register, with the original
reset mask and OLD_DATA collision behavior. Both changes have component
proofs and a successful 128-frame native replay; all 24 saved rasters match
the preceding implementation exactly. Native evidence:
`native-75b9b2b1c9b041a4a3ee3ab62ce4d38d/raster_comparison.json`.

The next candidate captures the static source-register field with the
instruction while retaining state-specific overrides, and captures
page-qualified sprite write strobes on their existing edge. It also bounds
background row-register fanout without changing logic or cycle timing.
These edits are undergoing requalification and are not timing acceptance.


2026-10-06 ongoing closure (no assembler)
---------------------------------------
C14 (bt-graphics-e9e3e85d31904ff9870485465623b415) retained static
instruction source-field capture, registered sprite page strobes and bounded
background row fanout. Its default routed SYS and MEM setup minima remained
-1.958 ns and -1.695 ns. The native 128-frame replay matched all 24 retained
rasters against C13.

C15 (bt-graphics-db5d5358ea994cd1b5498f732d200abf) tested moving the
existing CPU operand stage before field extension. Although the component
miter and 128-frame replay passed, routed SYS setup worsened to -4.253 ns
because extension and arithmetic then shared the register-file write path.
That experiment was reverted; its sources are retained under
 tests/graphics/experiments/operand-retime and in the frozen C15 snapshot.

The current CPU candidate captures MMA/R/RD/RS with the existing instruction
and state transitions. Both LINE_GZ variants are retained so line-drawing
states 6 and 9 still choose their live-condition source register. All seven
state-update sites have corresponding captures. The complete decoder miter
passed 6,291,456 comparisons in
 tests/graphics/evidence/io-phase/io-cpu_opcodes-cf10992571184de18ff6b5159072fe43.
The CPU field helper proof is io-cpu_fields-afb42de668d541ceb67f26c69a577781.

The current foreground candidate uses sixteen unchanged mixed-width RAM
leaves and producer-registered per-page/per-bank sprite write strobes. Its
one-hot read selectors retain the original read latency. CPU/write and sprite
priority, including concurrent hole writes, are preserved. Earlier component
proofs passed 100,000 sprite cycles, 200,000 complete foreground output
comparisons, and 196,608 cold-clear writes plus masked/readback transfers.
Final proofs must match the current source hashes after Quartus 17 generate
syntax compatibility fixes.

The DDR memory-return exception is now limited to named cache data, byte
patch selectors and bank/word selectors. Other MEM-clock sources retain
ordinary timing. The native harness additionally checks physical register
write ages, including writes of unchanged values, at actual CPU captures.
These stricter constraints and assertions are under qualification. Initial
closure is still OPEN. The broad donor and full-source optimization audit
has not begun. No programming image has been generated.

## Stopped at user request - 2026-10-06

Timing remains **OPEN**. No Quartus jobs owned by this chat were running at
stop, and no FPGA image was assembled. The complete donor and performance
audit has not started because initial timing closure is incomplete.

The latest reviewed routed candidate is C18
(`bt-graphics-bf4127e08cb1453ba2292cb7d5ffe46f`). Its default SYS and MEM
setup minima are -2.936 ns and -2.137 ns. A diagnostic analysis with the
correctly scoped 1,108 DDR return source registers gives SYS-only -0.879 ns,
MEM -2.137 ns and overall paths into SYS -5.468 ns. This diagnostic is not
an all-corner acceptance result.

C18 uses 21,733 ALMs, 21,839 registers and 553/553 RAM blocks. The earlier
C13, C14 and C15 fits also used 553 RAM blocks; foreground banking did not
increase that total. RAM capacity is full. The current source has no final,
source-matching successful eight-corner qualification. This commit preserves
work in progress and must not be treated as timing closure or release readiness.
