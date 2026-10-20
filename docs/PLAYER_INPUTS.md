# Battletoads player inputs

Player 2 and player 3 were tied to `8'hFF` at the `BT` instance, so the CPU
always saw released controls even though `hps_io` delivered their joysticks.
The wrapper now routes `joy0`, `joy1` and `joy2` independently to P1, P2 and P3.
P1's existing mapping is preserved. `rtl/BT.sv` already decodes all three ports.

All three players use the same active-low byte, matching
[MAME's Battletoads driver](https://github.com/mamedev/mame/blob/master/src/mame/rare/btoads.cpp):

| Control | MiSTer joystick bit | Board input bit |
| --- | ---: | ---: |
| Up | 3 | 0 |
| Right | 0 | 1 |
| Down | 2 | 2 |
| Left | 1 | 3 |
| Button 1 | 4 | 4 |
| Button 2 | 5 | 5 |
| Coin | 6 | 6 |
| Start | 7 | 7 |

The TMS34020 reads P1, P2 and P3 at bit addresses `0x20000000`, `0x20000080`
and `0x20000100`. Coin and Start remain independent for each player.

SW1 bit 3 must be clear for the game's three-player cabinet mode. The original
fixed `0x7C` byte disabled that mode. The wrapper's default now clears bit 3.
When an MRA supplies cabinet DIPs, select **Three Players: On**. MRA files are
maintained separately from this input fix.

Run `python tests/verify_player_inputs.py` with Icarus Verilog on PATH.
The test simulates exact source slices from the wrapper and the board's read
mux. Independent expected masks cover all 256 control combinations for each
player, simultaneous distinct inputs, isolation, address aliases and unused
joystick bits: 6,150 CPU input reads. It also checks the DIP default and, when
a DIP latch is present, ioctl filtering, cabinet mode changes and CPU DIP
readback. This is an input-path simulation; full game execution and physical
controller testing remain to be verified with the completed MRAs.
