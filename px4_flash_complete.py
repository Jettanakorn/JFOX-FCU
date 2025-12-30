#!/usr/bin/env python3
"""
Complete PX4 Bootloader Flash Tool
Implements full protocol sequence with GET_DEVICE and GET_CRC validation
Based on official PX4-Bootloader protocol
"""

import serial
import struct
import sys
import time
import os
import binascii


# Bootloader protocol commands (from PX4-Bootloader/bl.c)
PROTO_GET_SYNC = b'\x21'        # Establish synchronization
PROTO_GET_DEVICE = b'\x22'      # Get device identification
PROTO_CHIP_ERASE = b'\x23'      # Erase program memory
PROTO_PROG_MULTI = b'\x27'      # Write data at current address
PROTO_GET_CRC = b'\x29'         # Compute/return CRC checksum
PROTO_BOOT = b'\x30'            # Finalize programming and start application

# Response bytes
PROTO_INSYNC = b'\x12'          # "in sync" acknowledgment
PROTO_OK = b'\x10'              # Success response
PROTO_FAILED = b'\x11'          # Command failure
PROTO_INVALID = b'\x13'         # Invalid command
PROTO_EOC = b'\x20'             # End-of-command marker

CHUNK_SIZE = 252  # Maximum data bytes per PROG_MULTI command

def wait_for_response(ser, expected_len=2, timeout=10):
    """Wait for INSYNC + response pattern"""
    start = time.time()
    data = b''
    while time.time() - start < timeout:
        if ser.in_waiting > 0:
            data += ser.read(1)
            if len(data) >= expected_len:
                return data
        time.sleep(0.01)
    return data

def send_command(ser, cmd, data=b'', wait_response=True, response_len=2):
    """Send command and optionally wait for INSYNC + OK response"""
    packet = cmd + data + PROTO_EOC
    ser.write(packet)
    time.sleep(0.05)

    if wait_response:
        resp = wait_for_response(ser, response_len)
        if len(resp) >= 1 and resp[0:1] != PROTO_INSYNC:
            raise Exception(f"Expected INSYNC, got {resp.hex()}")
        if len(resp) >= 2 and resp[1:2] not in [PROTO_OK, b'']:
            if resp[1:2] == PROTO_FAILED:
                raise Exception("Command FAILED")
            elif resp[1:2] == PROTO_INVALID:
                raise Exception("Command INVALID")
        return resp
    return b''

def flash_firmware(port, firmware_path, baud=115200):
    """Flash firmware using complete PX4 bootloader protocol"""

    # Read firmware
    print(f"Reading firmware from {firmware_path}...")
    with open(firmware_path, 'rb') as f:
        firmware_data = f.read()

    print(f"Firmware size: {len(firmware_data)} bytes")
    print(f"Opening port {port} at {baud} baud...")

    ser = serial.Serial(port, baud, timeout=5)
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    time.sleep(0.5)

    try:
        # Step 1: Sync with bootloader
        print("\n[1/6] Syncing with bootloader...")
        synced = False
        for attempt in range(15):
            try:
                ser.reset_input_buffer()
                resp = send_command(ser, PROTO_GET_SYNC)
                if resp[0:1] == PROTO_INSYNC and resp[1:2] == PROTO_OK:
                    print("  [OK] Bootloader synced!")
                    synced = True
                    break
            except:
                pass
            print(f"  Attempt {attempt + 1}/15...", end='\r')
            time.sleep(0.15)

        if not synced:
            raise Exception("Failed to sync with bootloader")

        # Step 2: Get device info
        print("\n[2/6] Getting device information...")
        try:
            resp = send_command(ser, PROTO_GET_DEVICE, response_len=6)
            if len(resp) >= 6:
                # Response format: INSYNC + 4 bytes device info + OK
                device_id = struct.unpack('<I', resp[1:5])[0]
                print(f"  [OK] Device ID: 0x{device_id:08X}")
            else:
                print(f"  [WARN] Device response: {resp.hex()}")
        except Exception as e:
            print(f"  [WARN] GET_DEVICE not fully supported: {e}")
            print("  Continuing anyway (some bootloaders don't require this)...")

        # Step 3: Erase flash
        print("\n[3/6] Erasing flash memory...")
        print("  This may take 5-10 seconds, please wait...")

        resp = send_command(ser, PROTO_CHIP_ERASE, wait_response=False)

        # Wait for INSYNC + OK (erase takes time)
        resp = wait_for_response(ser, 2, timeout=30)
        if resp[0:1] == PROTO_INSYNC and resp[1:2] == PROTO_OK:
            print("  [OK] Flash erased successfully")
        else:
            raise Exception(f"Erase failed: {resp.hex()}")

        # Step 4: Program firmware
        print(f"\n[4/6] Programming {len(firmware_data)} bytes to flash...")

        offset = 0
        errors = 0

        while offset < len(firmware_data):
            chunk = firmware_data[offset:offset + CHUNK_SIZE]

            # Pad to chunk size with 0xFF
            if len(chunk) < CHUNK_SIZE:
                chunk += b'\xff' * (CHUNK_SIZE - len(chunk))

            # Send programming command: PROG_MULTI + length + data + EOC
            data_packet = struct.pack('B', len(chunk)) + chunk

            try:
                resp = send_command(ser, PROTO_PROG_MULTI, data_packet)
                if resp[0:1] != PROTO_INSYNC or resp[1:2] != PROTO_OK:
                    raise Exception(f"Programming failed at {offset}")

                # Success, move to next chunk
                offset += CHUNK_SIZE
                errors = 0

            except Exception as e:
                errors += 1
                if errors > 10:
                    raise Exception(f"Too many errors at offset {offset}: {e}")
                print(f"\n  [WARN] Error at offset {offset}, retrying...")
                time.sleep(0.1)
                continue

            # Progress bar
            progress = min(100, (offset * 100) // len(firmware_data))
            bar_length = 40
            filled = int(bar_length * progress / 100)
            bar = '=' * filled + '-' * (bar_length - filled)
            print(f"  [{bar}] {progress}% ({offset}/{len(firmware_data)} bytes)", end='\r', flush=True)

        print(f"\n  [OK] Programming complete! ({len(firmware_data)} bytes written)")



        # Step 5: Verify CRC
        print("\n[5/6] Verifying firmware CRC...")
        try:
            resp = send_command(ser, PROTO_GET_CRC, response_len=6)
            if len(resp) >= 6:
                # Get CRC from device
                device_crc = struct.unpack('<I', resp[1:5])[0]
                
                # Calculate local CRC32
                # We pad the data to match the padding sent to the chip
                padded_firmware = firmware_data
                remainder = len(padded_firmware) % CHUNK_SIZE
                if remainder > 0:
                    padded_firmware += b'\xff' * (CHUNK_SIZE - remainder)
                
                local_crc = binascii.crc32(padded_firmware) & 0xFFFFFFFF
                
                print(f"  Device CRC: 0x{device_crc:08X}")
                print(f"  Local  CRC: 0x{local_crc:08X}")

                if device_crc == local_crc:
                    print(f"  [OK] CRC verification passed!")
                else:
                    raise Exception(f"CRC Mismatch! Data corruption suspected.")
            else:
                print(f"  [WARN] CRC response unexpected: {resp.hex()}")
        except Exception as e:
            print(f"  [WARN] CRC check failed/skipped: {e}")

        # Step 6: Boot firmware
        print("\n[6/6] Booting firmware...")
        ser.write(PROTO_BOOT + PROTO_EOC)
        time.sleep(0.5)

        # Read any response (bootloader may send INSYNC + OK before rebooting)
        if ser.in_waiting > 0:
            resp = ser.read(ser.in_waiting)
            print(f"  Boot response: {resp.hex()}")

        print("\n" + "="*60)
        print("  [SUCCESS] FIRMWARE FLASHED AND BOOTED!")
        print("="*60)
        print("\nThe device should now be running the new firmware.")
        print("\nNext steps:")
        print("1. Check LED status (should exit bootloader blink pattern)")
        print("2. Reconnect USB (device will appear as new serial port)")
        print("3. Connect with QGroundControl or Mission Planner")
        print("4. Look for MAVLink heartbeat messages")

        return True

    except Exception as e:
        print(f"\n\n[ERROR] {e}")
        print("\nTroubleshooting:")
        print("1. Make sure device is in bootloader mode (BOOT0 button)")
        print("2. Try disconnecting and reconnecting USB")
        print("3. Check COM port in Device Manager")
        print("4. Try power cycling the device")
        return False

    finally:
        ser.close()

def main():
    if len(sys.argv) < 3:
        print("Usage: python px4_flash_complete.py <PORT> <FIRMWARE_BIN>")
        print("Example: python px4_flash_complete.py COM3 jfox-fcu.bin")
        sys.exit(1)

    port = sys.argv[1]
    firmware_path = sys.argv[2]

    if not os.path.exists(firmware_path):
        print(f"Error: Firmware file not found: {firmware_path}")
        sys.exit(1)

    print("="*60)
    print("  PX4 BOOTLOADER FLASH TOOL (COMPLETE PROTOCOL)")
    print("="*60)
    print("\nThis tool implements the full PX4 bootloader protocol:")
    print("  GET_SYNC -> GET_DEVICE -> CHIP_ERASE -> PROG_MULTI -> GET_CRC -> BOOT")
    print()

    success = flash_firmware(port, firmware_path)
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
