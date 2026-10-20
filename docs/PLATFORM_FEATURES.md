# Platform feature audit

Reference: [MAME 0.289 Battletoads driver](https://github.com/mamedev/mame/blob/mame0289/src/mame/rare/btoads.cpp),
`INPUT_PORTS_START(btoads)`, `main_map`, `machine_start`, and `btoads`.
Original timing register values are in `src/btc0/btc0.asm`.
There is one supported game/set, `btoads`.

| Requirement | Implementation |
| --- | --- |
| Functional controls | Attack, Jump, Coin, Start, Service Menu, Pause in OSD/MRA; all three player ports. |
| Service button | OSD trigger or joystick bit 8, inverted to the CPU's active-low input. The previous zero status bit held service asserted. |
| DIP switches | Dedicated DIP switches page, all eight SW1 bits with MAME names and polarity. Unknown labels the undocumented eighth switch. Three-player default retained. |
| Integer scaling | All five native video_freak modes; scale status expanded to three bits. |
| Direct/analog/CRT | Native RGB raster and framework sync paths retained; steady pixel cadence replaces fractional six/seven-clock intervals. |
| Y/C | Disabled by `MISTER_DISABLE_YC=1` in the timing-closed project. |
| Refresh | 10 MHz / (640 × 257) = 60.797665370 Hz; 64 microseconds per line. Program values HTOTAL=639 and VTOTAL=256 are inclusive. |
| High scores | Original 8 KiB battery-backed RAM, containing scores and cabinet settings; MRA index-4 load/save. An OSD rising edge requests upload after CPU writes and holds the CPU until completion. |
| Rotation | Removed from the active core. Framebuffer outputs are idle and native orientation is retained. |
| Scandoubler | Ordinary 2x line repeat and CRT scanline effects. HQ2x interpolation is disabled. |
| Audio routing | Stereo and framework mixing remain available. ALSA is disabled by `MISTER_DISABLE_ALSA=1`. |

The system/graphics-memory PLL changes from 64/128 MHz to 80/160 MHz.
Sample SDRAM uses the 80 MHz system clock: its two-cycle RAS-to-CAS delay
is 25 ns, meeting its 20 ns requirement; driving it at 160 MHz would fail
that timing constraint. Original CPU phase rates remain 32 MHz each and
audio enable remains 6 MHz. Video uses an exact divide by eight.
The full release at commit `4c0ba30d38fe08cb1dd1835ff44098512b815a8c`
passed all eight timing corners with minimum setup slack +0.030 ns,
minimum hold slack +0.087 ns and zero unconstrained paths. The SDRAM
clock retains its +8.750 ns phase. See `TIMING_CLOSURE_20261011.md`.

NVRAM uses inferred dual-port 4096 × 16 RAM: byte-enabled CPU access and
word-oriented host access. The TMS34020 sees only the low byte of each
32-bit word; a WIDE host transfer packs two consecutive NVRAM bytes.
CPU read acknowledgement waits until its registered data address matches.
First use and a new ROM clear the RAM, matching MAME's zero initialization.
Reset and OSD opening preserve it.

The active DDR bridge serves game memory only. Its command capture and
backpressure handling remain in `rtl/bt_video_ddr.sv`; the rotation writer,
FIFO and arbitration branch are absent. Game read responses reach the
controller independently of command backpressure.

## Verification

`python tests/verify_platform_features.py` checks every pixel-enable interval
and CPU phase counts, all 8192 NVRAM bytes, packed restore/upload, CPU byte
lanes, OSD saving and pause, unchanged-save suppression, unrelated indices,
and new-ROM clearing. Its current memory-bridge regression checks game
commands and read responses under DDR stalls. Source checks require the
rotation menu to be absent and the local ordinary scandoubler to be used.
Historical rotation/FIFO fixtures are retained as archive tests; they do
not establish features in the current core.

Wrapper lint also passes using the actual framework/video/DDR/SDRAM sources
with interface stubs for the BT board, VHDL enable generator, PLL primitive
and FIFO primitive. This checks integration rather than physical hardware
behavior. Existing framework procedural-net assignments require the
Verilator PROCASSWIRE diagnostic to be suppressed; sys sources are unchanged.

`python tests/verify_player_inputs.py` checks 6150 player input reads and
all 256 SW1 combinations through the production CPU input mux.

## Remaining hardware validation

The timing-closed RBF was built on 11 October 2026. Hardware qualification
remains pending. Checks must cover native RGB/direct video and HDMI scaling,
sound, DIP effects during gameplay, service entry, all three players, pause,
ROM reload and score persistence across reload and power cycles. The current
native startup replay covers 128 frames and does not exercise sprite-source
writes. See `FUNCTIONAL_AUDIT_20261011.md` for current audit evidence and limits.
Simulation cannot establish the absence of physical video distortion.
