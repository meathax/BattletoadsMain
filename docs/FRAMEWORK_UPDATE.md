# Battletoads framework update

Framework source: https://github.com/MiSTer-devel/Template_MiSTer
Framework commit: 3ea1134cf05d62c2b1db30362277a823d739ced2 (2026-08-26).
Core baseline: ace68a15e944c2090651080a59502ae47ae31b44 (2023-04-20).

## Changes

- Import the complete upstream sys/ tree without local framework modifications.
- Use sys/emu_ports.vh, including its 46-bit HPS bus and new video control outputs.
- Widen HPS status/status_in to 128 bits, joysticks to 32 bits, download index to
  16 bits and download address to 27 bits. Preserve existing menu bit assignments.
- Hold unused video controls and new_vmode low. Release the open-drain user port
  with ones and drive unused UART outputs low, as in the current template.
- Match the SD buffer address width and tie the unused SD input data and block
  count to zero. Existing disk read/write requests remain disabled.
- Vendor the author's CPU source dependencies and reference them inside rtl/.
- Record the installed Quartus 17.0.2 version. Preserve the core's clock plan,
  timing constraints, fitter settings and MISTER_SMALL_VBUF DDR layout selection.

## Initial assessment

This remains the upstream WIP core. A framework update does not establish
correct gameplay. ROM loading, CPU execution, video and sound still require
simulation and MiSTer testing before a playable release can be claimed.
The original ROM menu and game logic are retained for subsequent repair work.
The checkout has no MRA or released RBF. Its menu loads btc0-p0, btc0-p1 and
btc0-s separately; packaging for normal arcade loading remains future work.
The original video_freak aspect setting (64:49) is retained; assess it against
board timing and a reference capture during video repair.

## Validation

Quartus ran against a separate source snapshot. The user requested no RBF build, so the active compile was stopped during fitting after successful analysis and synthesis. No further builds will be run for this update.
No build is deployed as part of this framework update.

- All 57 imported framework files match the pinned template byte for byte.
- Quartus elaborated the framework, TMS34020 and TMS320C1X without interface
  errors during the first compile.
- Existing critical warning 127005: rtl/bt.mif initializes 32768 bytes of a
  65536-byte Z80 RAM; Quartus initializes the remaining addresses to zero.
  The RAM definition and image are unchanged by this update.
- Upstream framework whitespace produces git diff --check warnings; it is
  retained to keep sys/ identical to the template. Core integration edits pass
  the scoped whitespace check.

- Analysis and synthesis passed with Quartus 17.0.2 (18,174 registers, 4,255,457 block-memory bits, 34 DSP blocks). Fitting and timing validation were not completed.
