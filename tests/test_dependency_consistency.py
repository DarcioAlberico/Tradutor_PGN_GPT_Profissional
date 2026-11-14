import subprocess
import sys
from pathlib import Path

import pytest
from packaging.requirements import Requirement


ROOT = Path(__file__).resolve().parents[1]


def dependencies(lines):
    requirements = (Requirement(line) for line in lines if line.strip() and not line.lstrip().startswith('#'))
    return {item.name.lower().replace('_', '-'): item for item in requirements}


def test_pip_and_project_have_same_direct_dependencies():
    tomllib = pytest.importorskip('tomllib')
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    declared = dependencies(project['project']['dependencies'])
    pip = dependencies((ROOT / 'requirements.txt').read_text(encoding='utf-8').splitlines())
    assert declared == pip


def test_declared_versions_exclude_known_incompatible_pair():
    tomllib = pytest.importorskip('tomllib')
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    deps = dependencies(project['project']['dependencies'])
    assert '2.32.5' not in deps['requests'].specifier
    assert '2.33.1' in deps['requests'].specifier
    assert '7.4.3' in deps['chardet'].specifier
    assert '8.0.0' not in deps['chardet'].specifier


def test_import_requests_has_no_dependency_warning():
    command = (
        'import warnings; '
        'warnings.simplefilter("error"); '
        'import requests, chardet, customtkinter, deep_translator, spylls'
    )
    result = subprocess.run([sys.executable, '-c', command], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
