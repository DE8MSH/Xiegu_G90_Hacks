#!/usr/bin/env python3
"""
SAFE G90 DisplayUnit v1.81 CORRECTED RED firmware flasher
================================================

This uploader is intentionally LOCKED to exactly one firmware image:

    G90_DispUnit_Fw_V1.81_FTDX10_RED_CORRECTED.xgf
    size: 132656 bytes
    SHA-256: 2b6f9449dda3479662bfec08153276addf49b9ddb19c48cf70eaf3eb1f6eaae1

It uploads through the Xiegu XG bootloader at 115200 8N1 using
XMODEM-1K + CRC-16/XMODEM.

Safety properties:
- Refuses every firmware whose SHA-256 or length differs.
- CRC16 self-test before opening the serial port.
- Per-block CRC16 plus bootloader ACK required for every data block.
- Retries NAK/timeouts up to a fixed limit.
- Requires an explicit typed confirmation.
- Has --dry-run and --listen modes.
- Never touches USB-UART VCC; this is a software note, not an electrical control.

Limit:
The XG bootloader protocol does not expose a post-flash read-back operation here.
So this tool can verify the source file and every transmitted XMODEM block/ACK,
but it cannot independently read the STM32 flash back after programming.

Dependency:
    python3 -m pip install pyserial
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

EXPECTED_NAME = "G90_DispUnit_Fw_V1.81_FTDX10_RED_CORRECTED.xgf"
EXPECTED_SIZE = 132656
EXPECTED_SHA256 = "2b6f9449dda3479662bfec08153276addf49b9ddb19c48cf70eaf3eb1f6eaae1"

BAUD = 115200
PACKET_SIZE = 1024

STX = 0x02
EOT = 0x04
ACK = 0x06
NAK = 0x15
CAN = 0x18
CRC_REQUEST = 0x43  # ASCII C

BOOT_BANNER = b"Hit a key to abort"
BOOT_MENU = b"1.Update FW"
BOOT_WAIT_FW = b"Wait FW file"

serial = None
list_ports = None


def require_pyserial():
    global serial, list_ports
    if serial is None:
        try:
            import serial as _serial
            from serial.tools import list_ports as _list_ports
        except ImportError:
            print(
                "pyserial fehlt.\n"
                "Installieren mit:\n"
                "  python3 -m pip install pyserial",
                file=sys.stderr,
            )
            raise SystemExit(2)
        serial = _serial
        list_ports = _list_ports
    return serial, list_ports


def crc16_xmodem(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def self_test() -> None:
    # Standard CRC-16/XMODEM test vector.
    got = crc16_xmodem(b"123456789")
    if got != 0x31C3:
        raise RuntimeError(f"CRC self-test FAILED: 0x{got:04X}, expected 0x31C3")

    # Packet framing sanity.
    pkt = build_packet(1, b"abc")
    if len(pkt) != 1029:
        raise RuntimeError(f"XMODEM packet-size self-test FAILED: {len(pkt)}")
    if pkt[0] != STX or pkt[1] != 1 or pkt[2] != 0xFE:
        raise RuntimeError("XMODEM header self-test FAILED")


def build_packet(block_no: int, chunk: bytes) -> bytes:
    if len(chunk) > PACKET_SIZE:
        raise ValueError("internal error: XMODEM chunk > 1024")
    # Xiegu community uploader pads the last 1K block with EOT (0x04).
    payload = chunk.ljust(PACKET_SIZE, bytes([EOT]))
    n = block_no & 0xFF
    crc = crc16_xmodem(payload)
    return bytes([STX, n, 0xFF - n]) + payload + bytes([crc >> 8, crc & 0xFF])


def validate_locked_firmware(path: Path) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(path)

    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()

    print(f"Datei    : {path}")
    print(f"Groesse  : {len(data)} Byte (erwartet {EXPECTED_SIZE})")
    print(f"SHA-256  : {sha}")
    print(f"Erwartet : {EXPECTED_SHA256}")

    if path.suffix.lower() != ".xgf":
        raise ValueError("Datei ist keine .xgf")
    if len(data) != EXPECTED_SIZE:
        raise ValueError("FALSCHE DATEIGROESSE - Flashen wird verweigert")
    if sha != EXPECTED_SHA256:
        raise ValueError("SHA-256 STIMMT NICHT - Flashen wird verweigert")
    if len(data) % 16:
        raise ValueError("XGF ist nicht AES-Block-ausgerichtet")

    print("Firmware-Pruefung: OK - exakt der freigegebene CORRECTED RED-v1.81-Build.")
    return data


def open_serial(port: str, timeout: float = 0.05):
    smod, _ = require_pyserial()
    return smod.Serial(
        port=port,
        baudrate=BAUD,
        bytesize=smod.EIGHTBITS,
        parity=smod.PARITY_NONE,
        stopbits=smod.STOPBITS_ONE,
        timeout=timeout,
        write_timeout=10.0,
        xonxoff=False,
        rtscts=False,
        dsrdtr=False,
    )


def show_ports():
    _, lp = require_pyserial()
    ports = list(lp.comports())
    if not ports:
        print("Keine seriellen Ports gefunden.")
        return
    for p in ports:
        print(f"{p.device:20s} {p.description or ''} {p.hwid or ''}")


def listen_only(port: str, seconds: float):
    """
    RX-only test. This function writes NOTHING to the serial port.
    Use it before connecting the dongle TX wire if you built your own cable.
    """
    print(f"RX-only: {port}, {BAUD} 8N1, {seconds:.0f} s")
    print("Jetzt G90/Head in den Recovery-Start bringen.")
    print("Dieser Modus sendet KEIN einziges Byte.\n")

    with open_serial(port, timeout=0.1) as ser:
        ser.reset_input_buffer()
        deadline = time.monotonic() + seconds
        got = bytearray()
        while time.monotonic() < deadline:
            chunk = ser.read(256)
            if chunk:
                got.extend(chunk)
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
        print()

    if BOOT_BANNER in got or BOOT_MENU in got:
        print("\nBootloader-Text erkannt: RX-Verdrahtung ist plausibel.")
        return 0

    print(
        "\nKein eindeutiger Bootloader-Text erkannt.\n"
        "Noch NICHT flashen. Recovery-Start und RX/GND-Verdrahtung pruefen."
    )
    return 1


def read_until_any(ser, needles: list[bytes], timeout: float, echo=True) -> int:
    deadline = time.monotonic() + timeout
    buf = bytearray()

    while time.monotonic() < deadline:
        chunk = ser.read(256)
        if not chunk:
            continue

        if echo:
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()

        buf.extend(chunk)
        if len(buf) > 8192:
            del buf[:-4096]

        for idx, needle in enumerate(needles):
            if needle in buf:
                return idx

    raise TimeoutError(
        "Timeout: erwartet wurde "
        + " oder ".join(repr(x.decode(errors="replace")) for x in needles)
    )


def write_all(ser, data: bytes):
    sent = 0
    while sent < len(data):
        n = ser.write(data[sent:])
        if not n:
            raise IOError("serial write returned zero bytes")
        sent += n
    ser.flush()


def read_byte(ser, timeout: float):
    old = ser.timeout
    ser.timeout = timeout
    try:
        b = ser.read(1)
    finally:
        ser.timeout = old
    return b[0] if b else None


def enter_update_menu(ser, timeout: float):
    ser.reset_input_buffer()
    ser.reset_output_buffer()

    print("\nWarte auf XG-Bootloader...")
    print("Head/Radio jetzt in Recovery-Modus starten.")

    which = read_until_any(ser, [BOOT_BANNER, BOOT_MENU], timeout, echo=True)

    if which == 0:
        # Abort normal boot and enter menu.
        write_all(ser, b" ")
        read_until_any(ser, [BOOT_MENU], 10.0, echo=True)

    # Menu item 1 = Update FW
    write_all(ser, b"1")
    read_until_any(ser, [BOOT_WAIT_FW], 20.0, echo=True)
    print("\nBootloader wartet auf Firmware.")


def wait_for_crc_request(ser, timeout: float = 15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        b = read_byte(ser, 0.5)
        if b is None:
            continue
        if b == CRC_REQUEST:
            print("XMODEM CRC-Modus ('C') angefordert: OK")
            return
        if b == CAN:
            raise RuntimeError("Bootloader hat Transfer abgebrochen (CAN)")
        if b in (9, 10, 13) or 32 <= b <= 126:
            sys.stdout.write(chr(b))
            sys.stdout.flush()
    raise TimeoutError("Kein XMODEM-CRC-Request ('C') vom Bootloader")


def xmodem_send_1k(ser, data: bytes, retries: int = 10):
    wait_for_crc_request(ser)

    blocks = (len(data) + PACKET_SIZE - 1) // PACKET_SIZE
    print(f"\nTransfer: {len(data)} Byte, {blocks} XMODEM-1K-Bloecke")

    for i in range(blocks):
        chunk = data[i*PACKET_SIZE:(i+1)*PACKET_SIZE]
        pkt = build_packet(i + 1, chunk)

        ok = False
        for attempt in range(1, retries + 1):
            write_all(ser, pkt)
            response = read_byte(ser, 10.0)

            if response == ACK:
                ok = True
                break

            if response == CAN:
                raise RuntimeError(f"CAN vom G90 bei Block {i+1}")

            if response not in (NAK, CRC_REQUEST, None):
                printable = (
                    repr(chr(response))
                    if 32 <= response <= 126
                    else f"0x{response:02X}"
                )
                print(f"\nUnerwartete Antwort {printable} bei Block {i+1}")

            if attempt < retries:
                print(
                    f"\nBlock {i+1}/{blocks}: kein ACK, Retry {attempt+1}/{retries}",
                    flush=True,
                )

        if not ok:
            raise RuntimeError(
                f"Block {i+1} nach {retries} Versuchen NICHT bestaetigt"
            )

        done = i + 1
        pct = 100.0 * done / blocks
        print(f"\rACK {done:3d}/{blocks:3d}  {pct:6.2f} %", end="", flush=True)

    print()

    # End of transfer.
    write_all(ser, bytes([EOT]))
    response = read_byte(ser, 2.0)

    if response == NAK:
        # Conventional XMODEM receiver may NAK first EOT, then ACK second.
        write_all(ser, bytes([EOT]))
        response = read_byte(ser, 2.0)

    if response == CAN:
        raise RuntimeError("Bootloader hat EOT mit CAN abgebrochen")

    if response == ACK:
        print("EOT vom Bootloader mit ACK bestaetigt.")
    else:
        # Community g90updatefw does not require EOT ACK on all XG variants.
        print(
            "Hinweis: kein separates EOT-ACK empfangen. "
            "Alle Firmware-Datenbloecke wurden jedoch einzeln per CRC/ACK bestaetigt."
        )

    # Show any bootloader status without interpreting unknown wording.
    deadline = time.monotonic() + 3.0
    print("\nBootloader-Ausgabe nach Transfer:")
    while time.monotonic() < deadline:
        chunk = ser.read(256)
        if chunk:
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
        else:
            time.sleep(0.02)
    print()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Locked safe flasher for G90 DisplayUnit v1.81 RED"
    )
    ap.add_argument(
        "firmware",
        nargs="?",
        default=EXPECTED_NAME,
        help=f"must be exactly {EXPECTED_NAME}",
    )
    ap.add_argument("port", nargs="?", help="/dev/ttyUSB0, /dev/ttyACM0, COM5 ...")
    ap.add_argument("--list-ports", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="validate only, no serial I/O")
    ap.add_argument(
        "--listen",
        type=float,
        metavar="SECONDS",
        help="RX-only wiring test; writes nothing to G90",
    )
    args = ap.parse_args()

    try:
        self_test()
    except Exception as e:
        print(f"INTERNAL SELF-TEST FAILED: {e}", file=sys.stderr)
        return 2

    if args.list_ports:
        show_ports()
        return 0

    path = Path(args.firmware)

    try:
        data = validate_locked_firmware(path)
    except Exception as e:
        print(f"\nABBRUCH: {e}", file=sys.stderr)
        return 2

    if args.dry_run:
        print("\nDRY-RUN OK. Nichts wurde gesendet oder geflasht.")
        return 0

    if not args.port:
        ap.error("serieller Port fehlt")

    if args.listen is not None:
        return listen_only(args.port, max(1.0, args.listen))

    print(
        "\nWICHTIG:\n"
        "  * Nur DISPLAY/HEAD flashen, NICHT die MainUnit.\n"
        "  * Kabel am linken USER/Custom-Port des Heads.\n"
        "  * 3.3-V-TTL, kein echtes RS-232 und kein 5-V-TX.\n"
        "  * USB-TTL-VCC NICHT anschliessen.\n"
        "  * Funkgeraet mit eigener 13.8-V-Versorgung betreiben.\n"
        "  * Nach Beginn von Erase/Transfer Strom NICHT unterbrechen.\n"
    )

    phrase = "FLASH DISPLAY RED 1.81"
    try:
        answer = input(f"Zum Start exakt eingeben: {phrase}\n> ").strip()
    except EOFError:
        return 2

    if answer != phrase:
        print("Abgebrochen.")
        return 1

    try:
        with open_serial(args.port) as ser:
            enter_update_menu(ser, 120.0)
            print(
                "\nAb jetzt nicht ausschalten. "
                "Die Datei wurde vorher SHA-256-verifiziert."
            )
            xmodem_send_1k(ser, data)
    except KeyboardInterrupt:
        print(
            "\nABBRUCH durch Benutzer. Falls Erase/Programmierung bereits lief: "
            "Strom nicht vorschnell trennen; Recovery erneut starten.",
            file=sys.stderr,
        )
        return 130
    except Exception as e:
        print(f"\nFLASH-FEHLER: {e}", file=sys.stderr)
        print(
            "Wenn der Bootloader noch erreichbar ist: Geraet versorgt lassen "
            "bzw. Recovery erneut starten und die Original-Display-v1.81 flashen.",
            file=sys.stderr,
        )
        return 1

    print(
        "\nTransfer beendet. Erst jetzt den Hinweisen des Bootloaders folgen "
        "bzw. normal neu starten."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
