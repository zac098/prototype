"""Abre o RDF: python -m rdf

A interface é em Qt (PySide6).
"""

import sys


def main(argv=None):
    argv = sys.argv if argv is None else argv
    if '--autoteste' in argv:  # confere o app empacotado sem abrir a janela (rdf/selftest.py)
        from rdf import selftest

        return selftest.main(argv)
    # O Qt só é carregado aqui dentro: importar este módulo não abre janela nem cria pastas.
    from rdf.qt.__main__ import main as run_qt

    return run_qt()


if __name__ == '__main__':
    sys.exit(main())
