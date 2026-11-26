"""Atalho para abrir o RDF com duplo clique ou pelo PyInstaller (equivale a python -m rdf)."""

import sys

from rdf.__main__ import main


def explain_missing_module(error):
    """Com duplo clique, o Python do sistema pode não ter as bibliotecas: avisa em vez de fechar calado."""
    text = (
        f'Faltou uma biblioteca do RDF ({error.name}).\n\n'
        'Use o arquivo "Iniciar RDF.bat" (ele prepara tudo na primeira vez)\n'
        'ou rode: pip install -r requirements.txt'
    )
    print(text)
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, text, 'RDF', 0x10)
    except Exception:
        input('\nPressione Enter para fechar...')


def run():
    try:
        return main()
    except ModuleNotFoundError as error:
        if getattr(sys, 'frozen', False) or not error.name or error.name.split('.')[0] == 'rdf':
            raise
        explain_missing_module(error)
        return 1


if __name__ == '__main__':
    sys.exit(run())
