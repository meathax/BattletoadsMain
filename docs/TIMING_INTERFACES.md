# Timing qualification boundaries

This task runs Quartus analysis, synthesis, fitting and TimeQuest only. It does
not run the assembler, create an SOF/RBF, or authorize an RBF build. The timing
gate's `eligible_for_rbf` is a technical readiness result, not build permission.

## Configured clocks

The game system remains at 80 MHz, DDR at 160 MHz, and pixels at 10 MHz. CPU
F/R enables each average 32 MHz; the shortest R-to-R interval is two system
clocks, while an opposite phase can follow after one. CPU exceptions therefore
name only registers with a qualified phase owner. BSMT F/R enables each average
6 MHz. Their opposite phases are at least six system clocks apart; its selected
architectural register paths receive only a conservative two-clock allowance.
Free-running registers and external data inputs retain single-clock timing.

The SDRAM receive clock is an additional 80 MHz PLL output at +8750 ps. Commands
launch on the system clock; the board clock is inverted. ACTIVE starts at request
acceptance, READ/WRITE follows two clocks later, and a receive register captures
the single CL2 word before the original six-clock completion edge. A 16-bit
register bridge restores the original system-clock data publication and busy
completion. Requests, byte swapping, write masks and completion cycles have
independent reference checks. CL2 data starts driving one clock after READ.
Receive occurs in state 5; bridge publication is at state-6 completion, 16.25 ns
after receive. The intervening sys edge has its bridge enable low. This specific
enabled transfer has a two-cycle exception checked on every modeled read.
External hold checks the first following SDRAM edge.

The currently qualified scaled HDMI clock is 148.54 MHz; direct video uses the
80 MHz game clock. Runtime PLL frequencies above this profile need separate
timing qualification. This report does not certify arbitrary custom video
overclocks.

## Clocked external interfaces

| Interface | Requirement and budget | Qualification |
| --- | --- | --- |
| SDRAM input | MT48LC16M16A2 -75/-7E CL2 `tAC <= 6 ns`, plus 2 ns clock/return flight; no-load data hold `tOHn >= 1.8 ns`, with zero minimum board flight | 16 input setup and hold paths per corner; active-drive checks at the actual single-word release edge |
| SDRAM output | 1.5 ns setup, 0.8 ns hold, plus 0.5 ns clock/data skew | 34 active data/address/control paths per corner; constant pins have no data path |
| HDMI video | ADV7513 setup 1.8 ns, hold 1.3 ns, plus 0.25 ns board skew | Both exclusive forwarded clocks, 54 setup/hold paths per corner |
| HDMI audio | ADV7513 I2S/LRCLK setup and hold 2 ns, plus 0.25 ns skew | 48/96 kHz serializer cadence, rate switching, and two setup/hold paths per corner |

The SDRAM flight/skew and HDMI board skew are conservative analysis budgets,
not measurements of a particular user's module. Other SDRAM speed grades are
not automatically covered: use their actual CL2 access specification.

The I2S divider has a generated clock on its register, then a second generated
clock follows the actual route to HDMI_SCLK. A port-only clock omitted source
latency and failed TimeQuest's generated-clock consistency check. Normal
serialization has at least five audio clocks of setup and three of hold. Reset
can truncate an audio frame; the phase test excludes its initial settling period.

## Remaining platform boundaries

The gate explicitly inventories every remaining port without an I/O delay. A
new or unexpected port fails qualification; SDRAM DQ/control and HDMI video/audio
data cannot be hidden in these allowances.

- Buttons, switches, keys, VGA_EN, HDMI_TX_INT, I2C return pins and the shared
  SDCD/SPDIF input are asynchronous platform inputs. They do not have a board
  clock defining a synchronous input setup/hold relationship.
- VGA RGB/sync and analogue/PDM audio/SPDIF outputs have no synchronous external
  data-capture clock in this project. Internal source paths remain timed.
- LEDs are indicators. HDMI_MCLK, HDMI_TX_CLK, HDMI_SCLK and SDRAM_CLK are clock
  outputs, whose propagation belongs in the corresponding clock model.
- SD/SDIO, I2C, ADC and USER_IO are existing MiSTer platform/reserved boundaries.
  Their protocol or electrical timing is not certified by this core's eight-corner
  data-interface audit. The platform implementation must remain separately
  reviewed; this allowance is not permission to change its RTL without proof.

TimeQuest also emits synthetic unclocked nodes for the HPS hard interfaces.
Only the recorded HPS roots are allowed. Every unexpected unclocked fabric node,
unreviewed multiple-clock register, missing uncertainty, inconsistent multicycle,
or partial I/O constraint fails the gate. The known video clock mux registers
are checked against explicit, mutually exclusive native/scaled clock groups.

## Evidence and acceptance

`tests/graphics/synthesize.py` retains immutable inputs, their hashes, tool logs
and fitted reports. `timing_run.py` recreates a routed timing netlist independently
for every available operating model, avoiding Quartus 17 HPS annotation failures
when changing corners in a reused netlist. All eight models must pass setup,
hold, recovery, removal, minimum pulse width, consistency and I/O checks.

`verify_timing.py` binds those results to the current workspace and requires
matching successful SDRAM, audio, CPU-field/opcode, DDR-tag/cache, sprite-packet/read and full-core
native receipts. The native harness uses the actual CPU/graphics/DSP RTL and
converted VHDL T80, with external memory adapters. Its 128-frame result and saved
rasters are regression evidence; they do not establish exhaustive game behavior,
whole-MiSTer simulation, or hardware validation of a newly built bitstream.

DDR request fields are qualified individually. The wider metadata bundle failed
an age check because DATA_OLD can change one memory clock before a write capture.
It remains excluded from the two-memory-clock exceptions. CPU/DSP register-owner
and enable-spacing assertions are also mandatory in the native proof.
