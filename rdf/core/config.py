"""Configuração do RDF: pastas, limites, log e Tesseract.

Importar este módulo não cria pastas, não abre arquivos de log e não procura
o Tesseract. Essas ações acontecem só em init(), chamado na inicialização do
aplicativo.
"""

import json
import logging
import os
import shutil
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import pytesseract

APP_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "RDF"
LOG_DIR = APP_DATA_DIR / "logs"
LOG_FILE_NAME = "renomeador.log"
SESSION_DIR = APP_DATA_DIR
SESSION_FILE = SESSION_DIR / "sessao_atual.json"
SETTINGS_FILE = APP_DATA_DIR / "preferencias.json"  # tema, favoritas, janela: nada dos documentos
SPLIT_DIR = SESSION_DIR / "páginas_separadas"
CONVERT_DIR = SESSION_DIR / "arquivos_convertidos"

OUTPUT_FORMATS = ('PDF', 'PNG', 'JPEG', 'JPG', 'WEBP', 'BMP', 'TIFF')
MAX_BATCH_FILES = 300
MAX_BATCH_PAGES = 1000
MAX_FILE_SIZE_MB = 100
LARGE_FILE_WARNING_MB = 30
PARALLEL_WORKERS = 4

SESSION_MAX_AGE_DAYS = 7  # a sessão guarda nomes e matrículas: não fica no disco para sempre
TEMP_FOLDER_MAX_AGE_SECONDS = 3600  # pasta temporária de ferramenta parada há mais que isto é sobra de um app que caiu
LOGGER = logging.getLogger("rdf")

LOG_MAX_BYTES = 2 * 1024 * 1024
LOG_BACKUP_COUNT = 3


def app_base_dir():
    """Pasta do programa: a do RDF.exe quando empacotado, a raiz do projeto quando roda do código.

    Empacotado em um só arquivo, a pasta do código é uma pasta temporária apagada ao fechar; é na pasta do
    executável que o usuário coloca o tesseract_path.txt opcional.
    """
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resource_path(*parts):
    """Caminho de um arquivo embutido (ícone etc.), no código-fonte ou dentro do executável empacotado."""
    base = Path(getattr(sys, '_MEIPASS', '') or Path(__file__).resolve().parents[2])
    return base.joinpath(*parts)


def ensure_app_dirs(directories=None):
    """Cria as pastas de log, sessão e arquivos temporários do aplicativo."""
    for directory in directories or (LOG_DIR, SESSION_DIR, SPLIT_DIR, CONVERT_DIR):
        Path(directory).mkdir(parents=True, exist_ok=True)


def _referenced_generated_files(session_file, max_age_days, now):
    """Temporários que a sessão salva ainda usa. Sessão velha ou danificada vale como inexistente (e é apagada)."""
    if not session_file.exists():
        return set()
    try:
        if now - session_file.stat().st_mtime > max_age_days * 86400:
            raise ValueError('sessão expirada')
        data = json.loads(session_file.read_text(encoding='utf-8'))
        return {str(Path(p).resolve()) for p in data.get('generated_files', [])}
    except (OSError, ValueError, AttributeError, TypeError):
        session_file.unlink(missing_ok=True)
        session_file.with_suffix('.tmp').unlink(missing_ok=True)
        return set()


def _last_change(folder):
    """A data da última mudança dentro da pasta (ela mesma ou qualquer arquivo dentro)."""
    times = [folder.stat().st_mtime]
    times += [item.stat().st_mtime for item in folder.rglob('*')]
    return max(times)


def sweep_stale_data(max_age_days=SESSION_MAX_AGE_DAYS, now=None):
    """Apaga o que um fechamento anormal deixou: cópias de documentos (dados pessoais) e a sessão vencida.

    Só deve rodar no primeiro processo do RDF (único dono dessas pastas). Devolve quantos itens apagou."""
    now = time.time() if now is None else now
    removed = 0
    tools = CONVERT_DIR / 'ferramentas'
    if tools.is_dir():
        for folder in tools.iterdir():
            if now - _last_change(folder) > TEMP_FOLDER_MAX_AGE_SECONDS:  # recente: pode estar em uso por uma tela
                shutil.rmtree(folder, ignore_errors=True)
                removed += 1
    keep = _referenced_generated_files(SESSION_FILE, max_age_days, now)
    for folder in (SPLIT_DIR, CONVERT_DIR):
        if not folder.is_dir():
            continue
        for item in folder.iterdir():
            if item.is_file() and str(item.resolve()) not in keep:
                try:
                    item.unlink()
                    removed += 1
                except OSError:
                    LOGGER.warning('Não foi possível apagar o temporário %s', item)
    return removed


def setup_logging(log_dir=LOG_DIR, logger=None):
    """Liga o log rotativo ao logger "rdf" uma única vez e o devolve."""
    logger = logger or logging.getLogger("rdf")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = RotatingFileHandler(
            Path(log_dir) / LOG_FILE_NAME, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    logger.propagate = False
    return logger


def _which_outside_cwd(name):
    """O programa no PATH, ignorando a pasta atual (no Windows o shutil.which procura nela primeiro: um
    tesseract.exe plantado ao lado dos documentos seria executado)."""
    found = shutil.which(name)
    if found and Path(found).resolve().parent == Path.cwd().resolve():
        return None
    return found


def tesseract_candidates(base_dir):
    """Locais onde o Tesseract é procurado, em ordem de preferência."""
    base_dir = Path(base_dir)
    manual = base_dir / 'tesseract_path.txt'
    manual_path = manual.read_text(encoding='utf-8-sig').strip() if manual.exists() else None
    bundle_dir = getattr(sys, '_MEIPASS', str(base_dir))
    return [
        os.path.join(bundle_dir, 'Tesseract-OCR', 'tesseract.exe'),
        manual_path,
        _which_outside_cwd('tesseract'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'Tesseract-OCR', 'tesseract.exe'),
        os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Tesseract-OCR', 'tesseract.exe'),
        os.path.join(
            os.environ.get('USERPROFILE', ''), 'AppData', 'Local', 'Programs', 'Tesseract-OCR', 'tesseract.exe'
        ),
        os.path.join(os.environ.get('ProgramFiles', ''), 'Tesseract-OCR', 'tesseract.exe'),
        os.path.join(os.environ.get('ProgramFiles(x86)', ''), 'Tesseract-OCR', 'tesseract.exe'),
    ]


OMP_THREADS = '1'  # o RDF já lê vários arquivos em paralelo: cada Tesseract com uma thread não disputa a CPU


def configure_tesseract(base_dir):
    """Localiza o Tesseract instalado no usuario ou em pastas comuns, sem admin.

    Também limita cada Tesseract a uma thread do OpenMP (se o usuário não escolheu outro valor): com quatro leituras
    em paralelo, cada uma criando uma thread por núcleo, as threads disputavam a CPU e a leitura ficava dezenas de
    vezes mais lenta. É a recomendação da documentação do Tesseract para rodar vários ao mesmo tempo."""
    os.environ.setdefault('OMP_THREAD_LIMIT', OMP_THREADS)
    for exe in tesseract_candidates(base_dir):
        if exe and os.path.isfile(exe):
            pytesseract.pytesseract.tesseract_cmd = exe
            tessdata = os.path.join(os.path.dirname(exe), 'tessdata')
            if os.path.isdir(tessdata):
                os.environ['TESSDATA_PREFIX'] = tessdata
            return exe
    return None


def init(base_dir):
    """Prepara pastas, log e Tesseract. Devolve o caminho do Tesseract ou None."""
    ensure_app_dirs()
    setup_logging()
    return configure_tesseract(base_dir)
