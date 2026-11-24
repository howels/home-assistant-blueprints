import shutil
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def remove_blueprint_copy(hass):
    """The harness copies the blueprint into the test configuration directory."""
    yield
    shutil.rmtree(Path(hass.config.path("blueprints/automation/howels")), ignore_errors=True)


@pytest.fixture
def expected_lingering_timers() -> bool:
    """The blueprint's time and time_pattern triggers leave timers armed at teardown."""
    return True
