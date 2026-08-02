# JFOX FCU - Bare-Metal Rust Flight Controller

A bare-metal Rust firmware for the JFOX Flight Control Unit based on PX4FMUv2.4.5 hardware.

## Hardware

- **MCU**: STM32F427VIT6 (ARM Cortex-M4F @ 180MHz)
- **Flash**: 2MB
- **RAM**: 256KB (192KB main + 64KB CCM)
- **IMU**: MPU-6000 (6-axis gyro + accel) @ 1kHz
- **Barometer**: MS5611
- **Storage**: FM25V01 FRAM (128Kbit)
- **Communication**: 4x UART, USB, CAN, I2C, SPI
- **I/O**: 8x PWM outputs

## Architecture

### Project Structure

```
jfox-fcu/
├── firmware/       # Main RTIC application
├── bsp/            # Board Support Package (pins, clocks)
├── hal/            # Hardware Abstraction Layer (GPIO, SPI, UART)
├── drivers/        # Sensor drivers (MPU6000, MS5611, etc.)
├── math/           # Math library (vector, quaternion, PID)
├── flight/         # Flight control (sensor fusion, stabilization)
├── telemetry/      # Communication protocols
└── common/         # Shared utilities
```

### Key Features

- **Pure bare-metal**: Direct register access, no HAL dependencies
- **RTIC framework**: Real-time task scheduling with zero-cost concurrency
- **Sensor fusion**: Madgwick AHRS filter @ 1kHz
- **Control loops**: Cascaded PID (attitude + rate) @ 500Hz
- **Safety**: Arming logic, failsafe, voltage monitoring

## Building

### Prerequisites

```bash
# Install Rust nightly
rustup default nightly
rustup target add thumbv7em-none-eabihf

# Install tools
cargo install probe-rs
```

### Build Firmware

```bash
cd firmware
cargo build --release
```

### Flash

```bash
# Via probe-rs (ST-Link/J-Link)
probe-rs run --chip STM32F427VITx \
  target/thumbv7em-none-eabihf/release/jfox-fcu

# Or use cargo alias
cargo rr
```

This project has more than one firmware binary (see `firmware/Cargo.toml`'s
`[[bin]]` entries) and a second flashing path (the board's built-in PX4
bootloader over USB, no debug probe needed) - see **[`BUILD_AND_FLASH.md`](BUILD_AND_FLASH.md)**
for the full picture, including current build/flash status per binary and
how to connect Mission Planner/QGroundControl.

## Task Architecture

| Task | Rate | Priority | Description |
|------|------|----------|-------------|
| `imu_task` | 1000 Hz | 3 (highest) | Read MPU-6000, run Madgwick filter |
| `control_task` | 500 Hz | 2 | Attitude/rate control with PID |
| `motor_task` | 400 Hz | 1 | PWM output to motors/servos |
| `heartbeat_task` | 1 Hz | 0 (idle) | Status LED blink |

## Clock Configuration

- **HSE**: 24MHz (external crystal)
- **PLL**: 24MHz / 12 × 180 / 2 = 180MHz
- **SYSCLK**: 180MHz
- **AHB (HCLK)**: 180MHz
- **APB1 (PCLK1)**: 45MHz
- **APB2 (PCLK2)**: 90MHz

## Memory Layout

- **Flash**: 0x08000000 - 0x081FFFFF (2MB)
- **RAM**: 0x20000000 - 0x2002FFFF (192KB)
- **CCMRAM**: 0x10000000 - 0x1000FFFF (64KB)
  - Core-Coupled Memory for zero wait-state access
  - Used for time-critical data (attitude, PID state)

## Sensor Configuration

### MPU-6000 (Primary IMU)
- **Interface**: SPI1 @ 5.625MHz
- **Gyro range**: ±2000 °/s
- **Accel range**: ±16g
- **Sample rate**: 1000 Hz
- **DLPF**: 184 Hz bandwidth

## Development Status

### ✅ Completed
- [x] Workspace structure and build system
- [x] Memory layout and clock configuration
- [x] GPIO and SPI HAL implementation
- [x] MPU-6000 driver with full initialization
- [x] Vector and quaternion math library
- [x] Madgwick AHRS sensor fusion
- [x] PID controller implementation
- [x] RTIC application with task scheduling
- [x] MAVLink v1 telemetry (`jfox-fcu-usb`: HEARTBEAT/SYS_STATUS/ATTITUDE,
      interim GCS bridge - see `BUILD_AND_FLASH.md`)

### 🚧 In Progress
- [ ] UART HAL for telemetry/GPS
- [ ] PWM output for motor control
- [ ] RC input (PPM/S.Bus/Spektrum)
- [ ] Motor mixer (quad/hexa/plane)

### 📋 Planned
- [ ] MS5611 barometer driver
- [ ] GPS integration (NMEA/UBX)
- [ ] Position hold and navigation
- [ ] DMA for efficient I/O
- [ ] Configuration storage in FRAM

## Pin Mapping

### SPI1 - MPU-6000
- SCK: PE13 (AF5)
- MISO: PE14 (AF5)
- MOSI: PE15 (AF5)
- CS: PC2 (GPIO)
- DRDY: PD15 (GPIO input)

### UART1 - Telemetry
- TX: PA9 (AF7)
- RX: PA10 (AF7)

### PWM Outputs
- CH1-4: TIM1 (PE9, PE11, PE13, PE14)
- CH5-8: TIM4 (PD12, PD13, PD14, PD15)

## Debugging

### View logs via defmt
```bash
probe-rs run --chip STM32F427VITx
```

### GDB debugging
```bash
# Terminal 1: Start GDB server
probe-rs gdb-server --chip STM32F427VITx

# Terminal 2: Connect GDB
arm-none-eabi-gdb target/thumbv7em-none-eabihf/release/jfox-fcu
(gdb) target remote :1337
(gdb) load
(gdb) continue
```

## Performance

| Metric | Target | Notes |
|--------|--------|-------|
| CPU usage | <60% | Leave headroom for future features |
| RAM usage | <128 KB | Half of available RAM |
| Flash usage | <1 MB | Half of available flash |
| IMU jitter | <1ms | Consistent 1kHz sampling |
| Control latency | <10ms | Sensor to motor output |

## Safety Features

1. **Pre-arm checks**: Sensor health, calibration valid
2. **Arming logic**: Explicit RC command required
3. **Failsafe**: RC loss → disarm or hold
4. **Low voltage**: Battery protection
5. **Watchdog**: Auto-reset on firmware hang
6. **Data validation**: CRC checks on sensor data

## License

MIT OR Apache-2.0

## Contributing

This is a reference implementation for bare-metal Rust flight controller development.
Contributions welcome!

## References

- [PX4 Autopilot](https://px4.io/)
- [Madgwick AHRS](https://x-io.co.uk/open-source-imu-and-ahrs-algorithms/)
- [RTIC Framework](https://rtic.rs/)
- [Embedded Rust Book](https://rust-embedded.github.io/book/)
