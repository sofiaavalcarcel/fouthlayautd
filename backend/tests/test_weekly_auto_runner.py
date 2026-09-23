"""Regresiones del runner de capturas semanales."""

import asyncio

import pytest

from backend.app.automations.weekly_auto.weekly_photos.runner import (
    WeeklyAutoRunner as AutomationWeeklyPhotosRunner,
)
from backend.app.modules.weekly_auto.runner import WeeklyAutoError, WeeklyAutoRunner
from backend.app.modules.weekly_auto.weekly_photos.runner import (
    WeeklyAutoError as WeeklyPhotosError,
    WeeklyAutoRunner as WeeklyPhotosRunner,
)


class _Settings:
    def __init__(self, storage_dir):
        self.storage_dir = storage_dir


class _FailingPage:
    async def screenshot(self, **kwargs):
        raise RuntimeError("fallo simulado")


class _InfiniteScrollPage:
    def __init__(self):
        self.height_reads = 0
        self.scrolls = 0

    async def evaluate(self, script, *args):
        if "document.body.scrollHeight" in script:
            self.height_reads += 1
            return 1_000 + self.height_reads * 500
        if "window.innerHeight" in script:
            return 500
        if "scrollTo" in script:
            self.scrolls += 1
        return None

    async def wait_for_timeout(self, pause_ms):
        return None


def test_public_runner_points_to_weekly_photos_submodule():
    assert WeeklyAutoRunner is WeeklyPhotosRunner is AutomationWeeklyPhotosRunner
    assert WeeklyAutoError is WeeklyPhotosError


def test_url_validation_only_accepts_http_and_https(tmp_path):
    runner = WeeklyAutoRunner(_Settings(tmp_path))

    assert runner._is_valid_url("https://example.com/ruta")
    assert runner._is_valid_url("http://example.com")
    assert not runner._is_valid_url("file://server/archivo")
    assert not runner._is_valid_url("ftp://example.com/archivo")
    assert not runner._is_valid_url("example.com")


def test_screenshot_failure_is_reported_as_error(tmp_path):
    runner = WeeklyAutoRunner(_Settings(tmp_path))
    runner.evidence_directory = tmp_path

    with pytest.raises(WeeklyAutoError, match="No fue posible guardar"):
        asyncio.run(runner._save_screenshot(_FailingPage(), "https://example.com", 1))

    assert runner.screenshots == []


def test_infinite_scroll_has_a_safety_limit(tmp_path):
    runner = WeeklyAutoRunner(_Settings(tmp_path))
    page = _InfiniteScrollPage()

    asyncio.run(runner._progressive_scroll(page, pause_ms=1))

    assert page.height_reads == 101
    assert page.scrolls == 101  # 100 avances y el retorno al inicio.
