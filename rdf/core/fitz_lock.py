"""Trava única para o PyMuPDF.

A documentação do PyMuPDF diz que ele não suporta uso em várias threads (pode dar resultado errado ou derrubar o
Python). O RDF lê PDFs em até 4 threads de análise, na prévia e na janela ao mesmo tempo. Quem abre ou desenha um
PDF fora da thread principal usa esta trava: só um acesso ao PyMuPDF por vez. O OCR (Tesseract, a parte lenta) roda
fora dela, então as threads continuam trabalhando em paralelo.
"""

import contextlib
import threading

FITZ_LOCK = threading.RLock()


@contextlib.contextmanager
def released():
    """Solta a trava durante um trabalho que não usa o PyMuPDF (o Tesseract de uma página, por exemplo) e a pega de
    volta no fim, mesmo que quem chamou a tenha pegado mais de uma vez. Sem a trava, não faz nada."""
    if not FITZ_LOCK._is_owned():
        yield
        return
    state = FITZ_LOCK._release_save()
    try:
        yield
    finally:
        FITZ_LOCK._acquire_restore(state)
