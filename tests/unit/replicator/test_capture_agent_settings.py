"""Tests for runtime CDC capture tuning on CaptureAgent."""

from __future__ import annotations

from unittest.mock import MagicMock

from apps.replicator.capture.agent import CaptureAgent


def test_capture_agent_updates_poll_interval_and_batch_size():
    agent = CaptureAgent(provider=MagicMock(), publisher=MagicMock(), poll_interval_ms=1000, batch_size=1000)
    agent.set_poll_interval_ms(500)
    agent.set_batch_size(250)
    assert agent.poll_interval_ms == 500
    assert agent.batch_size == 250
