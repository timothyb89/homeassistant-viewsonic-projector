"""Consistency checks for translations, icons, services and the manifest."""

import json
from pathlib import Path
import re

import yaml

from custom_components.viewsonic_projector.button import BUTTONS
from custom_components.viewsonic_projector.number import NUMBERS
from custom_components.viewsonic_projector.protocol import INPUT_SOURCES
from custom_components.viewsonic_projector.select import SELECTS
from custom_components.viewsonic_projector.sensor import (
    POWER_STATUS_OPTIONS,
    SENSORS,
)
from custom_components.viewsonic_projector.switch import SWITCHES

ROOT = Path(__file__).parent.parent / "custom_components" / "viewsonic_projector"
TRANSLATIONS = json.loads((ROOT / "translations" / "en.json").read_text("utf-8"))
ICONS = json.loads((ROOT / "icons.json").read_text("utf-8"))
MANIFEST = json.loads((ROOT / "manifest.json").read_text("utf-8"))
SERVICES = yaml.safe_load((ROOT / "services.yaml").read_text("utf-8"))

TRANSLATION_KEY = re.compile(r"^[a-z0-9]+(?:[_-][a-z0-9]+)*$")

ENTITY_KEYS = {
    "button": [d.translation_key for d in BUTTONS],
    "number": [d.translation_key for d in NUMBERS],
    "select": [d.translation_key for d in SELECTS],
    "sensor": [d.translation_key for d in SENSORS] + ["power_status"],
    "switch": [d.translation_key for d in SWITCHES],
    "remote": ["remote"],
}


def test_entity_names_and_icons() -> None:
    """Every entity has a translated name and an icon."""
    for platform, keys in ENTITY_KEYS.items():
        assert len(keys) == len(set(keys)), platform
        for key in keys:
            assert TRANSLATION_KEY.match(key), key
            assert TRANSLATIONS["entity"][platform][key]["name"], (platform, key)
            assert ICONS["entity"][platform][key]["default"].startswith("mdi:")
    assert ICONS["entity"]["media_player"]["projector"]["default"]


def test_select_states_translated() -> None:
    """Every select option has a translation, and no stale ones remain."""
    for description in SELECTS:
        states = TRANSLATIONS["entity"]["select"][description.translation_key]["state"]
        assert set(states) == set(description.values), description.key
        for option in description.values:
            assert TRANSLATION_KEY.match(option), option


def test_sources_and_power_states_translated() -> None:
    """Input sources and power states are translated everywhere they appear."""
    media_player = TRANSLATIONS["entity"]["media_player"]["projector"]
    assert set(media_player["state_attributes"]["source"]["state"]) == set(
        INPUT_SOURCES
    )
    assert set(TRANSLATIONS["selector"]["source"]["options"]) == set(INPUT_SOURCES)
    assert set(TRANSLATIONS["entity"]["sensor"]["power_status"]["state"]) == set(
        POWER_STATUS_OPTIONS
    )


def test_exceptions_translated() -> None:
    """Every translation_key raised in the code has a message."""
    used = set()
    for path in ROOT.glob("*.py"):
        used.update(re.findall(r'translation_key="([a-z_]+)"', path.read_text("utf-8")))
    entity_keys = {key for keys in ENTITY_KEYS.values() for key in keys}
    used -= entity_keys | {"projector", "source", "remote", "power_status"}
    assert used <= set(TRANSLATIONS["exceptions"]), used - set(
        TRANSLATIONS["exceptions"]
    )
    assert used == set(TRANSLATIONS["exceptions"])


def test_services() -> None:
    """Every action and field is translated and has an icon."""
    assert set(SERVICES) == set(TRANSLATIONS["services"]) == set(ICONS["services"])
    for service, definition in SERVICES.items():
        translated = TRANSLATIONS["services"][service]
        assert translated["name"]
        assert translated["description"]
        assert set(definition["fields"]) == set(translated["fields"]), service


def test_manifest() -> None:
    """The manifest has the keys hassfest and HACS require, in order."""
    keys = list(MANIFEST)
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])
    for key in (
        "codeowners",
        "config_flow",
        "documentation",
        "integration_type",
        "iot_class",
        "issue_tracker",
        "requirements",
        "version",
    ):
        assert key in MANIFEST, key
    hacs = json.loads((ROOT.parent.parent / "hacs.json").read_text("utf-8"))
    assert hacs["homeassistant"] == "2026.11.0"


def test_config_flow_strings() -> None:
    """Config and options flow fields are described."""
    for step in ("user", "reconfigure"):
        data = TRANSLATIONS["config"]["step"][step]
        assert set(data["data"]) == {"device", "baud_rate", "model"}
        assert set(data["data_description"]) == set(data["data"])
    options = TRANSLATIONS["options"]["step"]["init"]
    assert set(options["data"]) == {"scan_interval", "settings_interval", "sources"}
    assert set(options["data_description"]) == set(options["data"])
