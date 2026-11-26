"""Abre o RDF: python -m rdf

A interface é em Qt (PySide6).
"""

import sys


def main():
    # O Qt só é carregado aqui dentro: importar este módulo não abre janela nem cria pastas.
    from rdf.qt.__main__ import main as run_qt

    return run_qt()


if __name__ == '__main__':
    sys.exit(main())
