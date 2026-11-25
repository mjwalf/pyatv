"""Tests for event-driven AirPlay 2 video playback."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from pyatv.exceptions import PlaybackError
from pyatv.protocols.raop.protocols import StreamContext
from pyatv.protocols.raop.protocols.airplayv2 import AirPlayV2
from pyatv.support.rtsp import RtspSession

pytestmark = pytest.mark.asyncio


def receiver() -> AirPlayV2:
    """Return a receiver with an established playback control stream."""
    protocol = AirPlayV2(StreamContext(), RtspSession(MagicMock()))
    protocol._rcs_stream_id = 1
    return protocol


async def test_playback_wait_returns_when_the_receiver_finishes():
    protocol = receiver()
    protocol.handle_event({"type": "playbackState", "name": "playing"})
    protocol.handle_event({"type": "notification", "name": "itemPlayedToEnd"})

    assert await protocol.wait_for_media_end()


async def test_playback_wait_errors_when_the_receiver_stays_idle(monkeypatch):
    protocol = receiver()
    protocol.handle_event({"type": "playbackState", "name": "stopped"})
    monkeypatch.setattr(
        "pyatv.protocols.raop.protocols.airplayv2.PLAYBACK_START_TIMEOUT", 0.01
    )

    with pytest.raises(PlaybackError, match="did not start"):
        await protocol.wait_for_media_end()


async def test_play_url_uses_ptp_before_setting_up_remote_control(monkeypatch):
    steps = []
    protocol = receiver()

    async def verify(*_):
        steps.append("verify")

    async def setup():
        steps.append("ptp")

    async def record():
        steps.append("record")

    async def remote_control():
        steps.append("remote control")
        return True

    async def command(url, position):
        steps.append(("command", url, position))
        return MagicMock(code=200)

    async def feedback():
        steps.append("feedback")

    monkeypatch.setattr(
        "pyatv.protocols.raop.protocols.airplayv2.verify_connection", verify
    )
    monkeypatch.setattr(protocol, "_setup_video_session", setup)
    monkeypatch.setattr(protocol.rtsp, "record", record)
    monkeypatch.setattr(protocol, "_setup_remote_control_session", remote_control)
    monkeypatch.setattr(protocol, "_play_url_command", command)
    monkeypatch.setattr(protocol, "start_feedback", feedback)
    legacy_setup = AsyncMock()
    monkeypatch.setattr(protocol, "_setup_base", legacy_setup)

    response = await protocol.play_url(49152, "https://example.com/test.m3u8", 4)

    assert response.code == 200
    assert steps == [
        "verify",
        "ptp",
        "record",
        "remote control",
        ("command", "https://example.com/test.m3u8", 4),
        "feedback",
    ]
    legacy_setup.assert_not_awaited()


async def test_playback_wait_errors_if_event_channel_closes_during_start():
    protocol = receiver()
    protocol.handle_event_channel_closed()

    with pytest.raises(PlaybackError, match="closed before video started"):
        await protocol.wait_for_media_end()
