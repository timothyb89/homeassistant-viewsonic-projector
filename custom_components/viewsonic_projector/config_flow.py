"""Config flow for the ViewSonic Projector integration."""

from typing import Any, override

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_DEVICE, CONF_SCAN_INTERVAL, UnitOfTime
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    SerialPortSelector,
)
import probatio

from .client import ProjectorConnectionError, ProjectorError, ViewSonicProjector
from .const import (
    CONF_BAUD_RATE,
    CONF_MODEL,
    CONF_SETTINGS_INTERVAL,
    CONF_SOURCES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SETTINGS_INTERVAL,
    DOMAIN,
    LOGGER,
    MANUFACTURER,
    PROFILES,
    get_profile,
)
from .protocol import BAUD_RATES, DEFAULT_BAUD_RATE, INPUT_SOURCES

# The port works, but nothing answered the power status query.
RESULT_NO_RESPONSE = "no_response"

DATA_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_DEVICE): SerialPortSelector(),
        probatio.Required(
            CONF_BAUD_RATE, default=str(DEFAULT_BAUD_RATE)
        ): SelectSelector(
            SelectSelectorConfig(
                options=[str(rate) for rate in BAUD_RATES],
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
        probatio.Required(CONF_MODEL): SelectSelector(
            SelectSelectorConfig(
                options=list(PROFILES),
                custom_value=True,
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
    }
)


async def async_test_connection(port: str, baud_rate: int) -> str | None:
    """Try to talk to a projector; return None or an error key."""
    client = ViewSonicProjector(port, baud_rate)
    try:
        await client.connect()
        await client.get_power_state()
    except ProjectorConnectionError:
        return "cannot_connect"
    except ProjectorError:
        return RESULT_NO_RESPONSE
    except HomeAssistantError as err:
        # e.g. the ESPHome device providing a serial proxy is not loaded
        LOGGER.debug("Unable to open %s: %s", client.safe_port, err)
        return "cannot_connect"
    except Exception:
        LOGGER.exception("Unexpected error connecting to %s", client.safe_port)
        return "unknown"
    finally:
        await client.disconnect()
    return None


def _entry_data(user_input: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_DEVICE: user_input[CONF_DEVICE],
        CONF_BAUD_RATE: int(user_input[CONF_BAUD_RATE]),
        CONF_MODEL: user_input[CONF_MODEL].strip(),
    }


def _form_values(data: dict[str, Any]) -> dict[str, Any]:
    return {**data, CONF_BAUD_RATE: str(data.get(CONF_BAUD_RATE, DEFAULT_BAUD_RATE))}


class ViewSonicProjectorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for ViewSonic projectors."""

    VERSION = 1

    _user_input: dict[str, Any] | None = None

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select the serial port and model."""
        errors: dict[str, str] = {}

        if user_input is not None:
            data = _entry_data(user_input)
            self._async_abort_entries_match({CONF_DEVICE: data[CONF_DEVICE]})
            error = await async_test_connection(data[CONF_DEVICE], data[CONF_BAUD_RATE])
            if error is None:
                return self.async_create_entry(
                    title=f"{MANUFACTURER} {data[CONF_MODEL]}", data=data
                )
            if error == RESULT_NO_RESPONSE:
                self._user_input = user_input
                return await self.async_step_troubleshoot()
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                DATA_SCHEMA, user_input or self._user_input or {}
            ),
            errors=errors,
        )

    async def async_step_troubleshoot(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Explain why the projector may not be answering."""
        if user_input is not None:
            return await self.async_step_user()
        return self.async_show_form(step_id="troubleshoot")

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the serial port, baud rate or model."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            data = _entry_data(user_input)
            if data[CONF_DEVICE] != entry.data[CONF_DEVICE]:
                self._async_abort_entries_match({CONF_DEVICE: data[CONF_DEVICE]})
            error = await async_test_connection(data[CONF_DEVICE], data[CONF_BAUD_RATE])
            if error is None:
                return self.async_update_reload_and_abort(
                    entry, title=f"{MANUFACTURER} {data[CONF_MODEL]}", data=data
                )
            errors["base"] = "cannot_connect" if error == RESULT_NO_RESPONSE else error

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                DATA_SCHEMA, user_input or _form_values(dict(entry.data))
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlowWithReload:
        """Create the options flow."""
        return ViewSonicProjectorOptionsFlow()


class ViewSonicProjectorOptionsFlow(OptionsFlowWithReload):
    """Polling intervals and the inputs offered by the media player."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL]),
                    CONF_SETTINGS_INTERVAL: int(user_input[CONF_SETTINGS_INTERVAL]),
                    CONF_SOURCES: user_input[CONF_SOURCES],
                }
            )

        profile = get_profile(self.config_entry.data.get(CONF_MODEL))
        schema = probatio.Schema(
            {
                probatio.Required(
                    CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=2,
                        max=300,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement=UnitOfTime.SECONDS,
                    )
                ),
                probatio.Required(
                    CONF_SETTINGS_INTERVAL, default=DEFAULT_SETTINGS_INTERVAL
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=5,
                        max=3600,
                        step=1,
                        mode=NumberSelectorMode.BOX,
                        unit_of_measurement=UnitOfTime.SECONDS,
                    )
                ),
                probatio.Required(
                    CONF_SOURCES, default=list(profile.sources)
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=list(INPUT_SOURCES),
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                        translation_key="source",
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                schema, self.config_entry.options
            ),
        )
