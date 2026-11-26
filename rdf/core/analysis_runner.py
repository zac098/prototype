"""Análise do lote em paralelo, sem interface.

Lê vários arquivos ao mesmo tempo (um pool de threads), avisa cada resultado por um callback e obedece ao
cancelamento: depois de cancelar, nenhum arquivo novo é iniciado e os que já estavam sendo lidos terminam.
"""

import logging
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from rdf.core.config import PARALLEL_WORKERS
from rdf.core.ocr import analyze_document

LOGGER = logging.getLogger('rdf')


def run_analysis(files, pages, build_row, emit, cancel_event, discard_event=None, analyze=None, workers=None):
    """Analisa os arquivos e chama emit(tipo, dado) a cada novidade; devolve quantos terminaram.

    tipos: 'result' (linha pronta), 'error' ((caminho, exceção)), 'progress' ((feitos, total, caminho)),
    'fatal' (exceção) e, sempre por último, 'finished'. build_row(caminho, resultado) monta a linha.
    Com discard_event ligado, resultados e erros não são enviados (a tela vai descartá-los)."""
    analyze = analyze or analyze_document
    discard_event = discard_event or threading.Event()
    total = len(files)
    pool_size = min(workers or PARALLEL_WORKERS, max(1, total))
    iterator = iter(files)
    running = {}
    completed = 0

    def submit_next(pool):
        if cancel_event.is_set():
            return False
        try:
            path = next(iterator)
        except StopIteration:
            return False
        running[pool.submit(analyze, path, pages.get(path, 0))] = path
        return True

    try:
        with ThreadPoolExecutor(max_workers=pool_size, thread_name_prefix='ocr') as pool:
            for _ in range(pool_size):
                submit_next(pool)
            while running:
                done, _pending = wait(tuple(running), return_when=FIRST_COMPLETED)
                for future in done:
                    path = running.pop(future)
                    completed += 1
                    try:
                        row = build_row(path, future.result())
                        if not discard_event.is_set():
                            emit('result', row)
                    except Exception as exc:
                        LOGGER.exception('Falha ao analisar %s', path)
                        if not discard_event.is_set():
                            emit('error', (path, exc))
                    emit('progress', (completed, total, path))
                    submit_next(pool)
    except Exception as exc:
        LOGGER.exception('Falha geral na análise')
        emit('fatal', exc)
    finally:
        emit('finished', None)
    return completed
