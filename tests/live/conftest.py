from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("XTRACTOR_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live tests are opt-in: set XTRACTOR_LIVE=1")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
