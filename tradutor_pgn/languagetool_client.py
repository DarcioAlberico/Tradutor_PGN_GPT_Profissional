"""Private loopback-only LanguageTool HTTP boundary and issue normalization."""

from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.connection import HTTPConnection
from urllib3.connectionpool import HTTPConnectionPool

from .writing_protection import ProtectedText
from .writing_types import AssistantStatus, IssueCategory, WritingIssue, WritingRequest

if TYPE_CHECKING:
    from .languagetool_process import LanguageToolProcess


EXPECTED_VERSION = "6.6"


class LanguageToolUnavailable(RuntimeError):
    """Safe diagnostic: never include request text, response bodies or URLs."""


def _owned_transport(verify_owner: Callable[[], bool]) -> HTTPAdapter:
    """Verify after TCP connect, before HTTP headers/body can leave the app.

    The pre-request PID check alone has a race if the child dies and a foreign
    service takes its port before requests connects. An established connection
    cannot be reassigned when a listener subsequently dies. Reconnects pass
    this guard too. urllib3 is the transport already provided by requests.
    """
    class OwnedConnection(HTTPConnection):
        def connect(self) -> None:
            super().connect()
            if not verify_owner():
                self.close()
                raise LanguageToolUnavailable("Concordância indisponível: processo local divergente.")

    class OwnedPool(HTTPConnectionPool):
        ConnectionCls = OwnedConnection

    adapter = HTTPAdapter(max_retries=0)
    # Copy the mapping: never change urllib3's process-wide pool classes.
    adapter.poolmanager.pool_classes_by_scheme = {
        **adapter.poolmanager.pool_classes_by_scheme, "http": OwnedPool,
    }
    return adapter


def _local_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise ValueError("LanguageTool requires a canonical IPv4 loopback URL") from None
    if (parts.scheme != "http" or parts.hostname != "127.0.0.1"
            or port is None or not 1 <= port <= 65535
            or parts.username is not None or parts.password is not None
            or parts.path not in {"", "/"} or parts.query or parts.fragment):
        raise ValueError("LanguageTool requires a canonical IPv4 loopback URL")
    return f"http://127.0.0.1:{port}"


def _category(rule: dict[str, Any]) -> IssueCategory:
    rule_id = rule["id"]
    category_id = rule["category"]["id"]
    issue_type = rule.get("issueType", "grammar")
    if issue_type == "misspelling" or category_id == "TYPOS":
        return "SPELLING"
    if issue_type == "duplication" or rule_id in {"PT_WORD_REPEAT_RULE", "WORD_REPEAT_RULE"}:
        return "REPEATED_WORD"
    if category_id == "PUNCTUATION":
        return "PUNCTUATION"
    if rule_id.startswith(("PT_VERBAL_AGREEMENT", "PT_AGREEMENT_VERB")) or rule_id in {
        "LINKING_VERB_PREDICATE_AGREEMENT", "GENERAL_VERB_AGREEMENT_ERRORS",
        "REFLEXIVE_VERB_SE_AGREEMENT", "CONCORDANCIA_SER_PLURAL", "CONCORDANCIA_QUALQUER",
    }:
        return "VERBAL_AGREEMENT"
    if rule_id.startswith(("PT_AGREEMENT", "PT_NOMINAL_AGREEMENT")) or rule_id in {
        "GENERAL_GENDER_AGREEMENT_ERRORS", "GENERAL_NUMBER_AGREEMENT_ERRORS",
        "GENERAL_GENDER_NUMBER_AGREEMENT_ERRORS", "SER_ADJECTIVE_AGREEMENT", "TODOS_NUMBER_AGREEMENT",
    }:
        return "NOMINAL_AGREEMENT"
    return "GRAMMAR"


def _issues(payload: Any, text: str, disabled: frozenset[str], version: int) -> tuple[WritingIssue, ...]:
    """Treat a malformed response as unavailable, never a partial success."""
    if (not isinstance(payload, dict) or not isinstance(payload.get("software"), dict)
            or payload["software"].get("name") != "LanguageTool"
            or payload["software"].get("version") != EXPECTED_VERSION
            or not isinstance(payload.get("language"), dict)
            or payload["language"].get("code") != "pt-BR"
            or not isinstance(payload.get("matches"), list)):
        raise ValueError("invalid response envelope")
    # Java offsets count UTF-16 units. Only complete scalar boundaries can be
    # selected: neither half of an emoji is a valid Python span boundary.
    boundaries = {0: 0}
    units = 0
    for index, char in enumerate(text, 1):
        units += 2 if ord(char) > 0xFFFF else 1
        boundaries[units] = index
    issues = []
    for match in payload["matches"]:
        if not isinstance(match, dict):
            raise ValueError("invalid match")
        offset, length = match.get("offset"), match.get("length")
        if type(offset) is not int or type(length) is not int or length <= 0:
            raise ValueError("invalid span")
        start, end = boundaries[offset], boundaries[offset + length]
        rule = match["rule"]
        if (not isinstance(rule, dict) or not isinstance(rule.get("id"), str) or not rule["id"]
                or not isinstance(rule.get("category"), dict)
                or not isinstance(rule["category"].get("id"), str)
                or not isinstance(match.get("message"), str)
                or not isinstance(match.get("replacements"), list)):
            raise ValueError("invalid rule")
        suggestions = []
        for replacement in match["replacements"]:
            if not isinstance(replacement, dict) or not isinstance(replacement.get("value"), str):
                raise ValueError("invalid replacement")
            value = replacement["value"]
            if value not in suggestions:
                suggestions.append(value)
        if rule["id"] in disabled:
            continue
        explanation = match.get("shortMessage") or rule.get("description") or match["message"]
        if not isinstance(explanation, str):
            raise ValueError("invalid explanation")
        issues.append(WritingIssue(
            issue_id="", rule_id=rule["id"], category=_category(rule),
            start=start, end=end, original=text[start:end], message=match["message"],
            explanation=explanation, suggestions=tuple(suggestions[:5]), severity="warning",
            provider="languagetool", text_version=version,
        ))
    return tuple(issues)


class LanguageToolLocalAdapter:
    """Use a managed sidecar by default; an explicit URL is an HTTP test seam.

    One injected session belongs to this adapter. Environment proxies/netrc and
    existing session proxies are disabled; redirects never carry text elsewhere.
    The process manager exclusively owns retry and session fallback policy.
    """

    def __init__(
        self, base_url: str | None = None, *, process: "LanguageToolProcess | None" = None,
        session: requests.Session | None = None, timeout: float = 2.0,
    ) -> None:
        if base_url is not None and process is not None:
            raise ValueError("choose a process or an explicit loopback URL")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._url = _local_url(base_url) if base_url is not None else None
        if self._url is None and process is None:
            from .languagetool_process import LanguageToolProcess
            process = LanguageToolProcess()
        self._process = process
        self._session = session if session is not None else requests.Session()
        self._session.trust_env = False
        self._session.proxies.clear()
        if self._process is not None:
            self._session.mount("http://", _owned_transport(self._process.owns_listener))
        self._timeout = timeout

    def _check_url(self, url: str, text: str, disabled: frozenset[str], version: int) -> tuple[WritingIssue, ...]:
        data = {"text": text, "language": "pt-BR"}
        if disabled:
            data["disabledRules"] = ",".join(sorted(disabled))
        try:
            response = self._session.post(
                _local_url(url) + "/v2/check", data=data, timeout=self._timeout,
                allow_redirects=False, proxies={"http": "", "https": ""},
            )
            with response:
                if response.status_code != 200:
                    raise LanguageToolUnavailable("Concordância indisponível: falha HTTP local.")
                return _issues(response.json(), text, disabled, version)
        except LanguageToolUnavailable:
            raise
        except requests.RequestException:
            raise LanguageToolUnavailable("Concordância indisponível: falha na conexão local.") from None
        except (ValueError, KeyError, TypeError, IndexError):
            raise LanguageToolUnavailable("Concordância indisponível: resposta local inválida.") from None

    def check(
        self, text: str, disabled_rule_ids: frozenset[str], *, text_version: int = 0,
    ) -> tuple[WritingIssue, ...]:
        disabled = frozenset(disabled_rule_ids)
        if self._process is not None:
            return self._process.execute(lambda url: self._check_url(url, text, disabled, text_version))
        assert self._url is not None
        return self._check_url(self._url, text, disabled, text_version)

    def analyze(self, request: WritingRequest, protected: ProtectedText) -> tuple[WritingIssue, ...]:
        return self.check(protected.projected_text, request.disabled_rule_ids, text_version=request.text_version)

    def status(self) -> AssistantStatus:
        return self._process.status() if self._process is not None else AssistantStatus("ready", "full")

    def shutdown(self) -> None:
        if self._process is not None:
            self._process.shutdown()
        self._session.close()
