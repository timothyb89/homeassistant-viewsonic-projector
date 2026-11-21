"""Constants for the ViewSonic Projector integration."""

from collections.abc import Mapping
from dataclasses import dataclass, field
import logging
from typing import Final

from .protocol import INPUT_SOURCES, Query

LOGGER = logging.getLogger(__package__)

DOMAIN: Final = "viewsonic_projector"
MANUFACTURER: Final = "ViewSonic"

CONF_BAUD_RATE: Final = "baud_rate"
CONF_MODEL: Final = "model"
CONF_SETTINGS_INTERVAL: Final = "settings_interval"
CONF_SOURCES: Final = "sources"

DEFAULT_SCAN_INTERVAL: Final = 5
DEFAULT_SETTINGS_INTERVAL: Final = 30

# Queries the projector may still answer in standby. Everything else is only
# read while the projector is on (the specification asks not to send commands
# while it is warming up or cooling down).
STANDBY_QUERIES: Final = frozenset(
    {Query.LIGHT_SOURCE_HOURS, Query.EQUIVALENT_LIGHT_SOURCE_HOURS}
)


@dataclass(frozen=True, kw_only=True, slots=True)
class ModelProfile:
    """What is known about a projector model beyond the generic protocol.

    The protocol specification covers every ViewSonic projector, so it lists
    inputs and options that a particular model may not have. A profile narrows
    the user interface down to what the model's user guide documents.
    """

    sources: tuple[str, ...] = tuple(INPUT_SOURCES)
    volume_max: int = 20
    # Entity key -> (min, max) for number entities.
    ranges: Mapping[str, tuple[int, int]] = field(default_factory=dict)
    # Entity key -> options to offer for select entities.
    options: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


GENERIC_PROFILE: Final = ModelProfile()

PROFILES: Final[Mapping[str, ModelProfile]] = {
    # LX700-4K user guide, "On-Screen Display (OSD) Menu Tree".
    "LX700-4K": ModelProfile(
        sources=("hdmi_1", "hdmi_2"),
        volume_max=10,
        ranges={
            "brightness": (-50, 50),
            "contrast": (-50, 50),
            "sharpness": (1, 15),
            "hue": (-50, 50),
            "saturation": (-50, 50),
            "keystone_horizontal": (-30, 30),
            "keystone_vertical": (-30, 30),
            "brilliant_color": (1, 10),
        },
        options={
            "aspect_ratio": ("auto", "4_3", "16_9", "native"),
            "three_d_sync": (
                "off",
                "auto",
                "frame_sequential",
                "top_bottom",
                "side_by_side",
            ),
        },
    ),
}


def get_profile(model: str | None) -> ModelProfile:
    """Return the profile for a model, falling back to the generic one."""
    if model is None:
        return GENERIC_PROFILE
    for name, profile in PROFILES.items():
        if name.casefold() == model.strip().casefold():
            return profile
    return GENERIC_PROFILE
