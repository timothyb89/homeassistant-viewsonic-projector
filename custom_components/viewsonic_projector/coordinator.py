"""Data update coordinator for the ViewSonic Projector integration."""

from collections.abc import Awaitable, Iterable
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import (
    CommandDisabledError,
    ProjectorConnectionError,
    ProjectorError,
    ProjectorTimeoutError,
    ViewSonicProjector,
)
from .const import (
    CONF_MODEL,
    CONF_SETTINGS_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SETTINGS_INTERVAL,
    DOMAIN,
    LOGGER,
    MANUFACTURER,
    STANDBY_QUERIES,
    ModelProfile,
    get_profile,
)
from .protocol import POWER_OFF, POWER_ON, Code, PowerState, Query

type ViewSonicConfigEntry = ConfigEntry[ViewSonicCoordinator]

# Some models may not answer queries they do not support (rather than replying
# "disabled"). Stop asking after this many unanswered attempts while the
# projector answers other queries, until it is turned on again.
_MAX_SILENT_STRIKES = 2


class ViewSonicCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls the projector and executes commands on behalf of entities."""

    config_entry: ViewSonicConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ViewSonicConfigEntry,
        client: ViewSonicProjector,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
            ),
            always_update=False,
        )
        self.client = client
        self.model: str | None = entry.data.get(CONF_MODEL)
        self.profile: ModelProfile = get_profile(self.model)
        self._settings_interval = float(
            entry.options.get(CONF_SETTINGS_INTERVAL, DEFAULT_SETTINGS_INTERVAL)
        )
        self._last_settings_refresh: float | None = None
        self._standby_attempted: set[Query] = set()
        self._silent_strikes: dict[Query, int] = {}
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer=MANUFACTURER,
            model=self.model,
            name=f"{MANUFACTURER} {self.model}" if self.model else entry.title,
        )

    # -- State helpers -----------------------------------------------------------

    @property
    def power_state(self) -> PowerState | None:
        """Return the last known power state."""
        if self.data is None:
            return None
        return self.data.get(Query.POWER)

    @property
    def is_on(self) -> bool:
        """Return whether the projector is on and accepting commands."""
        return self.power_state is PowerState.ON

    def value(self, query: Query) -> Any:
        """Return the last value read for a query."""
        if self.data is None:
            return None
        return self.data.get(query)

    def polled_queries(self) -> set[Query]:
        """Return the queries that enabled entities are listening to."""
        queries: set[Query] = set()
        for context in self.async_contexts():
            items: Iterable[Any] = (
                context if isinstance(context, (frozenset, set, tuple)) else (context,)
            )
            queries.update(item for item in items if isinstance(item, Query))
        queries.discard(Query.POWER)
        return queries

    # -- Polling -------------------------------------------------------------------

    async def _async_read_power(self) -> PowerState:
        if not self.client.connected:
            await self.client.connect()
            return await self.client.get_power_state()
        try:
            return await self.client.get_power_state()
        except ProjectorConnectionError:
            # The link dropped since the last poll (e.g. a serial proxy lost its
            # Wi-Fi connection); reconnect once rather than failing this poll.
            LOGGER.debug("Connection lost, reconnecting to %s", self.client.safe_port)
            await self.client.disconnect()
            await self.client.connect()
            return await self.client.get_power_state()

    async def _async_update_data(self) -> dict[str, Any]:
        data = dict(self.data or {})
        try:
            power = await self._async_read_power()
        except ProjectorError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        except HomeAssistantError as err:
            # e.g. the ESPHome integration providing a serial proxy is not ready
            raise UpdateFailed(str(err)) from err

        previous = data.get(Query.POWER)
        data[Query.POWER] = power

        if power is PowerState.ON:
            self._standby_attempted.clear()
            if previous is not PowerState.ON:
                self._silent_strikes.clear()
            polled = self.polled_queries()
            now = self.hass.loop.time()
            if (
                previous is not PowerState.ON
                or self._last_settings_refresh is None
                or now - self._last_settings_refresh >= self._settings_interval
            ):
                await self._async_read_queries(data, polled)
                self._last_settings_refresh = now
            else:
                # Entities enabled since the last refresh.
                await self._async_read_queries(
                    data, {query for query in polled if query not in data}
                )
        elif power is PowerState.OFF:
            # Some values may be readable in standby; try each once per standby.
            pending = (STANDBY_QUERIES & self.polled_queries()) - (
                self._standby_attempted
            )
            for query in pending:
                self._standby_attempted.add(query)
                try:
                    value = await self.client.read_value(query)
                except ProjectorTimeoutError:
                    continue
                except ProjectorError as err:
                    raise UpdateFailed(str(err)) from err
                if value is not None:
                    data[query] = value

        return data

    async def _async_read_queries(
        self, data: dict[str, Any], queries: Iterable[Query]
    ) -> None:
        for query in sorted(queries):
            if self._silent_strikes.get(query, 0) >= _MAX_SILENT_STRIKES:
                data[query] = None
                continue
            try:
                data[query] = await self.client.read_value(query)
            except ProjectorTimeoutError:
                data[query] = None
                await self._async_ensure_alive()
                # The projector answers other commands, just not this one.
                strikes = self._silent_strikes[query] = (
                    self._silent_strikes.get(query, 0) + 1
                )
                LOGGER.debug("No reply to %s (%s times)", query, strikes)
                if strikes >= _MAX_SILENT_STRIKES:
                    LOGGER.info(
                        "%s does not answer the %s query; not asking again until "
                        "it is turned on again",
                        self.device_info["name"],
                        query,
                    )
            except ProjectorError as err:
                raise UpdateFailed(
                    translation_domain=DOMAIN,
                    translation_key="update_failed",
                    translation_placeholders={"error": str(err)},
                ) from err
            else:
                self._silent_strikes.pop(query, None)

    async def _async_ensure_alive(self) -> None:
        """Fail the update if the projector stopped answering altogether."""
        try:
            await self.client.get_power_state()
        except ProjectorError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="not_responding"
            ) from err

    # -- Commands --------------------------------------------------------------------

    def _ensure_connected(self) -> None:
        if not self.client.connected or not self.last_update_success:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="not_connected"
            )

    def ensure_ready(self, *, require_on: bool = True) -> None:
        """Raise unless the projector can accept a command now.

        The specification asks not to send commands while the projector is
        warming up or cooling down.
        """
        self._ensure_connected()
        state = self.power_state
        if state in (PowerState.WARMING_UP, PowerState.COOLING_DOWN):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="projector_busy",
                translation_placeholders={
                    "state": state.name.lower().replace("_", " ")
                },
            )
        if require_on and state is not PowerState.ON:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="projector_off"
            )

    async def async_command[T](self, coro: Awaitable[T]) -> T:
        """Await a client call, translating errors for the user."""
        return await self._async_command(coro)

    async def _async_command[T](self, coro: Awaitable[T]) -> T:
        try:
            return await coro
        except CommandDisabledError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_rejected",
                translation_placeholders={"error": str(err)},
            ) from err
        except ProjectorError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def async_write(
        self,
        code: Code,
        data: bytes | int = 0,
        *,
        refresh: Query | Iterable[Query] | None = None,
        require_on: bool = True,
    ) -> None:
        """Send a write command, then re-read the affected values."""
        self.ensure_ready(require_on=require_on)
        await self._async_command(self.client.write(code, data))
        if refresh is not None:
            await self.async_refresh_queries(
                (refresh,) if isinstance(refresh, Query) else refresh
            )

    async def async_step_to(
        self, query: Query, step: Code, target: int, *, prefix: bytes = b""
    ) -> None:
        """Move an increase/decrease-only value to target."""
        self.ensure_ready()
        value = await self._async_command(
            self.client.step_to(query, step, target, prefix=prefix)
        )
        self.async_set_updated_data({**self.data, query: value})

    def invalidate_settings(self) -> None:
        """Re-read every setting at the next refresh."""
        self._last_settings_refresh = None

    async def async_request_settings_refresh(self) -> None:
        """Re-read every setting at the next refresh, which is requested now."""
        self.invalidate_settings()
        await self.async_request_refresh()

    async def async_refresh_queries(self, queries: Iterable[Query]) -> None:
        """Re-read values after a change and notify entities."""
        data = dict(self.data)
        for query in queries:
            try:
                data[query] = await self.client.read_value(query)
            except ProjectorError as err:
                LOGGER.debug("Unable to read back %s: %s", query, err)
        self.async_set_updated_data(data)

    async def async_turn_on(self) -> None:
        """Turn the projector on."""
        self._ensure_connected()
        state = self.power_state
        if state in (PowerState.ON, PowerState.WARMING_UP):
            return
        if state is PowerState.COOLING_DOWN:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="projector_busy",
                translation_placeholders={
                    "state": state.name.lower().replace("_", " ")
                },
            )
        await self._async_command(self.client.write(POWER_ON))
        self.async_set_updated_data({**self.data, Query.POWER: PowerState.WARMING_UP})

    async def async_turn_off(self) -> None:
        """Turn the projector off."""
        self._ensure_connected()
        state = self.power_state
        if state in (PowerState.OFF, PowerState.COOLING_DOWN):
            return
        if state is PowerState.WARMING_UP:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="projector_busy",
                translation_placeholders={
                    "state": state.name.lower().replace("_", " ")
                },
            )
        await self._async_command(self.client.write(POWER_OFF))
        self.async_set_updated_data({**self.data, Query.POWER: PowerState.COOLING_DOWN})

    async def async_shutdown(self) -> None:
        """Stop polling and close the serial connection."""
        await super().async_shutdown()
        await self.client.disconnect()
