"""Make pytest-homeassistant-custom-component 0.13.375 work with Home Assistant 2026.11.

The newest release of the test harness is built for Home Assistant 2026.10, while
this integration requires 2026.11. This plugin is loaded before the harness
(``-p tests.ha_bootstrap`` in pyproject.toml) and bridges the differences:

* Home Assistant 2026.11 aliases ``httpx`` to ``httpx2`` when it is first
  imported, which fails if ``httpx`` was imported before. The harness imports
  ``respx`` (and with it ``httpx``) before Home Assistant, so import it first.
* ``_clear_logger_overwrites`` moved to ``homeassistant.components.logger.helpers``.

Remove this module once a harness release for 2026.11 is available.
"""

import homeassistant  # noqa: F401  # isort:skip
from homeassistant.components import logger
from homeassistant.components.logger import helpers as logger_helpers

if not hasattr(logger, "_clear_logger_overwrites"):
    logger._clear_logger_overwrites = logger_helpers._clear_logger_overwrites  # type: ignore[attr-defined]
