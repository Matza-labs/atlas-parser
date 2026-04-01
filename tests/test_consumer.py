"""Tests for atlas-parser stream consumer (__main__.py)."""

import json
from unittest.mock import MagicMock, patch

import pytest


class FakeResponseError(Exception):
    pass


class FakeExceptions:
    ResponseError = FakeResponseError


def _make_redis_mock(messages=None):
    client = MagicMock()
    client.xgroup_create.return_value = True
    if messages:
        client.xreadgroup.side_effect = [messages, KeyboardInterrupt]
    else:
        client.xreadgroup.side_effect = KeyboardInterrupt
    return client


def _make_redis_module(client):
    mock_mod = MagicMock()
    mock_mod.from_url.return_value = client
    mock_mod.exceptions = FakeExceptions
    return mock_mod


class TestParserConsumer:

    def test_creates_consumer_group(self):
        client = _make_redis_mock()
        mock_mod = _make_redis_module(client)

        with patch.dict("sys.modules", {"redis": mock_mod}):
            import importlib
            import atlas_parser.__main__ as mod
            importlib.reload(mod)
            mod.main()

        client.xgroup_create.assert_called_once_with(
            "atlas.scan.results", "atlas-parser", id="0", mkstream=True,
        )

    def test_acks_on_parse_failure(self):
        messages = [("atlas.scan.results", [("3-0", {"data": "{}"})])]
        client = _make_redis_mock(messages)
        mock_mod = _make_redis_module(client)

        with patch.dict("sys.modules", {"redis": mock_mod}):
            import importlib
            import atlas_parser.__main__ as mod
            importlib.reload(mod)
            mod.main()

        client.xack.assert_called_once_with("atlas.scan.results", "atlas-parser", "3-0")
