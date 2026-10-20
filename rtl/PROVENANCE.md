# Vendored CPU sources

These files are copied from the Battletoads core author's
repositories. Each directory contains the upstream QIP and exactly the RTL it
references; the Battletoads-specific memory wrappers remain in rtl/.

- TMS34020: https://github.com/srg320/TMS34020
  Commit: 2046b4378e2e29ee1fe9ef0b6365987e95fa5c0c (2023-04-20).
- TMS320C1X: https://github.com/srg320/TMS320C1X
  Commit: be05f766d838deec1b69e3a4bf445bf4162be6d9 (2023-04-11).

These are also the latest upstream commits at import, and predate or coincide
with the Battletoads baseline. Source headers and copyright notices are retained.
Neither dependency repository supplies a separate license file; confirm their
licensing with the author before distributing a derivative release.

Local graphics integration change: `TMS34020/TMS34020.sv` exposes the existing
`DBUS_A` as `BIT_ADDR`. The physical `LA` bus replaces address bits 3:0 with a
bus function code; the sprite source cursor needs bit 3 of the original bit
address. CPU execution and the memory controller are unchanged.

Local framework resource changes: `sys/ascal.vhd` stores RGB line memories as
packed 24-bit words so Quartus honors MLAB placement attributes. The exhaustive
codec and complete-source preservation checks are in
`tests/verify_scaler_storage.py`; see `docs/RESOURCE_OPTIMIZATION.md` for scope.
`bt_audio_ram.sv` is a local full-capacity replacement for the mixed-width Z80
RAM wrapper, with the same registered byte reads and word-wide loader writes.
# HDMI rotation

`screen_rotate_two.sv`: copyright 2020 Sorgelig, GPL-2.0-or-later, copied
from the SSLAMS donor's `rtl/vendor/rotation/screen_rotate_two.sv`.
Battletoads moves declarations before use for strict elaborators and
initializes framebuffer ownership. The separate `bt_video_ddr.sv` FIFO
and arbiter handle clock crossing and DDR stalls; the donor ignores busy.
