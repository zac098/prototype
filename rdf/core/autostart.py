"""Início automático do RDF com o Windows (em segundo plano, na bandeja).

Usa a chave Run do próprio usuário (HKCU): não pede administrador e some junto com a conta. O valor "RDF" guarda o
comando que o Windows executa ao entrar. Quem liga e desliga é sempre o usuário (instalador ou menu da bandeja).

Todas as funções aceitam o caminho da chave para os testes usarem uma chave própria, sem tocar na real.
"""

import sys
from pathlib import Path

try:
    import winreg
except ImportError:  # fora do Windows não existe início automático por aqui
    winreg = None

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
VALUE_NAME = 'RDF'
BACKGROUND_FLAG = '--segundo-plano'  # inicia escondido na bandeja, sem abrir a janela


def supported():
    return winreg is not None


def command():
    """O comando que o Windows deve executar ao entrar: o RDF.exe empacotado ou, no código-fonte, o pythonw."""
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}" {BACKGROUND_FLAG}'
    python = Path(sys.executable)
    windowless = python.with_name('pythonw.exe')  # sem janela de console
    script = Path(__file__).resolve().parents[2] / 'rdf_app.py'
    return f'"{windowless if windowless.is_file() else python}" "{script}" {BACKGROUND_FLAG}'


def is_enabled(key=None):
    """True se o RDF está na lista de início automático do usuário."""
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key or RUN_KEY, 0, winreg.KEY_READ) as handle:
            value, _kind = winreg.QueryValueEx(handle, VALUE_NAME)
    except OSError:
        return False
    return bool(str(value).strip())


def set_enabled(enabled, key=None):
    """Liga (grava o comando atual) ou desliga (apaga o valor) o início automático. Devolve o novo estado."""
    if winreg is None:
        return False
    path = key or RUN_KEY
    if enabled:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as handle:
            winreg.SetValueEx(handle, VALUE_NAME, 0, winreg.REG_SZ, command())
        return True
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as handle:
            winreg.DeleteValue(handle, VALUE_NAME)
    except OSError:
        pass  # já não estava lá
    return False
