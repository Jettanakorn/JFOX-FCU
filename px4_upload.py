#!/usr/bin/env python3
"""
PX4 Bootloader Uploader
Uploads firmware binary to PX4 bootloader via serial port
Based on px_uploader.py from PX4 project
"""

import serial
import struct
import sys
import time
import os

# Bootloader protocol commands
SYNC = b'\x21'
GET_SYNC = b'\x21'
GET_DEVICE = b'\x22'
CHIP_ERASE = b'\x23'
PROG_MULTI = b'\x27'
READ_MULTI = b'\x28'
GET_CRC = b'\x29'
REBOOT = b'\x30'
EOC = b'\x20'

# Response codes
INSYNC = b'\x12'
OK = b'\x10'
FAILED = b'\x11'
INVALID = b'\x13'

class PX4Uploader:
    def __init__(self, port, baudrate=115200):
        self.port = port
        self.baudrate = baudrate
        self.ser = None

    def open(self):
        """Open serial port and sync with bootloader"""
        print(f"Opening port {self.port} at {self.baudrate} baud...")
        self.ser = serial.Serial(self.port, self.baudrate, timeout=2)
        time.sleep(0.5)

        # Try to sync with bootloader
        for attempt in range(10):
            print(f"Sync attempt {attempt + 1}...")
            self.ser.write(GET_SYNC + EOC)
            time.sleep(0.1)

            resp = self.ser.read(2)
            if resp == INSYNC + OK:
                print("Bootloader synced!")
                return True

        raise Exception("Failed to sync with bootloader")

    def get_device_info(self):
        """Get device ID from bootloader"""
        print("Getting device info...")
        self.ser.write(GET_DEVICE + EOC)

        resp = self.ser.read(1)
        if resp != INSYNC:
            raise Exception("Device info: No INSYNC")

        # Read device ID (4 bytes)
        dev_id = self.ser.read(4)

        resp = self.ser.read(1)
        if resp != OK:
            raise Exception("Device info: No OK")

        device_id = struct.unpack('<I', dev_id)[0]
        print(f"Device ID: 0x{device_id:08X}")
        return device_id

    def erase(self):
        """Erase flash memory"""
        print("Erasing flash...")
        self.ser.write(CHIP_ERASE + EOC)

        resp = self.ser.read(1)
        if resp != INSYNC:
            raise Exception("Erase: No INSYNC")

        # Wait for erase to complete (can take several seconds)
        resp = self.ser.read(1)
        if resp != OK:
            raise Exception("Erase: No OK")

        print("Flash erased")

    def program(self, firmware_data):
        """Program firmware to flash"""
        print(f"Programming {len(firmware_data)} bytes...")

        # Program in 256-byte chunks
        CHUNK_SIZE = 256
        offset = 0

        while offset < len(firmware_data):
            chunk = firmware_data[offset:offset + CHUNK_SIZE]

            # Pad to chunk size if needed
            if len(chunk) < CHUNK_SIZE:
                chunk += b'\xff' * (CHUNK_SIZE - len(chunk))

            # Send PROG_MULTI command
            cmd = PROG_MULTI + struct.pack('B', len(chunk)) + chunk + EOC
            self.ser.write(cmd)

            resp = self.ser.read(1)
            if resp != INSYNC:
                raise Exception(f"Program: No INSYNC at offset {offset}")

            resp = self.ser.read(1)
            if resp != OK:
                raise Exception(f"Program: No OK at offset {offset}")

            offset += CHUNK_SIZE

            # Progress indicator
            progress = (offset * 100) // len(firmware_data)
            print(f"\rProgress: {progress}%", end='', flush=True)

        print("\nProgramming complete")

    def verify(self, firmware_data):
        """Verify programmed firmware"""
        print(f"Verifying {len(firmware_data)} bytes...")

        # Get CRC from bootloader
        self.ser.write(GET_CRC + EOC)

        resp = self.ser.read(1)
        if resp != INSYNC:
            raise Exception("Verify: No INSYNC")

        crc_data = self.ser.read(4)

        resp = self.ser.read(1)
        if resp != OK:
            raise Exception("Verify: No OK")

        bootloader_crc = struct.unpack('<I', crc_data)[0]
        print(f"Bootloader CRC: 0x{bootloader_crc:08X}")

        # Calculate local CRC (simple sum for now)
        # TODO: Implement proper CRC32 if needed

        print("Verification skipped (CRC calculation not implemented)")

    def reboot(self):
        """Reboot device"""
        print("Rebooting...")
        self.ser.write(REBOOT + EOC)
        time.sleep(0.5)

    def close(self):
        """Close serial port"""
        if self.ser:
            self.ser.close()

    def upload(self, firmware_path):
        """Upload firmware file"""
        # Read firmware file
        print(f"Reading firmware from {firmware_path}...")
        with open(firmware_path, 'rb') as f:
            firmware_data = f.read()

        print(f"Firmware size: {len(firmware_data)} bytes")

        try:
            self.open()
            self.get_device_info()
            self.erase()
            self.program(firmware_data)
            # self.verify(firmware_data)  # Skip verify for now
            self.reboot()
            print("\n✓ Upload successful!")
        finally:
            self.close()

def main():
    if len(sys.argv) < 3:
        print("Usage: python px4_upload.py <PORT> <FIRMWARE_BIN>")
        print("Example: python px4_upload.py COM3 firmware.bin")
        sys.exit(1)

    port = sys.argv[1]
    firmware_path = sys.argv[2]

    if not os.path.exists(firmware_path):
        print(f"Error: Firmware file not found: {firmware_path}")
        sys.exit(1)

    uploader = PX4Uploader(port)
    uploader.upload(firmware_path)

if __name__ == '__main__':
    main()
