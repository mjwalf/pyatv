"""Tests for event-driven AirPlay 2 video playback."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from pyatv.exceptions import HttpError, PlaybackError
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
    monkeypatch.setattr(protocol, "_setup_ptp_session", setup)
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


@pytest.mark.parametrize("status_code", [None, 400, 503])
async def test_audio_retries_rejected_ntp_setup_with_ptp(monkeypatch, status_code):
    protocol = receiver()
    ntp_setup = AsyncMock(
        side_effect=(
            HttpError("NTP setup rejected", status_code)
            if status_code is not None
            else None
        )
    )
    ptp_setup = AsyncMock()
    audio_setup = AsyncMock()
    monkeypatch.setattr(protocol, "_setup_base", ntp_setup)
    monkeypatch.setattr(protocol, "_setup_ptp_session", ptp_setup)
    monkeypatch.setattr(protocol, "setup_audio_stream", audio_setup)

    if status_code == 503:
        with pytest.raises(HttpError, match="NTP setup rejected"):
            await protocol.setup(49152, 49153)
    else:
        await protocol.setup(49152, 49153)

    ntp_setup.assert_awaited_once_with(49152)
    if status_code == 400:
        ptp_setup.assert_awaited_once_with()
    else:
        ptp_setup.assert_not_awaited()
    if status_code == 503:
        audio_setup.assert_not_awaited()
    else:
        audio_setup.assert_awaited_once_with(49153)
