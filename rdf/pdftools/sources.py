"""Entrada de qualquer arquivo como PDF: as ferramentas e a impressão trabalham sempre com PDF, e este módulo
converte o resto (imagens, texto, HTML, SVG, quadrinhos CBZ e documentos do Office) antes.

- Imagens (JPG, PNG, BMP, GIF, TIFF, WEBP): uma página por quadro; a página acompanha o tamanho da imagem e nunca
  passa de uma folha A4 (a foto de um celular não vira uma página gigante).
- Texto (TXT, MD, CSV, LOG, JSON, XML) e HTML: páginas A4 com margem; o texto mantém acentos e quebra de linha.
- SVG e CBZ: o próprio PyMuPDF converte.
- Word, Excel e PowerPoint (DOC, DOCX, RTF, ODT, XLS, XLSX, PPT, PPTX): usa o Microsoft Office instalado no
  computador, em segundo plano e com macros desligadas. Sem o Office, o app diz isso com clareza.
"""

import codecs
import contextlib
import hashlib
import html
import io
import logging
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import fitz
from PIL import Image, ImageOps

from rdf.core.fitz_lock import FITZ_LOCK
from rdf.pdftools import ops
from rdf.pdftools.formats import (
    ALL_EXTENSIONS,
    EXCEL_EXTENSIONS,
    HTML_EXTENSIONS,
    IMAGE_EXTENSIONS,
    MUPDF_EXTENSIONS,
    OFFICE_EXTENSIONS,
    POWERPOINT_EXTENSIONS,
    TEXT_EXTENSIONS,
    WORD_EXTENSIONS,
    extension,
    is_supported,
)

__all__ = [  # os formatos continuam acessíveis por aqui (sources.ALL_EXTENSIONS etc.)
    'ALL_EXTENSIONS',
    'EXCEL_EXTENSIONS',
    'HTML_EXTENSIONS',
    'IMAGE_EXTENSIONS',
    'MUPDF_EXTENSIONS',
    'OFFICE_EXTENSIONS',
    'POWERPOINT_EXTENSIONS',
    'TEXT_EXTENSIONS',
    'WORD_EXTENSIONS',
    'extension',
    'is_supported',
]

LOGGER = logging.getLogger('rdf')

A4 = (595.0, 842.0)  # pontos (1/72 de polegada)
DEFAULT_IMAGE_DPI = 150.0
TEXT_MARGIN = 42  # pontos
OFFICE_TIMEOUT_SECONDS = 180

OFFICE_APPS = {  # extensão -> (programa, nome do processo)
    **dict.fromkeys(WORD_EXTENSIONS, ('Word', 'WINWORD')),
    **dict.fromkeys(EXCEL_EXTENSIONS, ('Excel', 'EXCEL')),
    **dict.fromkeys(POWERPOINT_EXTENSIONS, ('PowerPoint', 'POWERPNT')),
}

# Os caminhos vão por variável de ambiente (RDF_ORIGEM e RDF_DESTINO), nunca dentro do texto do script: assim um nome
# de arquivo com aspas ou símbolos não vira comando. AutomationSecurity=3 desliga as macros do documento aberto.
# O Office às vezes responde "ocupado" logo depois de abrir (0x80010001, 0x8001010A): a função Tentar repete a chamada.
# Word e Excel recebem uma senha qualquer ao abrir: um documento com senha falha na hora (e cai na mensagem de senha)
# em vez de esperar, escondido, alguém digitar a senha até o tempo acabar.
# Ao final, o que o RDF abriu é fechado, inclusive se a conversão falhou; o Word, Excel ou PowerPoint que o usuário
# já tinha aberto nunca é fechado.
_POWERSHELL_PRELUDE = (
    "$ErrorActionPreference = 'Stop'; "
    "$origem = $env:RDF_ORIGEM; $destino = $env:RDF_DESTINO; "
    "$antes = @(Get-Process -Name '{process}' -ErrorAction SilentlyContinue | ForEach-Object { $_.Id }); "
    "function Tentar([scriptblock]$acao) { "
    "for ($i = 1; $i -le 8; $i++) { "
    "try { return (& $acao) } catch { "
    "if ($i -eq 8 -or $_.Exception.Message -notmatch '0x8001000|0x8001010A|0x800AC472') { throw }; "
    "Start-Sleep -Milliseconds 700 } } }; "
    "$app = $null; $meus = @(); "
)
# Logo depois de criar o aplicativo: os processos que não existiam antes são os do RDF ($meus). Só eles são fechados,
# então um Word que o usuário abra no meio da conversão nunca é tocado. Os números também vão para um arquivo
# (RDF_PIDS): se o Office travar e o tempo acabar, o RDF fecha esses processos (o PowerShell já terá sido encerrado).
_POWERSHELL_OWN = (
    "$meus = @(Get-Process -Name '{process}' -ErrorAction SilentlyContinue | "
    "Where-Object { $antes -notcontains $_.Id } | ForEach-Object { $_.Id }); "
    "if ($env:RDF_PIDS) { Set-Content -Path $env:RDF_PIDS -Value ($meus -join ',') -ErrorAction SilentlyContinue }; "
)
# No fim, o aplicativo só é fechado se não tiver outro documento aberto: o PowerPoint usa um só processo, e uma
# apresentação que o usuário abra no meio da conversão entra no processo do RDF. Ela nunca é fechada à força.
_POWERSHELL_CLEANUP = (
    "finally { "
    "$outros = 0; try { if ($app) { $outros = @COUNT@ } } catch {}; "
    "if ($app -and $meus.Count -gt 0 -and $outros -eq 0) { try { $app.Quit() } catch {} }; "
    "if ($meus.Count -gt 0 -and $outros -eq 0) { Get-Process -Name '{process}' -ErrorAction SilentlyContinue | "
    "Where-Object { $meus -contains $_.Id } | Stop-Process -Force -ErrorAction SilentlyContinue } }"
)
_DOCUMENT_COUNTS = {
    'Word': '$app.Documents.Count',
    'Excel': '$app.Workbooks.Count',
    'PowerPoint': '$app.Presentations.Count',
}
_POWERSHELL_SCRIPTS = {
    'Word': (
        "try { $app = New-Object -ComObject Word.Application; @OWN@"
        "$app.Visible = $false; $app.DisplayAlerts = 0; $app.AutomationSecurity = 3; "
        "$doc = Tentar { $app.Documents.Open($origem, $false, $true, $false, 'rdf-sem-senha') }; "
        "try { Tentar { $doc.ExportAsFixedFormat($destino, 17) } } finally { try { $doc.Close($false) } catch {} } } "
    ),
    'Excel': (
        "try { $app = New-Object -ComObject Excel.Application; @OWN@"
        "$app.Visible = $false; $app.DisplayAlerts = $false; $app.AutomationSecurity = 3; "
        "$livro = Tentar { $app.Workbooks.Open($origem, 0, $true, [Type]::Missing, 'rdf-sem-senha') }; "
        "try { Tentar { $livro.ExportAsFixedFormat(0, $destino) } } finally { try { $livro.Close($false) } catch {} } } "
    ),
    'PowerPoint': (
        "try { $app = New-Object -ComObject PowerPoint.Application; @OWN@"
        "$app.AutomationSecurity = 3; "
        "$apresentacao = Tentar { $app.Presentations.Open($origem, -1, 0, 0) }; "
        "try { Tentar { $apresentacao.SaveAs($destino, 32) } } finally { try { $apresentacao.Close() } catch {} } } "
    ),
}


TOOL_MAX_MB = 500  # PDFs e imagens: grandes o bastante para comprimir um PDF pesado, sem esgotar a memória
TEXT_MAX_MB = 20  # texto e HTML são lidos inteiros e viram muitas páginas
MAX_IMAGE_PIXELS = 100_000_000


def size_error(path):
    """Mensagem pronta se o arquivo é grande demais para as ferramentas; None se está dentro do limite."""
    try:
        megabytes = Path(path).stat().st_size / (1024 * 1024)
    except OSError:
        return None
    limit = TEXT_MAX_MB if extension(path) in TEXT_EXTENSIONS | HTML_EXTENSIONS else TOOL_MAX_MB
    if megabytes > limit:
        return f'"{Path(path).name}" tem {megabytes:.0f} MB; o limite para este tipo de arquivo é {limit} MB.'
    return None


def pixels_error(width, height, name):
    if width * height > MAX_IMAGE_PIXELS:
        return f'"{name}" tem {width * height / 1_000_000:.0f} milhões de pixels; o limite é {MAX_IMAGE_PIXELS // 1_000_000}.'
    return None


def is_slow(path):
    """True para o que depende do Office: leva segundos por arquivo, então a conversão fica para a hora de executar."""
    return extension(path) in OFFICE_EXTENSIONS


def kind_label(path):
    """Nome curto do tipo de arquivo, para mostrar na lista."""
    ext = extension(path)
    if ext == '.pdf':
        return 'PDF'
    if ext in IMAGE_EXTENSIONS:
        return 'Imagem'
    if ext in TEXT_EXTENSIONS:
        return 'Texto'
    if ext in HTML_EXTENSIONS:
        return 'HTML'
    if ext in OFFICE_APPS:
        return OFFICE_APPS[ext][0]
    return ext.lstrip('.').upper()


def file_dialog_filters():
    """Filtros da janela de escolher arquivos, do mais abrangente ao mais específico."""

    def pattern(extensions):
        return ' '.join(f'*{ext}' for ext in sorted(extensions))

    return ';;'.join(
        [
            f'Todos os suportados ({pattern(ALL_EXTENSIONS)})',
            'Arquivos PDF (*.pdf)',
            f'Imagens ({pattern(IMAGE_EXTENSIONS)})',
            f'Documentos do Office ({pattern(OFFICE_EXTENSIONS)})',
            f'Texto e HTML ({pattern(TEXT_EXTENSIONS | HTML_EXTENSIONS)})',
            'Todos os arquivos (*.*)',
        ]
    )


def office_error(path, detail=''):
    app = OFFICE_APPS[extension(path)][0]
    return ops.PdfToolError(
        f'Para abrir "{Path(path).name}" é preciso ter o Microsoft {app} instalado neste computador.'
        + (f' ({detail})' if detail else '')
    )


def office_available(path):
    """True se o programa do Office que abre este arquivo está instalado (procura o registro do Windows)."""
    if sys.platform != 'win32':
        return False
    app = OFFICE_APPS.get(extension(path), ('', ''))[0]
    if not app:
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, f'{app}.Application'):
            return True
    except OSError:
        return False


# ---- conversão -----------------------------------------------------------------------------


def convert_to_pdf(source, dest, progress=ops._noop):
    """Grava o arquivo como PDF em dest (sem nunca deixar um PDF pela metade). Devolve dest como Path."""
    source, dest = Path(source), Path(dest)
    ext = extension(source)
    if ext == '.pdf':
        raise ops.PdfToolError('O arquivo já é um PDF.')
    if ext not in ALL_EXTENSIONS:
        raise ops.PdfToolError(f'Formato não suportado: {ext or "sem extensão"}.')
    if not source.is_file():
        raise ops.PdfToolError(f'Não foi possível abrir "{source.name}": o arquivo não existe mais.')
    too_big = size_error(source)
    if too_big:
        raise ops.PdfToolError(too_big)
    progress(0.0, f'Convertendo {source.name}')
    if ext in OFFICE_EXTENSIONS:
        _office_to_pdf(source, dest)
    else:
        with FITZ_LOCK, ops.atomic_output(dest) as temp:
            if ext in IMAGE_EXTENSIONS:
                document = _image_document(source)
            elif ext in TEXT_EXTENSIONS:
                document = _text_document(source)
            elif ext in HTML_EXTENSIONS:
                document = _html_document(source.read_bytes(), source.name)
            else:
                document = _mupdf_document(source)
            try:
                if document.page_count < 1:
                    raise ops.PdfToolError(f'"{source.name}" não tem conteúdo para converter.')
                document.save(temp, garbage=3, deflate=True)
            finally:
                document.close()
    progress(1.0, '')
    return dest


def cached_pdf(source, folder):
    """O PDF convertido de source dentro de folder, criando-o se preciso. Cada arquivo tem a sua subpasta (nome do
    PDF = nome do original), então dois "relatorio.docx" de pastas diferentes não se misturam."""
    source = Path(source)
    key = hashlib.sha1(str(source.resolve()).casefold().encode('utf-8')).hexdigest()[:10]
    dest = Path(folder) / key / f'{source.stem}.pdf'
    if dest.is_file() and dest.stat().st_mtime >= source.stat().st_mtime:
        return dest
    return convert_to_pdf(source, dest)


def cleanup(paths, folder):
    """Apaga conversões criadas por cached_pdf (só dentro de folder, nunca um arquivo do usuário)."""
    root = Path(folder).resolve()
    for path in set(paths):
        try:
            resolved = Path(path).resolve()
            if resolved.is_relative_to(root) and resolved != root:
                resolved.unlink(missing_ok=True)
                with contextlib.suppress(OSError):
                    resolved.parent.rmdir()
        except OSError:
            continue


def _image_document(path):
    try:
        image_file = Image.open(path)
    except Exception as exc:
        raise ops.PdfToolError(f'"{path.name}" não é uma imagem válida: {exc}') from exc
    document = fitz.open()
    with image_file as image:
        too_many = pixels_error(image.width, image.height, path.name)
        if too_many:
            document.close()
            raise ops.PdfToolError(too_many)
        dpi = image.info.get('dpi', (0, 0))[0] if isinstance(image.info.get('dpi'), tuple) else 0
        dpi = float(dpi) if 72 <= float(dpi or 0) <= 1200 else DEFAULT_IMAGE_DPI
        for index in range(getattr(image, 'n_frames', 1)):
            image.seek(index)
            frame = _flatten(ImageOps.exif_transpose(image))
            width, height = _fit_a4(frame.width * 72 / dpi, frame.height * 72 / dpi)
            buffer = io.BytesIO()
            if frame.width * frame.height > 1_500_000:
                frame.save(buffer, 'JPEG', quality=90)
            else:
                frame.save(buffer, 'PNG')
            page = document.new_page(width=width, height=height)
            page.insert_image(page.rect, stream=buffer.getvalue())
    return document


def _flatten(frame):
    """RGB com fundo branco: transparência não pode virar preto."""
    if frame.mode in ('RGBA', 'LA') or (frame.mode == 'P' and 'transparency' in frame.info):
        rgba = frame.convert('RGBA')
        background = Image.new('RGB', rgba.size, 'white')
        background.paste(rgba, mask=rgba.getchannel('A'))
        return background
    return frame.convert('RGB')


def _fit_a4(width, height):
    """A página no tamanho da imagem, reduzida (nunca ampliada) para caber numa folha A4 na mesma orientação."""
    limit_w, limit_h = (A4[1], A4[0]) if width > height else A4
    factor = min(1.0, limit_w / width, limit_h / height)
    return max(1.0, width * factor), max(1.0, height * factor)


_TEXT_PAGE_CSS = (
    f'@page {{ margin: {TEXT_MARGIN}pt }} body {{ font-family: sans-serif; font-size: 10.5pt }} '
    'pre { font-family: monospace; font-size: 9.5pt; white-space: pre-wrap; word-wrap: break-word }'
)


def _decode_text(raw):
    """O texto do arquivo: UTF-16 (o "Unicode" do Bloco de Notas e do Excel) pela marca no início, depois UTF-8 e,
    por fim, o padrão do Windows (cp1252), que aceita qualquer byte."""
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return raw.decode('utf-16', errors='replace')
    for encoding in ('utf-8-sig', 'cp1252'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode('latin-1')


def _text_document(path):
    text = _decode_text(path.read_bytes())
    body = f'<pre>{html.escape(text)}</pre>'
    return _html_document(f'<html><body>{body}</body></html>'.encode(), path.name)


def _html_document(data, name):
    if b'<style' not in data.lower():
        data = data.replace(b'</head>', f'<style>{_TEXT_PAGE_CSS}</style></head>'.encode(), 1)
        if b'<style' not in data.lower():
            data = f'<html><head><style>{_TEXT_PAGE_CSS}</style></head>'.encode() + data + b'</html>'
    try:
        document = fitz.open(stream=data, filetype='html')
    except Exception as exc:
        raise ops.PdfToolError(f'Não foi possível abrir "{name}": {exc}') from exc
    document.layout(rect=fitz.Rect(0, 0, *A4), fontsize=11)
    pdf = fitz.open('pdf', document.convert_to_pdf())
    document.close()
    return pdf


def _mupdf_document(path):
    try:
        with fitz.open(path) as source:
            return fitz.open('pdf', source.convert_to_pdf())
    except Exception as exc:
        raise ops.PdfToolError(f'Não foi possível abrir "{path.name}": {exc}') from exc


def _office_to_pdf(source, dest):
    if not office_available(source):
        raise office_error(source)
    app, process = OFFICE_APPS[extension(source)]
    cleanup = _POWERSHELL_CLEANUP.replace('@COUNT@', _DOCUMENT_COUNTS[app])
    script = _POWERSHELL_PRELUDE + _POWERSHELL_SCRIPTS[app].replace('@OWN@', _POWERSHELL_OWN) + cleanup
    script = script.replace('{process}', process)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # O nome temporário termina em .pdf: o Excel acrescenta ".pdf" a qualquer outro final e o arquivo sairia com
    # outro nome. O PDF só troca o destino quando está completo.
    temp = dest.with_name(f'.{dest.stem}.{uuid.uuid4().hex[:8]}.rdf-tmp.pdf')
    try:
        run = _run_powershell(script, source, temp)
        if run.returncode != 0 or not temp.is_file() or temp.stat().st_size == 0:
            detail = _first_line(run.stderr or run.stdout)
            lowered = detail.lower()
            if 'senha' in lowered or 'password' in lowered:
                raise ops.PdfToolError(f'"{source.name}" está protegido por senha. Abra no {app} e salve sem senha.')
            raise ops.PdfToolError(f'O {app} não conseguiu converter "{source.name}". {detail}'.strip())
        os.replace(temp, dest)
    finally:
        temp.unlink(missing_ok=True)


def _kill_recorded(pids_file):
    """Fecha os processos do Office que o script anotou (o tempo acabou e o PowerShell já foi encerrado)."""
    try:
        recorded = [int(part) for part in pids_file.read_text(encoding='utf-8-sig').replace(',', ' ').split()]
    except (OSError, ValueError):
        return []
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    for pid in recorded:
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True, timeout=15, creationflags=flags)
    return recorded


def _run_powershell(script, source, temp):
    pids_file = Path(temp).with_suffix('.pids')
    env = dict(os.environ, RDF_ORIGEM=str(source), RDF_DESTINO=str(temp), RDF_PIDS=str(pids_file))
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        return subprocess.run(
            ['powershell', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', script],
            env=env,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=OFFICE_TIMEOUT_SECONDS,
            creationflags=flags,
        )
    except subprocess.TimeoutExpired as exc:
        _kill_recorded(pids_file)  # o Office travado não fica escondido, segurando o arquivo
        raise ops.PdfToolError(
            f'A conversão de "{source.name}" demorou mais de {OFFICE_TIMEOUT_SECONDS} s e foi interrompida. '
            'Confira se o programa do Office não está esperando uma resposta sua.'
        ) from exc
    except OSError as exc:
        raise ops.PdfToolError(f'Não foi possível chamar o Office para converter "{source.name}": {exc}') from exc
    finally:
        pids_file.unlink(missing_ok=True)


def _first_line(text):
    for line in (text or '').splitlines():
        if line.strip():
            return line.strip()[:200]
    return ''


class SourceCache:
    """As conversões para PDF dos arquivos escolhidos numa tela, numa pasta própria dela.

    Arquivos rápidos (imagem, texto, HTML...) são convertidos ao serem adicionados, para a lista já mostrar as páginas.
    Os do Office, que levam segundos, ficam para a hora de executar (resolve). A pasta some quando a tela é apagada."""

    def __init__(self, folder):
        self.folder = Path(folder)
        self.pdfs = {}  # caminho original (texto) -> PDF convertido

    @staticmethod
    def is_other_format(path):
        return extension(path) != '.pdf'

    def prepare(self, path):
        """Converte já, se for rápido. Devolve o PDF, ou None se ficou para depois (Office) ou não precisa."""
        if not self.is_other_format(path) or is_slow(path):
            return None
        return self._converted(path)

    def _converted(self, path):
        """O PDF convertido de path. Se o arquivo sumiu da pasta temporária (limpeza, antivírus, outra janela), converte
        de novo a partir do original em vez de falhar na hora de usar."""
        key = str(path)
        recorded = self.pdfs.get(key)
        if recorded is None or not Path(recorded).is_file():
            if recorded is not None:
                LOGGER.warning('PDF convertido sumiu (%s); convertendo de novo', recorded)
            self.pdfs[key] = str(cached_pdf(path, self.folder))
        return self.pdfs[key]

    def resolve(self, source, progress=ops._noop):
        """O que a operação deve abrir: o PDF convertido (convertendo agora, se faltar) ou o próprio arquivo."""
        if isinstance(source, (list, tuple)):
            return [self.resolve(item, progress) for item in source]
        key = str(source)
        if not self.is_other_format(source):
            return key
        progress(0.0, f'Abrindo {Path(source).name}')
        return self._converted(source)

    def pdf_for(self, path):
        """O PDF já convertido deste arquivo, ou o próprio caminho se for PDF; None se ainda não foi convertido."""
        if not self.is_other_format(path):
            return str(path)
        if str(path) not in self.pdfs:
            return None
        try:
            return self._converted(path)
        except (ops.PdfToolError, OSError):
            return None

    def forget(self, paths):
        gone = [self.pdfs.pop(str(path)) for path in paths if str(path) in self.pdfs]
        cleanup(gone, self.folder)

    def clear(self):
        self.pdfs.clear()
        shutil.rmtree(self.folder, ignore_errors=True)
