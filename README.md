# JFOX FCU - Bare-Metal Rust Flight Controller

A bare-metal Rust firmware for the JFOX Flight Control Unit based on PX4FMUv2.4.5 hardware.

## Hardware

- **MCU**: STM32F427VIT6 (ARM Cortex-M4F @ 168MHz — see [Clock Configuration](#clock-configuration) for why not the part's 180MHz maximum)
- **Flash**: 2MB
- **RAM**: 256KB (192KB main + 64KB CCM)
- **IMU**: MPU-6000 (6-axis gyro + accel) @ 1kHz
- **Barometer**: MS5611
- **Storage**: FM25V01 FRAM (128Kbit)
- **Communication**: 4x UART, USB, CAN, I2C, SPI
- **I/O**: 8x PWM outputs

Schematic-level detail (connector pinouts, net traces) is in
**[`hardware/PX4FMUv2.4.5_NETS.md`](hardware/PX4FMUv2.4.5_NETS.md)**, derived
from the board's own Eagle netlist. The 3-board TMR array's KiCad project
lives in **[`hardware/`](hardware/README.md)**.

## Where things are

**Start here, depending on what you want to do:**

| I want to… | Read |
|---|---|
| Build firmware and get it onto a board | [`BUILD_AND_FLASH.md`](BUILD_AND_FLASH.md) |
| Bring up real hardware, 1 board → 3-board TMR | [`HARDWARE_BRINGUP.md`](HARDWARE_BRINGUP.md) |
| Work on the TMR schematic or carrier PCB | [`hardware/README.md`](hardware/README.md) |
| Understand the control law and its verification | [`docs/do178c/`](docs/do178c/) |
| Run the simulator | [`sitl/README.md`](sitl/README.md) |
| Know where a custom datalink would fit | [`JFOXGROUNDCONTROL_ROADMAP.md`](JFOXGROUNDCONTROL_ROADMAP.md) |

### Repository layout

```
jfox-fcu/
├── firmware/       # RTIC application - four [[bin]] targets, see BUILD_AND_FLASH.md
├── bsp/            # Board support: pin map, clock tree
├── hal/            # Register-level drivers: GPIO, SPI, UART, PWM, CAN, DWT
├── drivers/        # Sensors and storage: MPU-6000, FM25V01 FRAM
├── math/           # Vectors, quaternions, matrices, PID, filters
├── flight/         # Control law: fusion, stabilize, MPC, adaptive, redundancy, arming, BIT
├── telemetry/      # MAVLink v1 encoder
├── common/         # Types shared across crates without a dependency cycle
├── sitl/           # Host simulator - the real control chain against a 6-DOF plant
├── hardware/       # TMR schematic + carrier PCB (KiCad). Not built by cargo.
└── docs/
    ├── do178c/     # Requirements, traceability, coverage, coding standard
    ├── historical/ # Superseded 2025-12-30 docs and scripts - do not follow
    └── board-photos/
```

Two scripts live at the root because the flashing instructions call them
directly: `px4_flash_complete.py` (PX4-bootloader upload — the one with the
`GET_CRC` step the bootloader requires) and `px_mkfw.py` (vendored from PX4,
packages a `.bin` into the `.px4` format QGroundControl expects).

`memory.x` and `ccmram.x` are linker scripts; `Cargo.toml` is the workspace.

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
- **PLL**: 24MHz / 12 × 168 / 2 = 168MHz
- **SYSCLK**: 168MHz
- **AHB (HCLK)**: 168MHz
- **APB1 (PCLK1)**: 42MHz
- **APB2 (PCLK2)**: 84MHz
- **USB 48MHz**: PLLQ = 336MHz VCO / 7 = 48MHz exactly

### Why 168MHz, not the part's 180MHz maximum

USB OTG FS needs 48MHz ±0.25%, and on STM32F42x/43x that clock can come
**only** from the main PLL's Q-output (PLL48CK). Unlike the F446/F469 and
F412/F413, this part has no `CK48MSEL` mux, so PLLSAI cannot feed USB.

180MHz needs a 360MHz VCO, and 360 has no integer PLLQ giving 48
(360/7.5). A 336MHz VCO does: 336/7 = 48 exactly, with PLLP=/2 giving
168MHz. Exact USB and 180MHz are mutually exclusive on this silicon, and
working USB was chosen over the extra 12MHz.

An earlier revision ran at 180MHz and tried to route PLLSAI to USB by
writing `CK48MSEL` at offset 0x90 — reserved space on this part, so the
write did nothing and USB ran from PLLQ at 360/7 ≈ 51.43MHz (7.1% fast).
Windows enumeration failed with "Configuration Descriptor Request Failed"
under a null VID/PID. `bsp/src/clocks.rs` carries the full note.

Anything clock-derived must be taken from `bsp::clocks` rather than
hardcoded — CAN bit timing and UART baud divisors in particular both
break silently if the clock tree moves and a stale literal is left behind.

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
