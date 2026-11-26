"""Trava única para o PyMuPDF.

A documentação do PyMuPDF diz que ele não suporta uso em várias threads (pode dar resultado errado ou derrubar o
Python). O RDF lê PDFs em até 4 threads de análise, na prévia e na janela ao mesmo tempo. Quem abre ou desenha um
PDF fora da thread principal usa esta trava: só um acesso ao PyMuPDF por vez. O OCR (Tesseract, a parte lenta) roda
fora dela, então as threads continuam trabalhando em paralelo.
"""

import threading

FITZ_LOCK = threading.RLock()
