#!/usr/bin/env python3
"""
PX4 Reboot and Flash Tool
Attempts to reboot device into bootloader before flashing
"""

import serial
import struct
import sys
import time
import os

# Bootloader protocol
SYNC = b'\x21'
EOC = b'\x20'
INSYNC = b'\x12'
OK = b'\x10'
GET_DEVICE = b'\x22'
CHIP_ERASE = b'\x23'
PROG_MULTI = b'\x27'
REBOOT = b'\x30'

def try_reboot_to_bootloader(port, baudrates=[57600, 115200, 38400, 230400]):
    """Try to reboot device into bootloader using various methods"""

    print("Attempting to reboot device into bootloader...")

    for baud in baudrates:
        print(f"\nTrying {baud} baud...")
        try:
            ser = serial.Serial(port, baud, timeout=1)
            time.sleep(0.5)

            # Method 1: Send ASCII reboot command (PX4/NuttX)
            print("  Sending 'reboot -b' command...")
            ser.write(b'\r\n')
            time.sleep(0.1)
            ser.write(b'reboot -b\r\n')
            time.sleep(1.0)

            # Check if bootloader responds
            ser.write(SYNC + EOC)
            time.sleep(0.2)
            resp = ser.read(2)
            if resp == INSYNC + OK:
                print(f"✓ Bootloader activated at {baud} baud!")
                ser.close()
                return baud

            # Method 2: Send MAVLink reboot command
            print("  Trying MAVLink reboot command...")
            # MAVLink COMMAND_LONG to reboot to bootloader
            # This is a simplified attempt - real MAVLink is more complex
            ser.write(b'\xfe')  # MAVLink start byte
            time.sleep(0.5)

            # Check for bootloader
            ser.write(SYNC + EOC)
            time.sleep(0.2)
            resp = ser.read(2)
            if resp == INSYNC + OK:
                print(f"✓ Bootloader activated at {baud} baud!")
                ser.close()
                return baud

            # Method 3: Binary reboot command (some bootloaders)
            print("  Trying binary reboot sequence...")
            ser.write(b'\x00' * 10)
            time.sleep(0.1)
            ser.write(b'\xff' * 10)
            time.sleep(0.5)

            # Check for bootloader
            ser.write(SYNC + EOC)
            time.sleep(0.2)
            resp = ser.read(2)
            if resp == INSYNC + OK:
                print(f"✓ Bootloader activated at {baud} baud!")
                ser.close()
                return baud

            ser.close()

        except Exception as e:
            print(f"  Error: {e}")

    return None

def check_bootloader(port, baud=115200):
    """Check if device is already in bootloader mode"""
    print(f"\nChecking if bootloader is active on {port}...")

    try:
        ser = serial.Serial(port, baud, timeout=1)
        time.sleep(0.5)

        for attempt in range(3):
            ser.write(SYNC + EOC)
            time.sleep(0.2)
            resp = ser.read(2)
            if resp == INSYNC + OK:
                print("✓ Bootloader is already active!")
                ser.close()
                return True

        ser.close()
    except Exception as e:
        print(f"Error: {e}")

    return False

def flash_firmware(port, firmware_path, baud=115200):
    """Flash firmware using PX4 bootloader protocol"""

    # Read firmware
    with open(firmware_path, 'rb') as f:
        firmware_data = f.read()

    print(f"\nFirmware size: {len(firmware_data)} bytes")
    print(f"Opening port {port} at {baud} baud...")

    ser = serial.Serial(port, baud, timeout=3)
    time.sleep(0.5)

    try:
        # Sync with bootloader
        print("Syncing with bootloader...")
        for attempt in range(10):
            ser.write(SYNC + EOC)
            time.sleep(0.1)
            resp = ser.read(2)
            if resp == INSYNC + OK:
                print("✓ Bootloader synced!")
                break
            if attempt == 9:
                raise Exception("Failed to sync with bootloader")

        # Get device info
        print("Getting device info...")
        ser.write(GET_DEVICE + EOC)
        resp = ser.read(1)
        if resp != INSYNC:
            raise Exception("No INSYNC for GET_DEVICE")
        dev_id = ser.read(4)
        resp = ser.read(1)
        if resp != OK:
            raise Exception("No OK for GET_DEVICE")
        device_id = struct.unpack('<I', dev_id)[0]
        print(f"Device ID: 0x{device_id:08X}")

        # Erase flash
        print("Erasing flash (this may take several seconds)...")
        ser.write(CHIP_ERASE + EOC)
        resp = ser.read(1)
        if resp != INSYNC:
            raise Exception("No INSYNC for CHIP_ERASE")
        resp = ser.read(1)  # Wait for erase completion
        if resp != OK:
            raise Exception("No OK for CHIP_ERASE")
        print("✓ Flash erased")

        # Program firmware
        print(f"Programming {len(firmware_data)} bytes...")
        CHUNK_SIZE = 256
        offset = 0

        while offset < len(firmware_data):
            chunk = firmware_data[offset:offset + CHUNK_SIZE]
            if len(chunk) < CHUNK_SIZE:
                chunk += b'\xff' * (CHUNK_SIZE - len(chunk))

            cmd = PROG_MULTI + struct.pack('B', len(chunk)) + chunk + EOC
            ser.write(cmd)

            resp = ser.read(1)
            if resp != INSYNC:
                raise Exception(f"No INSYNC at offset {offset}")
            resp = ser.read(1)
            if resp != OK:
                raise Exception(f"No OK at offset {offset}")

            offset += CHUNK_SIZE
            progress = min(100, (offset * 100) // len(firmware_data))
            print(f"\r  Progress: {progress}%", end='', flush=True)

        print("\n✓ Programming complete")

        # Reboot
        print("Rebooting device...")
        ser.write(REBOOT + EOC)
        time.sleep(0.5)

        print("\n✓✓✓ FIRMWARE FLASHED SUCCESSFULLY! ✓✓✓")
        return True

    except Exception as e:
        print(f"\n✗ Error: {e}")
        return False
    finally:
        ser.close()

def main():
    if len(sys.argv) < 3:
        print("Usage: python px4_reboot_and_flash.py <PORT> <FIRMWARE_BIN>")
        print("Example: python px4_reboot_and_flash.py COM3 firmware.bin")
        sys.exit(1)

    port = sys.argv[1]
    firmware_path = sys.argv[2]

    if not os.path.exists(firmware_path):
        print(f"Error: Firmware file not found: {firmware_path}")
        sys.exit(1)

    print("="*60)
    print("PX4 REBOOT AND FLASH TOOL")
    print("="*60)

    # Step 1: Check if already in bootloader
    if not check_bootloader(port):
        # Step 2: Try to reboot into bootloader
        baud = try_reboot_to_bootloader(port)
        if not baud:
            print("\n" + "="*60)
            print("⚠ BOOTLOADER NOT DETECTED")
            print("="*60)
            print("\nThe device is not responding to bootloader commands.")
            print("Please manually enter bootloader mode:")
            print("\n1. Disconnect the USB cable")
            print("2. Locate the BOOT0 button/jumper on the board")
            print("3. Hold BOOT0 button (or set jumper to HIGH)")
            print("4. Connect USB cable while holding BOOT0")
            print("5. Release BOOT0 after 1 second")
            print("6. Run this script again")
            print("\nAlternatively, use an ST-Link debug probe:")
            print("  cargo flash --chip STM32F427VITx --release")
            print("="*60)
            sys.exit(1)

    # Step 3: Flash firmware
    success = flash_firmware(port, firmware_path)
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
