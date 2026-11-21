# ViewSonic Projector for Home Assistant

Control ViewSonic projectors from Home Assistant over their RS-232 port. Serial
ports can be local (USB adapters) or remote, including **ESPHome serial
proxies such as the Home Assistant Connect AUX-2**, which appear in the serial
port picker automatically.

The integration implements ViewSonic's *Projector RS-232/LAN Control Protocol
Specification V1.5* (available from ViewSonic's support site), which covers all
ViewSonic projectors. It has a tailored profile for the **LX700-4K** and works with other
models through a generic profile.

Requires Home Assistant **2026.11** or newer.

## Features

- Power control and **status monitoring while off**: power state (off, on,
  warming up, cooling down) is polled every few seconds, including in standby.
- A media player for power, input, volume and mute, and a remote entity that
  emulates the IR remote (menu navigation, etc.).
- Picture, light source, audio, 3D, HDMI, geometry and installation settings as
  select, number and switch entities.
- Light source hours and operating temperature sensors. Light source hours stay
  available while the projector is off.
- Raw `read` and `write` actions for anything else in the specification, and a
  `probe` action that reports which functions your model supports.
- Only enabled entities are polled, and settings are polled only while the
  projector is on. Following the specification, no commands are sent while it
  warms up or cools down.

## Installation

### HACS / Home Assistant Marketplace

1. Add this repository as a custom repository of type **Integration**:
   `https://github.com/timothyb89/homeassistant-viewsonic-projector`
2. Download **ViewSonic Projector** and restart Home Assistant.

### Manually

Copy `custom_components/viewsonic_projector` into your Home Assistant
`config/custom_components/` directory and restart Home Assistant.

## Hardware

The projector has a DB-9 RS-232 port; only RX, TX and ground are used. Depending
on your adapter you may need a null-modem (crossover) cable or adapter. If the
projector doesn't respond, try swapping TX and RX first.

Default settings are 115200 baud, 8 data bits, no parity, 1 stop bit, no flow
control. The baud rate can be changed in the projector's menu (supported:
2400, 4800, 9600, 14400, 19200, 38400, 115200).

### Home Assistant Connect AUX-2 / ESPHome serial proxy

1. Set up the AUX-2 (or any ESPHome device with a `serial_proxy`) in the ESPHome
   integration and configure its UART for the projector's baud rate.
2. Wire the projector's RS-232 port to it.
3. When adding the ViewSonic Projector integration, pick the AUX-2's port in the
   serial port list.

If the ESPHome device is offline when Home Assistant starts, the projector entry
retries until the proxy is available.

## Configuration

**Settings → Devices & services → Add integration → ViewSonic Projector**, then
choose:

- **Serial port**: a local port or a serial proxy.
- **Baud rate**: must match the projector (115200 by default).
- **Model**: pick `LX700-4K` or type your model name. Unknown models use the
  generic profile, which offers every input and option in the specification.

Setup checks that the projector answers a power status query. Some models only
answer over RS-232 while they are on, so if setup fails, turn the projector on
and try again.

**Options:** power status poll interval (default 5 s), settings refresh interval
(default 30 s), and which inputs the media player offers. You can change the
port, baud rate or model with **Reconfigure**.

## Entities

Entities marked *(off)* are disabled by default. Enable the ones your model
supports and you want to use; disabled entities aren't polled.

| Platform | Entities |
| --- | --- |
| Media player | Power, input source, volume, mute |
| Remote | Key presses: `menu`, `exit`, `up`, `down`, `left`, `right`, `enter`, `source`, `auto`, `my_button`, `bluetooth`, `return`, `next_track`, `previous_track`, `play`, `sub_menu`, `home`, `focus_near`, `focus_far`, `volume_up`, `volume_down`, `power`; cycles: `aspect_ratio`, `color_mode`, `light_source_mode`, `audio_mode` |
| Sensor | Power status, light source hours, operating temperature, equivalent light source hours *(off)* |
| Select | Color mode, light source mode, aspect ratio, color temperature, projector position; gamma, HDR, HDR EOTF, frame interpolation, audio mode, 3D sync, HDMI color format, HDMI range, primary color, splash screen, screen color, menu language, remote control code *(off)* |
| Number | Brightness, contrast, sharpness; hue, saturation, color gain, BrilliantColor, keystone (H/V), image position (H/V), digital lens shift (H/V), overscan, RGB gain and offset *(off)* |
| Switch | Blank screen, freeze, HDMI CEC, auto source, high altitude mode; quick power off, on-screen messages, 3D sync invert, ISF mode, 360° projection, S/PDIF output *(off)* |
| Button | Auto adjust, reset color settings, reset all settings, reset light source hours *(off)* |

Example: open the menu and move down twice.

```yaml
action: remote.send_command
target:
  entity_id: remote.viewsonic_lx700_4k_remote
data:
  command: [menu, down, down]
  delay_secs: 0.3
```

### How numbers are set

The protocol can only *increase* or *decrease* most picture values (brightness,
contrast, keystone, ...). When you set such a number, the integration steps it
towards the target and reads it back, stopping at the projector's limits. Large
changes can take a few seconds. BrilliantColor, overscan and volume are set
directly.

### Unavailable entities

The projector reports functions as unavailable when they are greyed out in its
menu, for example picture settings without an input signal or functions your
model doesn't have. The matching entities show as unavailable.

## Actions

| Action | Description |
| --- | --- |
| `viewsonic_projector.probe` | Reads every query in the specification and returns the raw results (`ok`, `disabled` or `timeout`). Run it with the projector on and a signal present to see what your model supports. |
| `viewsonic_projector.read` | Sends a read command, e.g. `code: "0x12 0x0B"` (color mode). Returns the data bytes and their decoded values. |
| `viewsonic_projector.write` | Sends a write command, e.g. `code: "0x12 0x0B"`, `data: "0x04"`. |

The command codes are the `cmd2 cmd3` bytes from section 3.3 of the specification.

## Known limitations and open questions

The integration was built from the specification and the LX700-4K user guide,
and tested against a protocol simulator, but **not yet against real hardware**.
In particular:

- **Option names per model.** The LX700-4K's menu uses names such as *Cinema*,
  *Bright*, *HDR*, *HLG*, *Bitstream/PCM* and a *Film/Video/Graphics* gamma that
  don't map one-to-one onto the specification. Color mode, gamma, color
  temperature, light source mode and audio mode therefore offer the
  specification's full lists. If the projector reports a value that isn't in the
  specification, the select shows *unknown* and the value is logged. Running
  `probe` while switching modes on the projector reveals the codes it uses.
- **Value ranges.** The LX700-4K profile uses the menu's ranges (e.g. brightness
  −50 to 50). If the projector reports values on a different scale over RS-232,
  the profile needs adjusting.
- **Possible errors in the specification.** For HDR (Auto/SDR) and 360°
  projection, the specification's read-back example values contradict the write
  values. The integration assumes a read returns the value written. S/PDIF
  follows the specification literally (reads `0` for on).
- **Standby.** Whether a model answers queries in standby varies. Power status is
  always polled, and light source hours are read once per standby period if the
  projector answers.
- **Unanswered queries.** The specification says unsupported functions reply
  with a "disabled" packet. If a model instead ignores some queries, the
  integration stops asking after two unanswered attempts (while the projector
  answers everything else) until the projector is next turned on, so a few
  unsupported entities can't slow down polling.
- The protocol has no unique device identifier, so each serial port can be
  configured once.

Diagnostics (**Download diagnostics** on the device page) include the
last-read values and the projector's service error counters.

## Development

```bash
uv sync
uv run ruff check custom_components tests
uv run python -m pytest   # Linux or macOS (Home Assistant does not run on Windows; use WSL)
```

Tests drive the integration through serialx against a simulated projector
(`tests/fake_projector.py`) served on `socket://127.0.0.1`. The protocol module
(`protocol.py`, `client.py`) has no Home Assistant dependencies.

`tests/ha_bootstrap.py` bridges the newest test harness release (built for
2026.10) to Home Assistant 2026.11. Remove it once a 2026.11 harness is
released.

## License

[Apache License 2.0](LICENSE). ViewSonic is a trademark of ViewSonic
Corporation; this project is not affiliated with or endorsed by ViewSonic.
