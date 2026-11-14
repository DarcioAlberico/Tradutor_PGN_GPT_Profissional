import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name != "nt", reason="PowerShell e caminhos Windows")
def test_cycle_refuses_existing_installation_even_without_data(tmp_path):
    appdata = tmp_path / "roaming"
    local = tmp_path / "local"
    appdata.mkdir()
    existing = local / "Programs" / "PGN Tradutor Pro"
    existing.mkdir(parents=True)
    marker = existing / "preserve-me.txt"
    marker.write_text("dados reais simulados", encoding="utf-8")
    env = dict(os.environ, APPDATA=str(appdata), LOCALAPPDATA=str(local))
    env.pop("PGN_TRADUTOR_DATA", None)
    script = Path(__file__).resolve().parents[1] / "instalador" / "verificar-ciclo.ps1"
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        env=env, capture_output=True, timeout=20,
    )
    assert result.returncode != 0
    assert b"instalacao existente" in result.stderr.lower()
    assert marker.read_text(encoding="utf-8") == "dados reais simulados"


def test_cycle_does_not_kill_unrelated_processes_or_delete_data_directories():
    script = Path(__file__).resolve().parents[1] / "instalador" / "verificar-ciclo.ps1"
    source = script.read_text(encoding="utf-8")
    assert "Get-Process -Name 'PGN_Tradutor_Pro'" not in source
    assert "Remove-Item $dados -Recurse" not in source
    assert "Remove-Item $programa -Recurse" not in source


@pytest.mark.skipif(os.name != "nt", reason="PowerShell e caminhos Windows")
def test_cycle_refuses_data_directory_override_without_touching_it(tmp_path):
    appdata, local, data = tmp_path / "roaming", tmp_path / "local", tmp_path / "user-data"
    for path in (appdata, local, data):
        path.mkdir()
    marker = data / "preservar.txt"
    marker.write_text("conteudo", encoding="utf-8")
    env = dict(os.environ, APPDATA=str(appdata), LOCALAPPDATA=str(local), PGN_TRADUTOR_DATA=str(data))
    script = Path(__file__).resolve().parents[1] / "instalador" / "verificar-ciclo.ps1"
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        env=env, capture_output=True, timeout=20,
    )
    assert result.returncode != 0
    assert b"pgn_tradutor_data" in result.stderr.lower()
    assert marker.read_text(encoding="utf-8") == "conteudo"


@pytest.mark.skipif(os.name != "nt", reason="registro Windows")
def test_cycle_refuses_registered_installation_even_if_default_folder_missing(tmp_path):
    import winreg

    key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{7C1D9F2E-5A64-4B7C-9E3D-1F2A6B8C4D50}_is1"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key):
            pass
    except FileNotFoundError:
        pytest.skip("instalação de usuário não registrada nesta máquina")
    appdata, local = tmp_path / "roaming", tmp_path / "local"
    appdata.mkdir()
    local.mkdir()
    script = Path(__file__).resolve().parents[1] / "instalador" / "verificar-ciclo.ps1"
    env = dict(os.environ, APPDATA=str(appdata), LOCALAPPDATA=str(local))
    env.pop("PGN_TRADUTOR_DATA", None)
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        env=env,
        capture_output=True, timeout=20,
    )
    assert result.returncode != 0
    assert b"instalacao existente registrada" in result.stderr.lower()
    assert not (local / "Programs" / "PGN Tradutor Pro").exists()
