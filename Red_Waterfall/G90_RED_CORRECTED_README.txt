G90 DisplayUnit v1.81 — corrected red waterfall
================================================

This build supersedes the earlier RED build.

Why corrected?
--------------
The real G90/ST7735 display path uses red/blue in the opposite effective
channel order from the simple RGB interpretation of the firmware palette.
The earlier build therefore appeared blue on real hardware.

This corrected build stores the palette with R/B compensated so the visible
waterfall is black/dark-red -> red -> orange -> yellow -> white.

Only the waterfall palette is modified:
    file offset: 0x1B1D4 .. 0x1B7D3
    flash addr : 0x0801F1D4 .. 0x0801F7D3
    size       : 1536 bytes (384 x 32-bit entries)

No executable code, menus, protocol, fonts, CAT or DSP code is changed.

Validation
----------
Size:   132656 bytes
SHA256: 2b6f9449dda3479662bfec08153276addf49b9ddb19c48cf70eaf3eb1f6eaae1

Independent validation performed:
- Official stock v1.81 XGF decrypted with the known G90 AES-256-ECB key.
- Corrected plaintext compared against official stock plaintext.
- Differences outside the 1536-byte palette region: ZERO.
- Corrected XGF decrypted again after encryption.
- Decrypt(encrypt(corrected.bin)) equals corrected.bin byte-for-byte.

Use
---
Install:
    python3 -m pip install pyserial

Dry-run:
    python3 flash_g90_display_red_corrected_safe.py G90_DispUnit_Fw_V1.81_FTDX10_RED_CORRECTED.xgf --dry-run

List ports:
    python3 flash_g90_display_red_corrected_safe.py --list-ports

With your official FTDI cable:
    python3 flash_g90_display_red_corrected_safe.py G90_DispUnit_Fw_V1.81_FTDX10_RED_CORRECTED.xgf /dev/serial/by-id/usb-FTDI_USB__-__Serial-if00-port0

The flasher is locked to the exact SHA-256 above and refuses the older,
blue-on-hardware build or any other firmware.
