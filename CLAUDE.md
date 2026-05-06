# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Python bridge that reads data from a **Heidelberg Energy Control EV wallbox** over Modbus RTU (RS-485 via USB adapter) and publishes it to MQTT using the [Homie convention](https://homieiot.github.io/). Also accepts `max_current` commands via MQTT to control the charging current. Designed for integration with openHAB and similar smart home systems.

## Running the Connector

```bash
# Install dependencies
pip3 install minimalmodbus pyserial paho-mqtt

# Configure (copy and edit)
cp config.ini.sample config.ini

# Run
python3 wallbox-connector.py
```

```bash
# Run via Docker (note: requirements.txt must be created first)
docker build -t wallbox-connector .
docker run wallbox-connector
```

There is no test suite and no linting configuration.

## Configuration

`config.ini` (gitignored) is read once at startup from `config.ini.sample`:

- `[general]` — log path and filename
- `[MQTT Broker Config]` — `broker_IP`, `broker_port`, `user`, `password`
- `[Modbus Config]` — `usb_device` (e.g. `/dev/ttyUSB1`)

## Architecture

**Two files, two responsibilities:**

`heidelberg.py` — `wallbox` class, the Modbus abstraction layer:
- Wraps `minimalmodbus` for Modbus RTU communication (19200 baud, 8E1, RTU mode)
- Maintains a flat register cache (`cregs[0..819]`); reads are served from cache unless `force=True` or cache is stale (`cache_timeout` = 3000 ms)
- Auto-reconnect: if the bus fails, `self.wb` is set to `None` and `_reInitialize()` retries after `bus_retry_timeout` = 120 s
- On init: disables standby (register 258 = 4), disables watchdog (register 257 = 0), reads hw min/max current limits
- Modbus register layout version is in register 4; registers 258–259 (standby, remote lock) are read-only in layout < 1.0.8 — reading them causes a bus timeout, so only register 257 is read in that case
- Input registers (functioncode 4): status, measurements. Holding registers (functioncode 3): settings like current preset (261) and watchdog (257)

`wallbox-connector.py` — main script / MQTT bridge:
- Reads `config.ini`, instantiates `wallbox`, sets up `paho-mqtt` client
- Advertises the device under `homie/Heidelberg-Wallbox/` with node `wallbox` and properties `akt_verbrauch` (power, kW), `zaehlerstand` (total energy, kWh), `max_current` (settable, A)
- Subscribes to `homie/Heidelberg-Wallbox/wallbox/max_current/set`; received values are stored in the global `maxCurrent` and written to the wallbox on the next loop iteration
- Main loop polls every 10 s; on shutdown (exception or `finally`), publishes `disconnected` state and sets current preset to 0
- MQTT client runs in a background thread (`loop_start()`); 5 s startup delay waits for the initial retained `max_current` message before the main loop begins

## Key Modbus Register Map

| Register | Description |
|----------|-------------|
| 1 | Modbus client ID |
| 4 | Modbus register layout version |
| 5 | Charging state (2–11) |
| 6–8 | Current phases 1–3 (÷10 → A) |
| 9 | Temperature (÷10 → °C) |
| 10–12 | Voltage phases 1–3 (V) |
| 14 | Active power (÷1000 → kW) |
| 15–16 | Energy since power-on (high/low word, ÷1000 → kWh) |
| 17–18 | Total energy (high/low word, ÷1000 → kWh) |
| 100 | HW max current (A) |
| 101 | HW min current (A) |
| 102–133 | Logistic string (2 chars/register) |
| 257 | Modbus watchdog timeout (ms) |
| 258 | Standby function control |
| 259 | Remote lock |
| 261 | Current preset (×10 → wallbox unit; e.g. 160 = 16 A) |
| 300–318 | Diagnostic data |
| 500–819 | Error memory |
