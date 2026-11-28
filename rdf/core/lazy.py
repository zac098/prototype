"""Módulos carregados só no primeiro uso.

O RDF abre bem mais rápido quando a tela inicial não carrega o que só as ferramentas usam (PyMuPDF, Pillow, OpenCV,
Tesseract). Quem precisa de um módulo pesado em poucas funções guarda um LazyModule no lugar do import: o módulo de
verdade só é importado quando alguém usa um atributo dele, e daí em diante o Python devolve o mesmo módulo de sempre.
"""

import importlib


class LazyModule:
    """Representa o módulo "name" sem importá-lo. lazy.merge_pdfs(...) importa o módulo e chama a função dele."""

    def __init__(self, name):
        self._name = name

    def __getattr__(self, attribute):  # só é chamado para o que não é atributo do próprio LazyModule
        return getattr(importlib.import_module(self._name), attribute)

    def __repr__(self):
        return f'<LazyModule {self._name}>'
