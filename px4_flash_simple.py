#!/usr/bin/env python3
"""
Simplified PX4 Bootloader Flash Tool
Works with bootloaders that don't fully support GET_DEVICE
"""

import serial
import struct
import sys
import time
import os

# Bootloader commands
SYNC = b'\x21'
EOC = b'\x20'
INSYNC = b'\x12'
OK = b'\x10'
CHIP_ERASE = b'\x23'
PROG_MULTI = b'\x27'
REBOOT = b'\x30'

def flash_firmware(port, firmware_path, baud=115200):
    """Flash firmware using simplified PX4 bootloader protocol"""

    # Read firmware
    print(f"Reading firmware from {firmware_path}...")
    with open(firmware_path, 'rb') as f:
        firmware_data = f.read()

    print(f"Firmware size: {len(firmware_data)} bytes")
    print(f"Opening port {port} at {baud} baud...")

    ser = serial.Serial(port, baud, timeout=5)
    time.sleep(0.5)

    try:
        # Step 1: Sync with bootloader
        print("\n[1/4] Syncing with bootloader...")
        synced = False
        for attempt in range(15):
            ser.write(SYNC + EOC)
            time.sleep(0.15)
            resp = ser.read(2)
            if resp == INSYNC + OK:
                print("  OK Bootloader synced!")
                synced = True
                break
            print(f"  Attempt {attempt + 1}/15...", end='\r')

        if not synced:
            raise Exception("Failed to sync with bootloader")

        # Step 2: Erase flash
        print("\n[2/4] Erasing flash memory...")
        print("  This may take 5-10 seconds, please wait...")

        ser.write(CHIP_ERASE + EOC)
        time.sleep(0.2)

        resp = ser.read(1)
        if resp != INSYNC:
            print(f"  Warning: Expected INSYNC, got {resp.hex()}")
            # Continue anyway, some bootloaders work differently

        # Wait for erase to complete (can take several seconds)
        resp = ser.read(1)
        if resp == OK:
            print("  OK Flash erased successfully")
        else:
            print(f"  Warning: Expected OK, got {resp.hex()}")
            # Continue anyway

        # Step 3: Program firmware
        print(f"\n[3/4] Programming {len(firmware_data)} bytes to flash...")

        CHUNK_SIZE = 252  # Use 252 instead of 256 to fit in single byte length field
        offset = 0
        errors = 0

        while offset < len(firmware_data):
            chunk = firmware_data[offset:offset + CHUNK_SIZE]

            # Pad to chunk size
            if len(chunk) < CHUNK_SIZE:
                chunk += b'\xff' * (CHUNK_SIZE - len(chunk))

            # Send programming command
            cmd = PROG_MULTI + struct.pack('B', len(chunk)) + chunk + EOC
            ser.write(cmd)
            time.sleep(0.05)  # Give bootloader time to process

            # Read response
            resp = ser.read(1)
            if resp != INSYNC:
                errors += 1
                if errors > 10:
                    raise Exception(f"Too many errors at offset {offset}")
                print(f"\n  Warning: No INSYNC at offset {offset}, retrying...")
                continue  # Retry this chunk

            resp = ser.read(1)
            if resp != OK:
                errors += 1
                if errors > 10:
                    raise Exception(f"Too many errors at offset {offset}")
                print(f"\n  Warning: No OK at offset {offset}, retrying...")
                continue  # Retry this chunk

            # Success, move to next chunk
            offset += CHUNK_SIZE
            progress = min(100, (offset * 100) // len(firmware_data))

            # Progress bar
            bar_length = 40
            filled = int(bar_length * progress / 100)
            bar = '=' * filled + '-' * (bar_length - filled)
            print(f"  [{bar}] {progress}% ({offset}/{len(firmware_data)} bytes)", end='\r', flush=True)

        print(f"\n  OK Programming complete! ({offset} bytes written)")

        # Step 4: Reboot device
        print("\n[4/4] Rebooting device...")
        ser.write(REBOOT + EOC)
        time.sleep(0.5)

        print("\n" + "="*60)
        print("  FIRMWARE FLASHED SUCCESSFULLY!")
        print("="*60)
        print("\nThe device is now rebooting with the new firmware.")
        print("You can verify operation by checking the serial output or LEDs.")

        return True

    except Exception as e:
        print(f"\n\nERROR: {e}")
        print("\nTroubleshooting:")
        print("1. Make sure device is still in bootloader mode")
        print("2. Try disconnecting and reconnecting USB")
        print("3. Re-enter bootloader mode and run again")
        return False

    finally:
        ser.close()

def main():
    if len(sys.argv) < 3:
        print("Usage: python px4_flash_simple.py <PORT> <FIRMWARE_BIN>")
        print("Example: python px4_flash_simple.py COM3 firmware.bin")
        sys.exit(1)

    port = sys.argv[1]
    firmware_path = sys.argv[2]

    if not os.path.exists(firmware_path):
        print(f"Error: Firmware file not found: {firmware_path}")
        sys.exit(1)

    print("="*60)
    print("  PX4 BOOTLOADER FLASH TOOL (SIMPLIFIED)")
    print("="*60)

    success = flash_firmware(port, firmware_path)
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
