# STM32H753II pin map

**Generated** by `hardware/tools/plan_pinout.py` from
`STM32H753II.json` (embassy-rs/stm32-data-generated), which carries the
part's real alternate-function table. Do not hand-edit — re-run it.

RAM 1060 KB · flash 2048 KB · package LQFP176.

Allocated mechanically because the previous board's pin map was written
by hand and put five of eight PWM channels on top of SPI1 and SPI2.

## Assignments

| Function | Peripheral | Signal | Pin | AF |
|---|---|---|---|---|
| RC input | UART8 | TX | **PE1** | AF8 |
| RC input | UART8 | RX | **PE0** | AF8 |
| microSD | SDMMC1 | CK | **PC12** | AF12 |
| microSD | SDMMC1 | CMD | **PD2** | AF12 |
| microSD | SDMMC1 | D0 | **PC8** | AF12 |
| microSD | SDMMC1 | D1 | **PC9** | AF12 |
| microSD | SDMMC1 | D2 | **PC10** | AF12 |
| microSD | SDMMC1 | D3 | **PC11** | AF12 |
| USB | USB_OTG_FS | DM | **PA11** | AF10 |
| USB | USB_OTG_FS | DP | **PA12** | AF10 |
| PWM 1-4 | TIM1 | CH4 | **PE14** | AF1 |
| FRAM | SPI4 | MOSI | **PE6** | AF5 |
| IMU1 BMI088 | SPI1 | SCK | **PG11** | AF5 |
| IMU3 ICM-45686 | SPI6 | SCK | **PG13** | AF5 |
| FRAM | SPI4 | SCK | **PE12** | AF5 |
| FRAM | SPI4 | MISO | **PE13** | AF5 |
| PWM 1-4 | TIM1 | CH3 | **PA10** | AF1 |
| external sensor | SPI5 | SCK | **PH6** | AF5 |
| external sensor | SPI5 | MISO | **PH7** | AF5 |
| external sensor | SPI5 | MOSI | **PF11** | AF5 |
| baro + mag | I2C1 | SCL | **PB8** | AF4 |
| PWM 5-8 | TIM4 | CH3 | **PD14** | AF2 |
| baro + mag | I2C1 | SDA | **PB7** | AF4 |
| PWM 5-8 | TIM4 | CH2 | **PD13** | AF2 |
| debug console | USART1 | RX | **PB15** | AF4 |
| CAN2 | FDCAN2 | TX | **PB13** | AF9 |
| telemetry 2 | USART3 | CTS | **PD11** | AF7 |
| CAN2 | FDCAN2 | RX | **PB12** | AF9 |
| telemetry 1 | USART2 | TX | **PD5** | AF7 |
| telemetry 1 | USART2 | RX | **PA3** | AF7 |
| telemetry 1 | USART2 | CTS | **PD3** | AF7 |
| telemetry 1 | USART2 | RTS | **PD4** | AF7 |
| telemetry 2 | USART3 | RTS | **PD12** | AF7 |
| PWM 5-8 | TIM4 | CH1 | **PB6** | AF2 |
| PWM 1-4 | TIM1 | CH1 | **PE9** | AF1 |
| PWM 1-4 | TIM1 | CH2 | **PE11** | AF1 |
| PWM 5-8 | TIM4 | CH4 | **PD15** | AF2 |
| telemetry 2 | USART3 | TX | **PD8** | AF7 |
| telemetry 2 | USART3 | RX | **PD9** | AF7 |
| debug console | USART1 | TX | **PA9** | AF7 |
| IMU2 ICM-42688-P | SPI2 | SCK | **PI1** | AF5 |
| IMU1 BMI088 | SPI1 | MISO | **PG9** | AF5 |
| IMU1 BMI088 | SPI1 | MOSI | **PD7** | AF5 |
| IMU2 ICM-42688-P | SPI2 | MISO | **PI2** | AF5 |
| IMU3 ICM-45686 | SPI6 | MISO | **PG12** | AF5 |
| IMU3 ICM-45686 | SPI6 | MOSI | **PG14** | AF5 |
| external I2C | I2C2 | SCL | **PF1** | AF4 |
| external I2C | I2C2 | SDA | **PF0** | AF4 |
| GPS 2 | UART7 | RX | **PE7** | AF7 |
| CAN1 (TMR bus) | FDCAN1 | TX | **PH13** | AF9 |
| CAN1 (TMR bus) | FDCAN1 | RX | **PI9** | AF9 |
| IMU2 ICM-42688-P | SPI2 | MOSI | **PI3** | AF5 |
| GPS 1 | UART4 | TX | **PD1** | AF8 |
| GPS 1 | UART4 | RX | **PD0** | AF8 |
| GPS 2 | UART7 | TX | **PF7** | AF7 |

## Reserved

| Pin | Why |
|---|---|
| PA13 | SWDIO (debug) |
| PA14 | SWCLK (debug) |
| PB3 | SWO (trace) |
| PC14 | OSC32_IN (LSE) |
| PC15 | OSC32_OUT (LSE) |
| PH0 | OSC_IN (HSE 16 MHz) |
| PH1 | OSC_OUT (HSE 16 MHz) |

## Plain GPIO

No alternate-function constraint, so these take whatever the
peripherals did not need - preferring the most contended pins, since
those are the ones no peripheral could use anyway.

| Net | Pin |
|---|---|
| IMU1A_CS | **PC1** |
| IMU1G_CS | **PA6** |
| IMU2_CS | **PA7** |
| IMU3_CS | **PB0** |
| FRAM_CS | **PB5** |
| IMU1A_DRDY | **PB9** |
| IMU1G_DRDY | **PA1** |
| IMU2_DRDY | **PA5** |
| IMU3_DRDY | **PA0** |
| BARO1_INT | **PA4** |
| BARO2_INT | **PB14** |
| MAG_DRDY | **PC5** |
| EN_3V3_IMU1 | **PC6** |
| EN_3V3_IMU2 | **PC7** |
| EN_3V3_IMU3 | **PD6** |
| EN_3V3_SENS | **PA15** |
| LED_R | **PA2** |
| LED_G | **PA8** |
| LED_B | **PB10** |
| SAFETY_SW | **PB2** |
| SAFETY_LED | **PB4** |
| SD_DETECT | **PB1** |
| VBUS_SENSE | **PE4** |
| BRICK_VALID | **PE5** |
| SERVO_VALID | **PF8** |
| USB_VALID | **PB11** |
| PG_3V3 | **PC0** |
| IMU1_RAIL_FLG | **PC4** |
| IMU2_RAIL_FLG | **PE8** |
| IMU3_RAIL_FLG | **PC2** |
| SENS_RAIL_FLG | **PE2** |
| CAN1_FLT | **PF10** |
| CAN2_FLT | **PF6** |

