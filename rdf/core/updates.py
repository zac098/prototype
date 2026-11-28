"""Atualizações pelo GitHub: descobre a versão mais nova, baixa o instalador e confere se ele chegou inteiro.

Nada aqui conhece a interface: a tela chama estas funções numa thread e mostra o progresso. As conexões usam o
urllib do Python (respeita o proxy do Windows) com tempo limite, e só falam com o GitHub. Nenhum dado do usuário é
enviado: só o pedido da página da última versão, identificado como "RDF/versão".

Como cada versão é publicada (ver .github/workflows/release.yml): a release "vX.Y.Z" traz RDF_Setup_X.Y.Z.exe,
RDF_portatil_X.Y.Z.exe e SHA256SUMS.txt com a soma SHA-256 de cada .exe. O download só é aceito se a soma bater.
"""

import hashlib
import json
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from rdf import APP_VERSION

LOGGER = logging.getLogger('rdf')

REPOSITORY = 'zac098/prototype'
LATEST_API = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
RELEASES_PAGE = f'https://github.com/{REPOSITORY}/releases/latest'
USER_AGENT = f'RDF/{APP_VERSION}'
TIMEOUT_SECONDS = 20
CHUNK_BYTES = 256 * 1024
INSTALLER_PATTERN = re.compile(r'^RDF_Setup_[\w.-]+\.exe$', re.IGNORECASE)
CHECKSUMS_NAME = 'SHA256SUMS.txt'
MAX_NOTES_CHARS = 20000


class UpdateError(Exception):
    """Falha esperada (sem internet, arquivo corrompido...); a mensagem é mostrada ao usuário."""


class Cancelled(UpdateError):
    """O usuário cancelou o download."""


@dataclass(frozen=True)
class Release:
    version: str  # "4.1.0"
    notes: str  # o texto da versão (Markdown)
    page_url: str  # página da versão no GitHub
    installer_url: str = ''
    installer_name: str = ''
    installer_size: int = 0
    checksums_url: str = ''

    @property
    def can_install(self):
        return bool(self.installer_url and self.checksums_url)


def parse_version(text):
    """'v4.1.0' ou '4.1.0' -> (4, 1, 0). None se não for uma versão."""
    match = re.fullmatch(r'v?(\d+(?:\.\d+){0,3})', str(text or '').strip(), flags=re.IGNORECASE)
    return tuple(int(part) for part in match.group(1).split('.')) if match else None


def is_newer(candidate, current=APP_VERSION):
    """True se candidate é uma versão mais nova que current ('4.1.0' > '4.0.2'; '4.1' == '4.1.0')."""
    new, old = parse_version(candidate), parse_version(current)
    if new is None or old is None:
        return False
    width = max(len(new), len(old))
    return new + (0,) * (width - len(new)) > old + (0,) * (width - len(old))


def parse_release(data):
    """A resposta do GitHub (JSON da release) como Release. None se não for uma versão publicada utilizável."""
    if not isinstance(data, dict) or data.get('draft') or data.get('prerelease'):
        return None
    version = parse_version(data.get('tag_name'))
    if version is None:
        return None
    installer, checksums = {}, {}
    for asset in data.get('assets') or []:
        if not isinstance(asset, dict):
            continue
        name, url = str(asset.get('name') or ''), str(asset.get('browser_download_url') or '')
        if not url.startswith('https://'):
            continue
        if INSTALLER_PATTERN.match(name) and not installer:
            installer = {'url': url, 'name': name, 'size': int(asset.get('size') or 0)}
        elif name == CHECKSUMS_NAME:
            checksums = {'url': url}
    page = str(data.get('html_url') or '')
    return Release(
        version='.'.join(str(part) for part in version),
        notes=str(data.get('body') or '')[:MAX_NOTES_CHARS],
        page_url=page if page.startswith('https://') else RELEASES_PAGE,
        installer_url=installer.get('url', ''),
        installer_name=installer.get('name', ''),
        installer_size=installer.get('size', 0),
        checksums_url=checksums.get('url', ''),
    )


def urlopen(request, timeout):
    """O urllib só é carregado quando o RDF procura uma atualização (ele e o ssl pesam na abertura do app)."""
    import urllib.request

    return urllib.request.urlopen(request, timeout=timeout)


def notes_for_app(notes):
    """As novidades sem as instruções de instalação que a página da versão traz no topo (dentro do app, quem instala é
    o próprio RDF)."""
    kept = [
        line
        for line in str(notes or '').splitlines()
        if not line.lstrip().startswith(('**Como instalar:**', 'O `RDF_portatil'))
    ]
    return '\n'.join(kept).strip()


def _request(url, accept='*/*'):
    import urllib.request

    return urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': accept})


def _read(url, opener, accept='*/*', limit=2 * 1024 * 1024):
    try:
        with opener(_request(url, accept), timeout=TIMEOUT_SECONDS) as response:
            return response.read(limit + 1)[:limit]
    except OSError as exc:  # sem internet, proxy, DNS, tempo esgotado, HTTP 4xx/5xx (HTTPError é OSError)
        raise UpdateError(f'Não foi possível falar com o GitHub ({_reason(exc)}).') from exc


def _reason(exc):
    code = getattr(exc, 'code', None)
    if code:
        return f'HTTP {code}'
    reason = getattr(exc, 'reason', None) or exc
    return str(reason)[:120] or type(exc).__name__


def fetch_latest(opener=urlopen):
    """A última versão publicada no GitHub, ou None se não houver nenhuma utilizável."""
    raw = _read(LATEST_API, opener, accept='application/vnd.github+json')
    try:
        data = json.loads(raw.decode('utf-8'))
    except ValueError as exc:
        raise UpdateError('O GitHub respondeu algo que não é uma versão do RDF.') from exc
    return parse_release(data)


def check(current=APP_VERSION, opener=urlopen):
    """A versão mais nova que current, se existir; senão None."""
    release = fetch_latest(opener)
    return release if release is not None and is_newer(release.version, current) else None


def parse_checksums(text):
    """'<sha256>  <arquivo>' por linha (formato do sha256sum) -> {arquivo: sha256}."""
    sums = {}
    for line in str(text).splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and re.fullmatch(r'[0-9a-fA-F]{64}', parts[0]):
            sums[parts[1].strip().lstrip('*')] = parts[0].lower()
    return sums


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b''):
            digest.update(chunk)
    return digest.hexdigest()


def download(url, dest, expected_size=0, progress=None, cancelled=None, opener=urlopen):
    """Baixa url para dest. Grava num .parcial e só troca pelo nome final quando chegou tudo.

    progress(baixados, total) é chamado a cada pedaço; cancelled() devolvendo True interrompe (Cancelled)."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_name(dest.name + '.parcial')
    received = 0
    try:
        with opener(_request(url), timeout=TIMEOUT_SECONDS) as response, open(partial, 'wb') as handle:
            total = int(response.headers.get('Content-Length') or 0) or int(expected_size or 0)
            while True:
                if cancelled is not None and cancelled():
                    raise Cancelled('Download cancelado.')
                chunk = response.read(CHUNK_BYTES)
                if not chunk:
                    break
                handle.write(chunk)
                received += len(chunk)
                if progress is not None:
                    progress(received, total)
        if total and received != total:
            raise UpdateError('O download veio incompleto. Tente de novo.')
        partial.replace(dest)
        return dest
    except OSError as exc:
        raise UpdateError(f'O download falhou ({_reason(exc)}).') from exc
    finally:
        partial.unlink(missing_ok=True)


def download_installer(release, folder, progress=None, cancelled=None, opener=urlopen):
    """Baixa o instalador da versão e confere a soma SHA-256 publicada junto. Devolve o caminho do instalador."""
    if not release.can_install:
        raise UpdateError('Esta versão não tem instalador para baixar. Abra a página da versão.')
    sums = parse_checksums(_read(release.checksums_url, opener).decode('utf-8', 'replace'))
    expected = sums.get(release.installer_name)
    if not expected:
        raise UpdateError('A versão não traz a soma de verificação do instalador; por segurança, ele não foi baixado.')
    path = download(
        release.installer_url,
        Path(folder) / release.installer_name,
        release.installer_size,
        progress,
        cancelled,
        opener,
    )
    if sha256_of(path) != expected:
        path.unlink(missing_ok=True)
        raise UpdateError('O arquivo baixado não confere com o publicado (veio corrompido). Tente de novo.')
    return path


def is_installed_copy(executable=None):
    """True quando o RDF roda da pasta do instalador (que tem o desinstalador ao lado): só aí dá para atualizar sozinho.

    A versão portátil e o código-fonte abrem a página da versão para baixar."""
    if executable is None:
        if not getattr(sys, 'frozen', False):
            return False
        executable = sys.executable
    return (Path(executable).resolve().parent / 'unins000.exe').is_file()


def installer_command(installer):
    """Instalador em modo silencioso: só a barra de progresso, mantendo as opções da instalação anterior.

    No fim ele abre o RDF de novo (packaging/installer.iss, [Run] com WizardSilent)."""
    return [str(installer), '/SILENT', '/SP-', '/NORESTART', '/CLOSEAPPLICATIONS']
