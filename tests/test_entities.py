"""Tests for the entities of the ViewSonic Projector integration."""

from homeassistant.components.button import DOMAIN as BUTTON_DOMAIN, SERVICE_PRESS
from homeassistant.components.media_player import (
    ATTR_INPUT_SOURCE,
    ATTR_MEDIA_VOLUME_LEVEL,
    ATTR_MEDIA_VOLUME_MUTED,
    DOMAIN as MEDIA_PLAYER_DOMAIN,
    SERVICE_SELECT_SOURCE,
    SERVICE_VOLUME_DOWN,
    SERVICE_VOLUME_MUTE,
    SERVICE_VOLUME_SET,
)
from homeassistant.components.number import (
    ATTR_VALUE,
    DOMAIN as NUMBER_DOMAIN,
    SERVICE_SET_VALUE,
)
from homeassistant.components.remote import (
    ATTR_COMMAND,
    DOMAIN as REMOTE_DOMAIN,
    SERVICE_SEND_COMMAND,
)
from homeassistant.components.select import (
    ATTR_OPTION,
    DOMAIN as SELECT_DOMAIN,
    SERVICE_SELECT_OPTION,
)
from homeassistant.components.switch import DOMAIN as SWITCH_DOMAIN
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.viewsonic_projector.button import BUTTONS
from custom_components.viewsonic_projector.number import NUMBERS
from custom_components.viewsonic_projector.protocol import (
    COLOR_MODES,
    PowerState,
    Query,
)
from custom_components.viewsonic_projector.select import SELECTS
from custom_components.viewsonic_projector.sensor import SENSORS
from custom_components.viewsonic_projector.switch import SWITCHES

from .conftest import entity_id
from .fake_projector import FakeProjector, addr


async def _refresh(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Poll the projector now, re-reading every setting."""
    entry.runtime_data.invalidate_settings()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def test_media_player(
    hass: HomeAssistant, init_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """Power, source, volume and mute."""
    player = entity_id(hass, "media_player", "projector")
    state = hass.states.get(player)
    assert state.state == STATE_ON
    assert state.attributes["source"] == "hdmi_1"
    assert state.attributes["source_list"] == ["hdmi_1", "hdmi_2"]
    assert state.attributes[ATTR_MEDIA_VOLUME_LEVEL] == 0.5
    assert state.attributes[ATTR_MEDIA_VOLUME_MUTED] is False

    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN,
        SERVICE_SELECT_SOURCE,
        {ATTR_ENTITY_ID: player, ATTR_INPUT_SOURCE: "hdmi_2"},
        blocking=True,
    )
    assert projector.value(Query.INPUT_SOURCE) == 0x07
    assert hass.states.get(player).attributes["source"] == "hdmi_2"

    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN,
        SERVICE_VOLUME_SET,
        {ATTR_ENTITY_ID: player, ATTR_MEDIA_VOLUME_LEVEL: 0.8},
        blocking=True,
    )
    assert projector.value(Query.VOLUME) == 8
    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN,
        SERVICE_VOLUME_DOWN,
        {ATTR_ENTITY_ID: player},
        blocking=True,
    )
    assert projector.value(Query.VOLUME) == 7
    assert hass.states.get(player).attributes[ATTR_MEDIA_VOLUME_LEVEL] == 0.7

    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN,
        SERVICE_VOLUME_MUTE,
        {ATTR_ENTITY_ID: player, ATTR_MEDIA_VOLUME_MUTED: True},
        blocking=True,
    )
    assert projector.value(Query.MUTE) == 1
    assert hass.states.get(player).attributes[ATTR_MEDIA_VOLUME_MUTED] is True


async def test_power_cycle(
    hass: HomeAssistant, init_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """Turning off leaves standby-readable sensors available."""
    player = entity_id(hass, "media_player", "projector")
    power_status = entity_id(hass, "sensor", "power_status")
    color_mode = entity_id(hass, "select", "color_mode")
    hours = entity_id(hass, "sensor", "light_source_hours")
    temperature = entity_id(hass, "sensor", "operating_temperature")
    assert hass.states.get(hours).state == "1234"
    assert hass.states.get(temperature).state == "29.7"

    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: player}, blocking=True
    )
    assert projector.power is PowerState.OFF
    assert hass.states.get(power_status).state == "cooling_down"
    assert hass.states.get(player).state == STATE_OFF

    await _refresh(hass, init_integration)
    assert hass.states.get(power_status).state == "off"
    assert hass.states.get(color_mode).state == STATE_UNAVAILABLE
    assert hass.states.get(temperature).state == STATE_UNAVAILABLE
    assert hass.states.get(hours).state == "1234"

    # Settings cannot be changed while the projector is off. (Settings
    # entities are unavailable then, so Home Assistant does not even call them;
    # the media player stays available to be turned on.)
    with pytest.raises(HomeAssistantError, match="must be on"):
        await hass.services.async_call(
            MEDIA_PLAYER_DOMAIN,
            SERVICE_VOLUME_SET,
            {ATTR_ENTITY_ID: player, ATTR_MEDIA_VOLUME_LEVEL: 0.3},
            blocking=True,
        )

    projector.warm_up = True
    await hass.services.async_call(
        MEDIA_PLAYER_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: player}, blocking=True
    )
    await _refresh(hass, init_integration)
    assert hass.states.get(power_status).state == "warming_up"
    assert hass.states.get(player).state == STATE_ON
    with pytest.raises(HomeAssistantError, match="warming up"):
        await hass.services.async_call(
            MEDIA_PLAYER_DOMAIN,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: player},
            blocking=True,
        )

    projector.power = PowerState.ON
    projector.set_value(Query.COLOR_MODE, COLOR_MODES["gaming"])
    await _refresh(hass, init_integration)
    assert hass.states.get(color_mode).state == "gaming"


async def test_select(
    hass: HomeAssistant, init_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """Selects show and change enumerated settings."""
    color_mode = entity_id(hass, "select", "color_mode")
    assert hass.states.get(color_mode).state == "standard"
    await hass.services.async_call(
        SELECT_DOMAIN,
        SERVICE_SELECT_OPTION,
        {ATTR_ENTITY_ID: color_mode, ATTR_OPTION: "movie"},
        blocking=True,
    )
    assert projector.value(Query.COLOR_MODE) == COLOR_MODES["movie"]
    assert hass.states.get(color_mode).state == "movie"

    # The LX700-4K profile narrows down the aspect ratios.
    aspect = hass.states.get(entity_id(hass, "select", "aspect_ratio"))
    assert aspect.attributes["options"] == ["auto", "4_3", "16_9", "native"]

    # An undocumented value shows as unknown.
    projector.set_value(Query.COLOR_MODE, 0x30)
    await _refresh(hass, init_integration)
    assert hass.states.get(color_mode).state == STATE_UNKNOWN


async def test_select_rejected(
    hass: HomeAssistant, init_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """A command the projector refuses raises a helpful error."""
    projector.disabled.add(addr(Query.COLOR_TEMPERATURE))
    with pytest.raises(HomeAssistantError, match="refused the command"):
        await hass.services.async_call(
            SELECT_DOMAIN,
            SERVICE_SELECT_OPTION,
            {
                ATTR_ENTITY_ID: entity_id(hass, "select", "color_temperature"),
                ATTR_OPTION: "warm",
            },
            blocking=True,
        )


async def test_greyed_out_setting_is_unavailable(
    hass: HomeAssistant, init_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """Settings the projector reports as disabled are unavailable."""
    projector.disabled.add(addr(Query.ASPECT_RATIO))
    await _refresh(hass, init_integration)
    assert (
        hass.states.get(entity_id(hass, "select", "aspect_ratio")).state
        == STATE_UNAVAILABLE
    )


async def test_number_steps_to_value(
    hass: HomeAssistant, init_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """Step-only values are moved to the requested value."""
    contrast = entity_id(hass, "number", "contrast")
    state = hass.states.get(contrast)
    assert state.state == "-10"
    assert state.attributes["min"] == -50
    assert state.attributes["max"] == 50

    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: contrast, ATTR_VALUE: 12},
        blocking=True,
    )
    assert projector.value(Query.CONTRAST) == 12
    assert hass.states.get(contrast).state == "12"


@pytest.mark.usefixtures("enable_all_entities")
async def test_number_direct_and_rgb(
    hass: HomeAssistant, init_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """Directly writable values and per-channel steps."""
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: entity_id(hass, "number", "brilliant_color"), ATTR_VALUE: 9},
        blocking=True,
    )
    assert projector.value(Query.BRILLIANT_COLOR) == 9

    red_gain = entity_id(hass, "number", "red_gain")
    await hass.services.async_call(
        NUMBER_DOMAIN,
        SERVICE_SET_VALUE,
        {ATTR_ENTITY_ID: red_gain, ATTR_VALUE: 47},
        blocking=True,
    )
    assert projector.value(Query.RED_GAIN) == 47


async def test_switch(
    hass: HomeAssistant, init_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """Switches toggle on/off settings."""
    blank = entity_id(hass, "switch", "blank")
    assert hass.states.get(blank).state == STATE_OFF
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: blank}, blocking=True
    )
    assert projector.value(Query.BLANK) == 1
    assert hass.states.get(blank).state == STATE_ON


@pytest.mark.usefixtures("enable_all_entities")
async def test_spdif_switch(
    hass: HomeAssistant, init_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """S/PDIF is written through the audio mode command and read separately."""
    spdif = entity_id(hass, "switch", "spdif")
    assert hass.states.get(spdif).state == STATE_OFF
    await hass.services.async_call(
        SWITCH_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: spdif}, blocking=True
    )
    assert projector.value(Query.SPDIF) == 0
    assert hass.states.get(spdif).state == STATE_ON
    # The audio mode itself is untouched.
    assert projector.value(Query.AUDIO_MODE) == 0x04


async def test_remote(
    hass: HomeAssistant, init_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """Remote commands are sent as key presses."""
    remote = entity_id(hass, "remote", "remote")
    assert hass.states.get(remote).state == STATE_ON
    await hass.services.async_call(
        REMOTE_DOMAIN,
        SERVICE_SEND_COMMAND,
        {ATTR_ENTITY_ID: remote, ATTR_COMMAND: ["menu", "down", "enter"]},
        blocking=True,
    )
    assert projector.actions == [
        ((0x02, 0x04), b"\x0f"),
        ((0x02, 0x04), b"\x0c"),
        ((0x02, 0x04), b"\x15"),
    ]

    with pytest.raises(ServiceValidationError, match="Unknown remote command"):
        await hass.services.async_call(
            REMOTE_DOMAIN,
            SERVICE_SEND_COMMAND,
            {ATTR_ENTITY_ID: remote, ATTR_COMMAND: ["self_destruct"]},
            blocking=True,
        )


@pytest.mark.usefixtures("enable_all_entities")
async def test_button(
    hass: HomeAssistant, init_integration: MockConfigEntry, projector: FakeProjector
) -> None:
    """Buttons send one-shot commands."""
    await hass.services.async_call(
        BUTTON_DOMAIN,
        SERVICE_PRESS,
        {ATTR_ENTITY_ID: entity_id(hass, "button", "reset_color_settings")},
        blocking=True,
    )
    assert projector.actions == [((0x11, 0x2A), b"\x00")]


@pytest.mark.usefixtures("enable_all_entities")
async def test_all_entities_have_names(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Every entity resolves a translated name (no missing translation keys)."""
    states = [
        state
        for state in hass.states.async_all()
        if state.entity_id.split(".")[1].startswith("viewsonic_lx700_4k")
    ]
    expected = (
        len(SWITCHES) + len(SELECTS) + len(NUMBERS) + len(SENSORS) + len(BUTTONS)
    ) + 3  # media player, remote, power status sensor
    assert len(states) == expected
    for state in states:
        assert state.attributes.get("friendly_name"), state.entity_id
        assert "none" not in state.entity_id, state.entity_id
