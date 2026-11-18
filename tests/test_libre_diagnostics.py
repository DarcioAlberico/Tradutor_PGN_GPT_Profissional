from threading import Event

import requests

from tradutor_pgn.libre_translation import LibreTranslator, check_instance


class Response:
    def __init__(self, status, payload):
        self.status_code = status
        self.payload = payload
        self.closed = False

    def json(self):
        return self.payload

    def close(self):
        self.closed = True


def test_connection_test_checks_language_pair_without_sending_comments():
    calls = []
    response = Response(200, [{"code": "en", "targets": ["pt"]}, {"code": "pt", "targets": ["en"]}])
    def get(url, **kwargs):
        calls.append((url, kwargs))
        return response
    ok, message = check_instance("http://localhost:5000", "en", "pt", get=get)
    assert ok and "en" in message and "pt" in message
    assert calls[0][0] == "http://localhost:5000/languages"
    assert "json" not in calls[0][1] and calls[0][1]["allow_redirects"] is False
    assert response.closed


def test_connection_test_reports_unsupported_pair_and_bad_response():
    ok, message = check_instance("http://localhost:5000", "en", "pt", get=lambda *a, **k: Response(200, [{"code": "en", "targets": ["es"]}]))
    assert not ok and "idioma" in message.lower()
    ok, _ = check_instance("http://localhost:5000", "en", "pt", get=lambda *a, **k: Response(200, {"secret": "x"}))
    assert not ok


def test_connection_test_auto_detect_requires_available_destination():
    ok, _ = check_instance("http://localhost:5000", "", "pt", get=lambda *a, **k: Response(200, [{"code": "en", "targets": ["pt"]}]))
    assert ok
    ok, _ = check_instance("http://localhost:5000", "", "pt", get=lambda *a, **k: Response(200, [{"code": "en", "targets": ["es"]}]))
    assert not ok


def test_network_errors_produce_specific_diagnostics_without_exception_text():
    for exception, expected in [(requests.Timeout("private"), "tempo"),
                                (requests.ConnectionError("private"), "conexão"),
                                (requests.exceptions.SSLError("private"), "certificado")]:
        def post(*args, **kwargs):
            raise exception
        logs = []
        LibreTranslator("http://localhost:5000", None, "en", "pt", post=post).translate_batch(["secret"], "pt", logs.append, Event())
        assert expected in logs[0].lower()
        assert "private" not in logs[0] and "secret" not in logs[0]


def test_http_rate_limit_and_authentication_are_explained():
    for status, expected in [(429, "limite"), (403, "chave"), (401, "chave")]:
        logs = []
        response = Response(status, {"error": "secret"})
        LibreTranslator("http://localhost:5000", "secret", "en", "pt", post=lambda *a, **k: response).translate_batch(["text"], "pt", logs.append, Event())
        assert expected in logs[0].lower() and str(status) in logs[0]
        assert "secret" not in logs[0] and response.closed


def test_settings_check_runs_in_background_and_updates_the_ui(monkeypatch):
    from types import SimpleNamespace
    from tradutor_pgn import settings_window

    tasks, scheduled = [], []
    class Thread:
        def __init__(self, target, **kwargs):
            self.target = target
        def start(self):
            tasks.append(self.target)
    class Widget:
        def configure(self, **kwargs):
            self.values = kwargs
    monkeypatch.setattr(settings_window.threading, "Thread", Thread)
    monkeypatch.setattr(settings_window, "check_instance", lambda url, source, target: (True, "servidor disponível"))
    window = settings_window.SettingsWindow.__new__(settings_window.SettingsWindow)
    window.libre_url_var = SimpleNamespace(get=lambda: "http://localhost:5000")
    window.app = SimpleNamespace(source_language=SimpleNamespace(get=lambda: "en"), target_language=SimpleNamespace(get=lambda: "pt"))
    window.win = SimpleNamespace(after=lambda delay, fn: scheduled.append(fn))
    window.libre_test_button = Widget()
    window.libre_test_label = Widget()
    window.test_libre_instance()
    assert window.libre_test_button.values["state"] == "disabled"
    assert len(tasks) == 1 and len(scheduled) == 1
    tasks.pop()()
    scheduled.pop()()
    assert window.libre_test_button.values["state"] == "normal"
    assert window.libre_test_label.values["text"] == "servidor disponível"
