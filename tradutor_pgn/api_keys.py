"""As chaves de API dos modelos de linguagem (ROADMAP 28.7, garantia K1).

Fora do `settings.json`, de proposito: aquele arquivo e JSON editavel a mao,
vai para backup e ja foi aberto no Bloco de Notas (ROADMAP 12.1); uma chave
em texto claro nele viraria copia em cada lugar por onde ele passa. As chaves
ficam num arquivo proprio na pasta de dados, `chaves-api.json`, cifradas com
o DPAPI do Windows (`CryptProtectData`, por `ctypes` — nada a instalar), que
so decifra na MESMA conta de usuario da MESMA maquina.

O que isso compra e o que nao compra, dito inteiro: um `.exe` portatil levado
a outra maquina nao decifra o arquivo — "decifrar falhou" e uma chave ausente,
e a tela pede a chave de novo sem apagar as outras. Fora do Windows (o CI, um
desenvolvedor no Linux) nao ha DPAPI, e o arquivo guarda a chave em base64 com
a marca `"cifra": "nenhuma"`: legivel por quem abrir o arquivo, e o arquivo diz
isso. Uma variavel de ambiente (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`DEEPSEEK_API_KEY`) VENCE o arquivo — e o jeito de quem prefere nao gravar.

**A chave nunca aparece inteira** em log, tela ou dialogo: `mask_api_key`
devolve `****` e os quatro ultimos caracteres, que e o que o console de cada
provedor mostra para identificar a chave.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
import sys
import tempfile
import threading

from . import app_paths
from .settings import _settings_lock_handle

KEYS_FILENAME = "chaves-api.json"
CIFRA_DPAPI = "dpapi"
CIFRA_NENHUMA = "nenhuma"
_KEYS_UPDATE_LOCK = threading.Lock()


def keys_path() -> str:
    return app_paths.data_path(KEYS_FILENAME)


def mask_api_key(key: str | None) -> str:
    """`****wxyz` — o que log, tela e dialogo podem mostrar (K1)."""
    if not key:
        return ""
    if len(key) <= 4:
        return "****"
    return "****" + key[-4:]


# ------------------------------------------------------------------ DPAPI


class _DataBlob(ctypes.Structure):
    # DWORD e um inteiro de 32 bits sem sinal; escrito assim para o modulo
    # importar fora do Windows (o CI headless, um desenvolvedor no Linux).
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def dpapi_available() -> bool:
    return sys.platform == "win32"


def _blob(data: bytes) -> _DataBlob:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _dpapi(func_name: str, data: bytes) -> bytes:
    """`CryptProtectData` / `CryptUnprotectData` sobre `data`, ou `OSError`."""
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    entrada = _blob(data)
    saida = _DataBlob()
    func = getattr(crypt32, func_name)
    # (pDataIn, szDataDescr/ppszDataDescr, pOptionalEntropy, pvReserved,
    #  pPromptStruct, dwFlags, pDataOut) — CRYPTPROTECT_UI_FORBIDDEN = 1: nunca
    # abrir dialogo, que numa thread do worker seria uma janela sem dona.
    ok = func(ctypes.byref(entrada), None, None, None, None, 1, ctypes.byref(saida))
    if not ok:
        raise OSError(ctypes.get_last_error() or 0, f"{func_name} falhou")
    try:
        return ctypes.string_at(saida.pbData, saida.cbData)
    finally:
        kernel32.LocalFree(saida.pbData)


def protect(texto: str) -> dict[str, str]:
    """O registro gravado para uma chave: `{"cifra": ..., "valor": base64}`."""
    dados = texto.encode("utf-8")
    if dpapi_available():
        cifrado = _dpapi("CryptProtectData", dados)
        return {"cifra": CIFRA_DPAPI, "valor": base64.b64encode(cifrado).decode("ascii")}
    return {"cifra": CIFRA_NENHUMA, "valor": base64.b64encode(dados).decode("ascii")}


def unprotect(registro: object) -> str | None:
    """A chave de um registro, ou `None` se nao da para decifrar (outra
    maquina, outra conta, arquivo editado)."""
    if not isinstance(registro, dict):
        return None
    try:
        bruto = base64.b64decode(str(registro.get("valor", "")), validate=True)
    except (ValueError, TypeError):
        return None
    cifra = registro.get("cifra")
    try:
        if cifra == CIFRA_DPAPI:
            if not dpapi_available():
                return None
            return _dpapi("CryptUnprotectData", bruto).decode("utf-8")
        if cifra == CIFRA_NENHUMA:
            return bruto.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return None


# ---------------------------------------------------------------- arquivo


def _read_file(path: str | None = None, *, strict: bool = False) -> dict[str, object]:
    caminho = path or keys_path()
    try:
        with open(caminho, encoding="utf-8") as handle:
            dados = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, RecursionError) as exc:
        if strict:
            raise OSError("Não foi possível ler o arquivo de chaves; gravação cancelada") from exc
        return {}
    if not isinstance(dados, dict):
        if strict:
            raise OSError("Arquivo de chaves inválido; gravação cancelada")
        return {}
    return dados


def _write_file(dados: dict[str, object], path: str | None = None) -> None:
    caminho = path or keys_path()
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    directory = os.path.dirname(os.path.abspath(caminho))
    fd, temporario = tempfile.mkstemp(prefix=".chaves-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dados, handle, ensure_ascii=False, indent=2)
        os.replace(temporario, caminho)
    finally:
        if os.path.exists(temporario):
            os.unlink(temporario)


def stored_key_state(provider_id: str, path: str | None = None) -> str:
    """`"ausente"`, `"ok"` ou `"ilegivel"` — o que a tela diz da chave gravada
    sem mostra-la."""
    try:
        registro = _read_file(path, strict=True).get(provider_id)
    except OSError:
        return "ilegivel"
    if registro is None:
        return "ausente"
    return "ok" if unprotect(registro) is not None else "ilegivel"


def load_api_key(provider_id: str, env_var: str | None = None, path: str | None = None) -> str | None:
    """A chave em uso: a variavel de ambiente vence; depois o arquivo."""
    if env_var:
        valor = os.environ.get(env_var, "").strip()
        if valor:
            return valor
    registro = _read_file(path).get(provider_id)
    if registro is None:
        return None
    chave = unprotect(registro)
    return chave or None


def save_api_key(provider_id: str, key: str | None, path: str | None = None) -> None:
    """Grava (ou, vazia, apaga) a chave de UM provedor sem tocar nas outras."""
    caminho = path or keys_path()
    with _KEYS_UPDATE_LOCK, _settings_lock_handle(caminho):
        dados = _read_file(caminho, strict=True)
        chave = (key or "").strip()
        if chave:
            dados[provider_id] = protect(chave)
        else:
            dados.pop(provider_id, None)
        _write_file(dados, caminho)
