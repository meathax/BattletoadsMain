# Battletoads graphics audit

Status: graphics component regressions pass. Shipping scanout reproduces all
five captured MAME title/gameplay PNGs exactly with recorded display writes.
Full CPU execution equivalence is not established. FPGA timing and hardware
gameplay acceptance remain in progress.

Scope: sprite shift-register transfers and scaling, foreground/background
framebuffer addressing, page selection, priority, scrolling, and palette output.
Battletoads renders bitmap VRAM; its graphics path must be compared with the
MAME shift-register callbacks as well as the final scanline compositor.

The starting checkout had no project simulation harness, MAME capture runner,
MRA, or released RBF. These are evidence gaps to resolve during this audit.
Production corrections require a pinned reference and focused regression proof.
Existing framework and CPU provenance are recorded separately.

## Confirmed divergence: sprite row producer

Observation: the original serial blitter reset both fractional cursors for every
AC-region transfer and stops at an even-width boundary. FG_VRAM begins its
register-to-memory transfer before SPR_START becomes active.

Evidence: MAME 0.289 `src/mame/rare/btoads.cpp`, `render_sprite_row`,
`to_shiftreg`, and `from_shiftreg`; RTL `BT.sv` sprite state machine and
`fg_vram.sv` transfer state machine. The installed reference reports
`0.289 (mame0289)`. Local source has no Git metadata; hash it in test receipts.

Selected explanation (KNOWN): the foreground/sprite serial interface implements
different address and update semantics from the reference. MAME sets the
destination on A4 reads, sets the source on A8 reads, ignores the AC write
address, renders `(~control & 0x1ff) + 2` source pixels, preserves zero nibbles,
and advances source and destination cursors across successive rows.

Smallest correction: retain the existing bitmap memories and scanout, give the
sprite engine indexed access to its existing source shift register, and write
completed sprite pixels through the foreground memory's byte-enabled port.
Block CPU memory cycles while that port belongs to the blitter. Keep the
destination's 512-pixel wrap separate from the 256-pixel displayed half-row.

Verification: compare actual RTL writes and resulting foreground bytes with an
independent transcription of the pinned MAME row producer. Cover all widths,
unaligned sources, fractional source/destination steps, repeated rows, flip,
shadow, transparency, destination wrap, page selection, and RAM byte lanes.

Known unknowns: CPU correctness, native frame/raster equivalence, sound,
physical DDR/dual-port collision behavior, and FPGA timing. Source-driven unit tests
and MAME gameplay captures do not by themselves establish paired gameplay
equivalence.

## Implemented corrections and evidence

Reference: [MAME 0.289 Battletoads driver](https://github.com/mamedev/mame/blob/mame0289/src/mame/rare/btoads.cpp).
The exact `render_sprite_row` function body is extracted into the test oracle;
only its class qualifier is changed. Receipts bind the local driver hash,
generated oracle, tested RTL, testbench, executable and output log. Each test
compiles a frozen copy of its sources, so changes in another chat cannot change
the compiled code after its receipt is recorded.

- The row width includes all nine control bits and the extra two pixels,
  including odd widths and the maximum 513-pixel row.
- `BIT_ADDR` preserves the CPU memory controller's original address before
  `LA` replaces its low four bits with a function code. Source setup retains
  unaligned nibble offsets.
- A4 reads latch the destination and physical draw page; A8 reads latch the
  source. AC writes use the latched cursors and page even after display-control
  changes. Source/destination offsets survive successive draws.
- Each opaque source nibble writes its scaled destination, including repeated
  writes to the same pixel. Zero nibbles preserve existing data; shadow writes
  preserve MAME's bank-color semantics. Signed destination steps wrap correctly.
- Both foreground pages retain 512 destination bytes per row. CPU byte lanes
  and the independent 256-column scanout wrap are preserved.
- Full eight-bit horizontal scroll is added before background addressing.
  Odd scroll values no longer round down.
- The serial strobe is registered from the pixel phase before the divider
  changes. The former combinational phase/enable expression generated extra
  edges at the faster memory clock, consuming foreground pixels and background
  words too quickly.
- Scanline refresh keeps CPU readiness low until both foreground copies and
  their final register writes finish. Sprite-source copies likewise include
  the final registered write in their readiness check.
- Ordinary background CPU reads no longer redirect the video serial port.
  Unsupported background shift writes leave bitmap memory unchanged.
- Graphics registers merge each enabled byte independently. Palette writes
  and reads advance once per bus access, preserve raw eight-bit components,
  and produce the TLC34076's six-bit DAC values. Disallowed palette pens are
  black; the mask does not remap them to another color.
- The CPU shift register is shared across foreground and sprite windows.
  Foreground transfers copy its first 512 bytes while retaining the upper half,
  including transfers between physical pages.
- Each foreground row also retains its independent upper 512 logical bytes in
  reserved DDR storage. CPU clears of those bytes no longer erase displayed
  pixels. Initialization clears both pages before releasing the CPU.
- The 256 off-screen drawing columns also use the same DDR backing store.
  Displayed columns stay in on-chip RAM; opaque sprite writes wait for DDR
  completion, and CPU shift writes retain all 512 drawing bytes.
- Unaligned foreground shift reads gather all 512 bytes from the complete logical
  address, including DDR-backed halves and row boundaries, with stalled DDR reads.
- Foreground CPU shift copies preserve the video register and serial cursor.
  Their final pending memory writes hold CPU readiness low until committed.
- Ordinary foreground/source address decoding follows the exact MAME windows;
  the broader bit-30 alias applies only to shift callbacks.
- Scanline prefill starts at HSBLNK for the following line. DPYNX retains its
  fractional increment and reloads at VSBLNK. The former schedule displayed
  foreground rows one line late at startup.
- Normal BG/FG writes capture address, data and byte enables together on the
  CPU clock before committing in the 160 MHz VRAM domain. An advancing bus
  cannot substitute the next payload for an accepted write.
- The mixer uses its registered pixel enable. Background byte selection starts
  at the low byte after horizontal blanking. Actual pre-edge consumer sampling
  exposed a one-pixel foreground displacement and a boot-phase-dependent
  background byte swap hidden by post-edge diagnostic captures.

Latest component tests: 1,283 sprite configurations, 4,146 successive rows,
864 priority combinations, 21 scroll cases, 1,024 scanline pixels, 2,823 palette
checks, 3,072 shared-register bytes, 28 register checks, 43 background-read
checks, 2,048 saved-page checks, 2,048 upper-half checks, 18,432 unaligned-copy
bytes, 36 address-map checks, and 78 video-copy checks. The row count includes
300 consecutive draws crossing source/destination cursor wraps. Both a varied xorshift source and a sprite
row captured from actual MAME gameplay produce zero mismatches. The original
width/source/destination fixture had 768 mismatching foreground bytes. Added
fixtures exposed 1,016 scanout pixel mismatches, 27 premature refresh returns,
21 corrupted background positions, 18 wrong-page positions, 1,024 erased
foreground pixels, 9,216 wrong unaligned-copy bytes, and 72 disturbed video
positions before their respective corrections; each now reports zero.

The memory models reproduce the configured RAM address/output registration and
byte enables. Sprite transfers exercise intermittent acknowledgements and the
shipping DDR word order. These are CPU-bus-stimulated graphics tests, not a
cycle-accurate external-DDR or CPU execution qualification.
The DDR foreground-clear test separately verifies 393,216 stalled writes across
two complete initializations, including both pages, exclusion of the on-chip
visible quarter, and final-write readiness.

The shipping DDR controller is also exercised independently, including command
backpressure and read responses arriving during command stalls. Starting with
nonzero backing memory verifies 196,608 accepted initialization writes and
preservation of the reserved visible quarter. A further 128 accepted masked
writes and a 512-byte copy/readback verify the physical word order. This exposed
two integration faults: readiness omitted prepared/pending writes, and a
foreground-copy write could lose its payload before the controller captured it.
Readiness now covers final acceptance, and the foreground request holds its
address/data/byte enables through capture.

TMS34020 1-bit transparency also differed from MAME: `PatternEqual` returned an
all-transparent mask for every source value. MAME's `write_pixel_t_1` writes a
nonzero source bit. The corrected lane mask and aggregate write predicate pass
3,241 directed/random 1-bit cases within 204,224 comparisons over all 64 pixel
size encodings; the other encodings retain their baseline behavior.

## Gameplay reference

A clean, ROM-audited headless MAME run reaches gameplay and continues through
frame 1,800, with coin/start, movement and attack inputs. The input log and
snapshots prove that the scenario starts play after the title becomes ready.
The retained tap observed 629,181 graphics-register writes, 808 flip commands,
657 shadow commands, 29 source scales, 32 destination scales and three priority
modes. The fourth priority mode is covered by the directed compositor tests.

Capture receipts and native reference snapshots are under
`tests/graphics/evidence/mame-296b4583ac7840188c7a78cdc5876be7/`.
This capture retains all 1,800 input frames, 512 sprite-source blocks, and
361 unique graphics-register configurations observed during gameplay. Those
configurations include intermediate register states, rather than a trace of
actual sprite draw commands. The latest test receipts are in
`tests/graphics/build/after/` and `tests/graphics/build/after-captured/`.
This is reference and component coverage. A separate frozen native game-board
harness executes the actual TMS34020, converted production VHDL Z80, DSP,
graphics, clock enables and shipping DDR controller. Earlier snapshots complete
1,800 frames with coin/start, movement and attack inputs. The current CPU
arithmetic and phase assertions are running in a fresh 1,800-frame scenario.
The host supplies
functional external DDR and graphics RAM adapters; this is not the complete
MiSTer platform or FPGA hardware qualification.
The latest capture additionally records 2,688 direct upper-half foreground
writes during gameplay, all zero-valued clears. Those writes would have erased
lower-half pixels in the original aliased storage, confirming that the separate
logical halves are exercised by the game itself.

The full raster test instantiates the shipping graphics, real TMS34020 video
I/O and the actual MiSTer mixer enable. Synthetic patterns cover all four
priority modes, both pages, both horizontal parities and both boot phases:
3,670,016 pixels, zero mismatches. Independent scanline tests cover 5,632 timing
steps, 3,072 prefills and all register byte writes against MAME's DPYNX rules.

MAME capture `mame-cffd3c061854485eb3e56465039adb1e` includes VRAM, DAC values,
video I/O and live display-write positions for frames 350, 600, 900, 1500 and
1800. Replaying those writes gives 1,146,880 matching RTL/oracle pixels and
zero differing pixels in all five actual MAME PNGs. Receipt:
`tests/graphics/evidence/raster/raster-dde402b98e304cd2b96310cf995301d5/`.
In gameplay, BG1 scroll changes at physical line 120; the visible area starts
at line 24. Using only the final scroll value caused differences in rows 0–96.
The captured write timeline resolves those differences without image alignment
or modifying either image. This qualifies the renderer with MAME state; it
does not assert identical CPU scheduling in two independent executions.

## FPGA acceptance and remaining gaps

Analysis/synthesis of the full-memory correction succeeded: 18,213 registers,
5,304,033 logical memory bits and 34 DSP blocks. Initial placement failed at
573 M10K blocks against 553 available, despite logical bits being below capacity.
Scaler storage placement and NVRAM/audio RAM inference changes are documented
in [RESOURCE_OPTIMIZATION.md](RESOURCE_OPTIMIZATION.md). Logical memory capacity
is preserved, and the scaler's packed storage change has exhaustive codec and
complete-source control preservation checks. The revised allocation has now
fitted successfully at 534 of 553 physical RAM blocks. Timing closure is still
required before FPGA acceptance.

No RBF has been produced yet. The user explicitly requested an RBF after full
timing closure. Until that condition is verified, the check runner invokes only
`quartus_map`, `quartus_fit` and `quartus_sta`.

The original graphics adapter qualifies bus-stimulated components. The new
native harness executes game CPUs, but a successful run alone cannot attest
MAME RGB equivalence, complete MiSTer input/raster ordering or FPGA gameplay.
Palette mask/readback, shared shift-register transfers between memory windows,
and saved destination pages now have directed passing coverage. Both 512-byte
halves of each foreground row and unaligned A0 copies crossing them now have
passing directed coverage. MAME
explicitly masks background word addresses with `0x3fcff`; its unused column
bits alias the stored columns. This implementation does not establish MAME
equivalence for every game level or whole-core CPU execution.

ROM-loader/player-input changes landed separately during the audit and are
preserved. Their tests and commits are not graphics acceptance evidence.
