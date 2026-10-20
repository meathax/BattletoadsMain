# Battletoads functionality audit — 11 October 2026

Status: in progress. This audit checks the active core, reproduces suspected
faults before fixing them, and retains the original 80 MHz system, 160 MHz
memory and 80 MHz SDRAM clocks with the +8.750 ns SDRAM phase. Check-only
compiles use private databases and do not assemble an RBF.

Confirmed fixes under regression include the BSMT command-pending BIO signal;
DSP ABS, BGZ, low-nine-bit auxiliary-register updates and the documented
`-32768 * -32768` multiply result; CPU arithmetic-left-shift overflow;
SDRAM cold-cache validity, initialization and distributed refresh; and the
sample-ROM loader's refresh reservation handoff. The SDRAM receive test also
reproduced a stale word at the DSP's actual pre-edge read deadline. An active
read now exposes the captured word at that deadline while committing the cache
and completing the transaction on the original edge.

The TI first-generation DSP instruction specification defines SACH shifts
0, 1 and 4. Differences from MAME for reserved SACH encodings are recorded as
unsupported-encoding observations; they do not justify changing those valid
hardware semantics.

The current production DSP passed all 79 directed checks, with only the five
explicitly reserved SACH observations, and 131,121 MPY plus 57,344 MPYK cases
passed without supported-instruction mismatches. Receipts are retained in
`build/functional_audit_20261011/cpu_audio/dsp_current_r1/receipt.json` and
`build/functional_audit_20261011/cpu_audio/mpy_current_r1/receipt.json`.

The IO refresh outputs were also declared as nets despite assignment in clocked
processes. Their declarations now explicitly use registers, preserving the
processes and allowing strict SystemVerilog compilation without a test adapter.
The CPU's early return stage also now sees an explicit `IO_SEL` declaration
before use, with its original continuous driver retained beside the IO block.
The dormant ROM-detection template, its unused PAL state and its constant OSD
button register were removed; the button output remains explicitly zero.
The new SDRAM refresh-slot input is appended to retain the old positional-port
ordering for existing integrations.

Natural CPU boot, instruction fetch and retirement reproduced ten incorrect
DIVS/DIVU cases out of twenty boundaries. The divider now zero-extends unsigned
32-bit dividends, shifts divisor magnitudes logically, retains the dividend
sign for signed remainders, detects quotient overflow, sets V on division
errors and preserves both destination registers on an error. Overflow reuses
the first iterative subtraction's borrow; no combinational divider or extra
valid division step was added. The new sign state remains under the original
R-phase checker. Current retirement regressions are pending.

A warm-reset test also exposed a stale reset value in the simulation-only
address reference. Its reset now matches the real address register; the
transaction assertions remain enabled. Hardware state is unchanged by that
checker correction.

Current cabinet input/DIP coverage passed 6,150 CPU reads and every physical
DIP byte: `build/player_inputs/inputs-83a5c28c9bdd42d681056e816434cbc9/receipt.json`.
The current SDRAM pin/caller regression passed all 87 profiles, all 80 phase
offsets, four 65 ms profiles, refresh/init/byte lanes and reserved-refresh
loader handoffs. Its receipt is
`build/functionality_audit_4c0ba30/sdram_current_v1/proof-r4/receipt.json`
(SHA-256 `35987438e1925868d47d6b9a05ed3991b61630fdca13d79908719d8475744bcc`).
Full ROM transport remains under test.

Full ROM transport subsequently passed all 5,259,264 halfwords, including every
sample and audio-memory word. The main-ROM endpoint models DDR acceptance and
acknowledgment; sample writes use actual SDRAM pins. Receipt:
`build/functionality_audit_4c0ba30/sdram_current_v1/full-rom-r1/receipt.json`
(SHA-256 `c5d39e1507a39204fee2ec942f4814fdb5147fe11fb4923bd5709fddd6c9ea4f`).

Natural SLA instruction retirement also reproduced 504 incorrect negative
flags in 1,368 cases, with data/C/Z/V and unrelated status passing. Shift
operations now derive N from the shifted result's sign, and their factored
line predicate follows the same sign. Instruction flag masks retain unaffected
flags. The unchanged failing receipt is
`build/functional_audit_20261011/cpu_audio/sla_retirement_baseline_r1/receipt.json`;
current-source retirement verification remains pending.

## Accepted baseline

The baseline is commit `4c0ba30d38fe08cb1dd1835ff44098512b815a8c`.
The delivered RBF is
`build/timing_closure_20261011/timing_closed_release_artifacts/Arcade-Battletoads.rbf`,
SHA256 `c7adb9654f3651dd8bfd4c2e31dcd061ce3330cfa1b20217243d9a4732c8df0a`.
Its immutable artifact manifest is in the same directory. All eight native
timing corners passed: minimum setup +0.030 ns, hold +0.087 ns,
recovery +1.210 ns, removal +0.259 ns and pulse width +0.625 ns, with
zero unconstrained paths. The audit preserves that binary and its evidence.

The qualified native startup run contains 128 frames, 2,878,478 DDR commands
and 2,573,046 raw writes. Its receipts are
`build/final_v25_native_input_qualification_r1/receipt.json` and
`build/final_v25_current_input_qualification_r1/receipt.json`.
That proof excludes production HPS/top-level integration, hardware sound,
and whole-game MAME equivalence. Its startup interval contains no
sprite-source writes. Component proofs supplement it but do not establish
complete gameplay correctness.

## Audit matrix

| Area | Current evidence / investigation | Acceptance needed |
| --- | --- | --- |
| CPU / memory controller | Existing instruction, Boolean equivalence and startup proofs; independent source audit in progress. | Reproduce and correct any instruction/bus fault; regress affected behavior. |
| DDR / foreground / sprite storage | Existing native RAM, arbitration, clear and collision proofs; independent ownership and loader audit in progress. | Active gameplay commands, masks, reads, clear and backpressure. |
| Sample SDRAM | Physical command audit in progress. Refresh appears dependent on cache-hit reads; initialization refresh sequence needs checking. | Device-specified initialization, periodic refresh during idle/loading/reset and retained read/write correctness. |
| Video | Native palette/startup and ordinary doubler proofs; independent blitter, page, scale, shadow and priority review in progress. | Gameplay sprite writes and clears, native and doubled raster, sync/blanking and palette transitions. |
| DSP / audio CPU | Independent command/BIO, instruction and clock-enable audit in progress. | Correct command handoff and DSP instruction behavior; live sound remains a hardware gate. |
| ROM / controls / pause / NVRAM | Existing full payload, input-mux, phase-gate and packed 8 KiB persistence regressions; production-top review in progress. | Current-source regression plus hardware service/DIPs/players/save/reload checks. |
| Platform / preflight | Project importer fails before simulation on a Quartus Tcl assignment-collection API gap. | Preserve exact project source replacement guard; repair integration without weakening RTL checks. |
| Timing | Accepted baseline above. | Every changed active RTL snapshot must pass original-setting fit/STA at all eight corners, with zero unconstrained paths and reviewed warnings. |

## Confirmed corrections

README, platform and ROM-loading documentation described an older feature
set and an interrupted build. They now describe the active timing-closed
release. `rotate_90` is constant zero, framebuffer outputs are idle, the OSD
has no rotation option, HQ2x is disabled, and the QSF disables Y/C and ALSA.
Native RGB/direct video, HDMI scaling, ordinary doubling, scanlines and
stereo mixing remain in the active implementation.

## Preflight tool gap

## Qualification limits

No audit fix has yet been assembled into a new RBF. No hardware deployment,
whole-game paired MAME comparison or complete-game pass is claimed here.
Findings and tests below will be updated with exact current-source receipts
as the investigations complete.
