# Battletoads core for MiSTer (WIP)

The MiSTer framework is updated to Template_MiSTer commit
`3ea1134cf05d62c2b1db30362277a823d739ced2`. CPU dependencies are included in
`rtl/`, so the project no longer requires sibling CPU repositories.

See [the framework assessment and validation](docs/FRAMEWORK_UPDATE.md) and
[CPU source provenance](rtl/PROVENANCE.md). Gameplay remains unverified.

Load [Battletoads.mra](releases/Battletoads.mra) from the MiSTer Arcade menu.
Install the matching Battletoads RBF in `_Arcade/cores/` and the unmodified
MAME 0.289 `btoads.zip` in `games/mame/`. No extracted ROM files or additional
ZIPs are needed at runtime. The MRA includes the game's DIP switches.

The index-0 download contains the 8 MiB main program interleaved as MAME's
`ROM_LOAD32_WORD`, followed by 2 MiB of samples and the 32 KiB Z80 program.
The loader holds the CPUs in reset until the complete stream has been written.
The Z80 program is downloaded from the archive rather than baked into the RBF.
The existing BSMT2000 chip firmware remains initialized by `rtl/bsmt2000.mif`.

The OSD and MRA name the controls **Attack**, **Jump**, **Coin**, **Start**,
**Service Menu**, and **Pause**. Service Menu is also available directly in
the OSD. All three players can use the service and pause controls.
The **DIP switches** menu exposes all eight SW1 switches: Demo Sounds,
Mono Sound, Common Coin Mech, Three Players, Free Play, Blood Free Mode,
Credit Retention, and the hardware's undocumented eighth switch (Unknown).
Three Players defaults to On. Mono Sound (SW1-2) is Off by default, which gives true
stereo: MAME labels this bit "Stereo" with the polarity reversed, and its default
produces a near-mono mix. Other defaults follow MAME 0.289.

Audio & Video includes Normal, V-Integer, HV-Integer-, HV-Integer+ and
HV-Integer scaling, ordinary 2x line doubling, and CRT scanline effects.
Analog RGB, CRT and direct video use the native raster. The timing-closed
build has HDMI rotation, HQ2x interpolation, Y/C encoding and ALSA disabled.
The pixel enable is a steady 10 MHz, giving 15.625 kHz horizontal and
60.797665370 Hz vertical timing (640 pixels by 257 lines).

The original cabinet's 8 KiB NVRAM stores high scores and service settings.
It restores through the MRA's index-4 NVRAM file, and automatically requests
a save when the OSD opens after a change. The CPU pauses through the save
transaction; native video timing keeps running. Opening the OSD also pauses
gameplay. NVRAM persists through reset and clears when a new ROM is loaded
before its saved file is restored.

Run `python tests/verify_platform_features.py` and
`python tests/verify_player_inputs.py` for the source-level regressions.
See [platform validation and remaining hardware checks](docs/PLATFORM_FEATURES.md).
Commit `4c0ba30d38fe08cb1dd1835ff44098512b815a8c` produced an RBF on
11 October 2026 with all eight timing corners accepted at 80/160 MHz:
minimum setup slack +0.030 ns and zero unconstrained paths.
See [the timing evidence](docs/TIMING_CLOSURE_20261011.md) and
[the current functionality audit](docs/FUNCTIONAL_AUDIT_20261011.md).
That release has not yet been qualified on MiSTer hardware or through a
complete gameplay comparison with MAME.

Validate against a local MAME executable and ZIP:

```powershell
python scripts/validate_rom_loading.py "path/to/btoads.zip" --mame "path/to/mame.exe"
```

The script checks ROM sizes, CRCs, SHA1s, DIP settings and every payload byte
against an independent MAME layout. Its output stays in ignored `build/roms/`.
Run `tests/rom_loading_tb.sv` with Verilator, including `rtl/bt_rom_loader.sv`,
`rtl/ddram.sv`, `rtl/sdram.sv` and `tests/altddio_out_sim.sv`, and pass
`+image=build/roms/download.bin`. This checks the full stream against real DDR
and SDRAM command writes, CPU cache/reset-vector reads, reloads and short loads.
`tests/rom_loading_wrapper_tb.sv` (same files plus `rtl/bt_video_ddr.sv`) runs
the same stream through the wrapper's DDR command slice to the HPS port.
