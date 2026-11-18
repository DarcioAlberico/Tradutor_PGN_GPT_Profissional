"""Cliente HTTP de uma instância LibreTranslate escolhida pelo usuário."""
from urllib.parse import urlsplit

import requests

DEFAULT_URL = "http://127.0.0.1:5000"


def validate_url(url):
    if not isinstance(url, str):
        raise ValueError("Informe uma URL HTTP(S) válida.")
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Informe uma URL HTTP(S) válida, sem credenciais, consulta ou fragmento.")
    return url.strip().rstrip("/")


def _network_error(exc):
    if isinstance(exc, requests.exceptions.SSLError):
        return "Falha no certificado TLS do LibreTranslate. Confira o certificado do servidor."
    if isinstance(exc, requests.Timeout):
        return "O LibreTranslate excedeu o tempo de resposta. Confira se o servidor está ocupado."
    if isinstance(exc, requests.ConnectionError):
        return "Não foi possível estabelecer conexão com o LibreTranslate. Confira o endereço e se o servidor está em execução."
    return "Não foi possível comunicar com o LibreTranslate. Confira a rede e o servidor."


def _http_error(status):
    if status in (401, 403):
        return f"LibreTranslate respondeu HTTP {status}: acesso recusado; confira a chave e as permissões."
    if status == 429:
        return "LibreTranslate respondeu HTTP 429: limite de requisições atingido; aguarde e confira a cota do servidor."
    return f"LibreTranslate respondeu HTTP {status}; confira a instância, os idiomas e a chave."


def check_instance(url, source, target, *, get=None):
    """Consulta apenas os idiomas da instância; não envia textos ou chaves."""
    try:
        endpoint = validate_url(url) + "/languages"
    except (ValueError, TypeError):
        return False, "Endereço LibreTranslate inválido."
    try:
        response = (get or requests.get)(endpoint, timeout=(5, 10), allow_redirects=False)
        try:
            if response.status_code != 200:
                return False, _http_error(response.status_code)
            languages = response.json()
        finally:
            response.close()
    except requests.RequestException as exc:
        return False, _network_error(exc)
    except (ValueError, AttributeError):
        return False, "O servidor devolveu uma lista de idiomas inválida."
    if not isinstance(languages, list) or not languages or any(
        not isinstance(item, dict) or not isinstance(item.get("code"), str)
        or not isinstance(item.get("targets"), list)
        or any(not isinstance(code, str) for code in item["targets"])
        for item in languages
    ):
        return False, "O servidor devolveu uma lista de idiomas inválida."
    available = [item for item in languages if not source or source == "auto" or item["code"] == source]
    if not target or not any(target in item["targets"] for item in available):
        return False, "O servidor não oferece o par de idiomas selecionado. Instale os modelos correspondentes."
    return True, f"Conexão disponível; idioma de origem {source or 'automático'} e destino {target} disponíveis."


class LibreTranslator:
    run_label = "libretranslate"

    def __init__(self, url, api_key, source, target, *, post=None):
        self.url = validate_url(url)
        self.api_key = api_key
        self.source = source or "auto"
        self.target = target
        self.post = post or requests.post

    def describe(self):
        return "Motor LibreTranslate configurado."

    def translate_batch(self, texts, target, log_message, cancel_flag, contexts=None):
        if cancel_flag is not None and cancel_flag.is_set():
            return None
        payload = {"q": texts, "source": self.source, "target": self.target, "format": "text"}
        if self.api_key:
            payload["api_key"] = self.api_key
        try:
            response = self.post(self.url + "/translate", json=payload, timeout=(10, 120), allow_redirects=False)
            try:
                if response.status_code != 200:
                    log_message("[ERRO] " + _http_error(response.status_code))
                    return None
                result = response.json().get("translatedText")
            finally:
                response.close()
        except requests.RequestException as exc:
            log_message("[ERRO] " + _network_error(exc))
            return None
        except (ValueError, AttributeError):
            log_message("[ERRO] Não foi possível obter resposta válida do LibreTranslate. Confira se a instância está em execução.")
            return None
        if cancel_flag is not None and cancel_flag.is_set():
            return None
        if not isinstance(result, list) or len(result) != len(texts) or any(not isinstance(item, str) or not item.strip() for item in result):
            log_message("[ERRO] LibreTranslate devolveu um lote incompleto ou inválido.")
            return None
        return result
