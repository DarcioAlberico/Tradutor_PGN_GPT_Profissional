from unittest.mock import patch

import pytest
import requests

from tradutor_pgn.deep_translation import DeepTranslatorAdapter
from tradutor_pgn.translation_api import RequestPacer, translate_text_chunk
from test_google_shared_network import Response, Shared


@pytest.mark.parametrize("provider", ["gtx", "deep"])
@pytest.mark.parametrize("status", [200, 403, 429])
def test_counts_actual_requests_characters_and_responses(provider, status):
    pacer = RequestPacer(base_range=(0, 0), shared_cooldown=Shared())
    with patch("requests.get", return_value=Response(status)):
        if provider == "gtx":
            translate_text_chunk("secret", "pt", pacer=pacer)
        else:
            DeepTranslatorAdapter("en", "pt").translate("secret", pacer=pacer)
    metrics = pacer.metrics
    assert metrics.attempts >= 1
    assert metrics.characters == 6 * metrics.attempts
    assert metrics.forbidden == (metrics.attempts if status == 403 else 0)
    assert metrics.rate_limited == (metrics.attempts if status == 429 else 0)
    assert "secret" not in repr(metrics)


@pytest.mark.parametrize("provider", ["gtx", "deep"])
def test_rejected_wait_is_not_a_network_attempt(provider):
    pacer = RequestPacer(shared_cooldown=Shared(allow=False))
    with patch("requests.get") as get:
        if provider == "gtx":
            translate_text_chunk("secret", "pt", pacer=pacer)
        else:
            DeepTranslatorAdapter("en", "pt").translate("secret", pacer=pacer)
    get.assert_not_called()
    assert pacer.metrics.attempts == 0


def test_network_exception_is_still_counted():
    pacer = RequestPacer(shared_cooldown=Shared())
    with patch("requests.get", side_effect=requests.ConnectionError), patch("tradutor_pgn.translation_api.wait_for_server_delay", return_value=False):
        translate_text_chunk("secret", "pt", pacer=pacer)
    assert pacer.metrics.attempts == 3
    assert pacer.metrics.characters == 18


def test_shared_wait_records_elapsed_time_even_when_cancelled():
    pacer = RequestPacer(shared_cooldown=Shared(allow=False))
    with patch("tradutor_pgn.translation_api.time.monotonic", side_effect=[10.0, 12.5]):
        assert not pacer.wait_shared(None, None)
    assert pacer.metrics.shared_wait_seconds == 2.5


def test_deep_internal_retry_counts_each_actual_request():
    pacer = RequestPacer(base_range=(0, 0), shared_cooldown=Shared())
    response = Response(200)
    response.text = '<div class="result-container">Same</div>'
    with patch("requests.get", return_value=response) as get:
        adapter = DeepTranslatorAdapter("en", "pt")
        adapter.client._url_params["hl"] = "en"
        adapter.translate("Same", pacer=pacer)
    assert get.call_count >= 2
    assert pacer.metrics.attempts == get.call_count
    assert pacer.metrics.characters == 4 * get.call_count
