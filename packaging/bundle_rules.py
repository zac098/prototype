"""O que entra no RDF empacotado. Usado pela receita do PyInstaller (rdf.spec) e conferido pelos testes.

O PyInstaller junta, por garantia, tudo o que as bibliotecas trazem, e o Tesseract instalado vem com programas de
treino e bibliotecas que só esses programas usam. O RDF não usa nada disso: tirar deixa o download menor e a
instalação mais rápida. Cada regra abaixo diz por que o item pode sair. O CI confere o resultado abrindo o próprio
executável (RDF.exe --autoteste): se algo necessário sair por engano, o build falha antes de virar versão.
"""

from pathlib import Path, PurePosixPath

# Caminho dentro do pacote (minúsculas, com "/") de arquivos que saem.
DROP_EXACT = {
    'pyside6/opengl32sw.dll',  # OpenGL por software (~20 MB): as telas do RDF não usam OpenGL
    'pyside6/d3dcompiler_47.dll',  # compilador de shaders do Direct3D, pelo mesmo motivo
}
DROP_PREFIXES = (
    'cv2/opencv_videoio_ffmpeg',  # vídeo no OpenCV (~27 MB): o RDF só lê imagens
    'cv2/data/',  # detectores de rosto e olhos do OpenCV
    'pyside6/plugins/tls/',  # HTTPS pelo Qt: o RDF baixa atualizações pelo Python
    'pyside6/plugins/networkinformation/',  # aviso de rede do Qt
    'pyside6/plugins/generic/',  # telas de toque e mesas digitalizadoras
    'pyside6/plugins/platforminputcontexts/',  # métodos de entrada do Linux
    'pyside6/plugins/platforms/qoffscreen',  # telas virtuais (só para testes)
    'pyside6/plugins/platforms/qminimal',
    'pyside6/plugins/platforms/qdirect2d',
)
# Das traduções do Qt, só a do português (botões Sim e Não, menu de copiar e colar).
KEEP_TRANSLATIONS = {'qtbase_pt_br.qm'}

# Do Tesseract: o programa, as bibliotecas que ele carrega de verdade e só o que a leitura usa.
TESSERACT_LANGUAGES = ('por', 'eng')
TESSDATA_KEEP_FOLDERS = ('configs', 'tessconfigs')  # configs/pdf, configs/tsv... usados pelo pytesseract
TESSDATA_KEEP_FILES = ('pdf.ttf',)  # fonte do texto invisível do PDF pesquisável (ferramenta OCR)


def normalized(dest):
    return str(dest).replace('\\', '/').lower()


def should_keep(dest):
    """True se o arquivo (caminho de destino dentro do pacote) deve ir para o executável."""
    name = normalized(dest)
    if name in DROP_EXACT or name.startswith(DROP_PREFIXES):
        return False
    if name.startswith(('pyside6/translations/', 'pyside6/qt/translations/')):
        return PurePosixPath(name).name in KEEP_TRANSLATIONS
    return True


def filter_toc(entries):
    """Lista do PyInstaller (destino, origem, tipo) sem o que o RDF não usa."""
    return [entry for entry in entries if should_keep(entry[0])]


def pe_imports(path):
    """DLLs que o programa ou a DLL importa (normais e atrasadas), pelo cabeçalho do arquivo. Só no Windows."""
    import pefile

    wanted = [
        pefile.DIRECTORY_ENTRY[name] for name in ('IMAGE_DIRECTORY_ENTRY_IMPORT', 'IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT')
    ]
    pe = pefile.PE(str(path), fast_load=True)
    try:
        pe.parse_data_directories(directories=wanted)
        entries = list(getattr(pe, 'DIRECTORY_ENTRY_IMPORT', [])) + list(
            getattr(pe, 'DIRECTORY_ENTRY_DELAY_IMPORT', [])
        )
        return [entry.dll.decode('ascii', 'ignore') for entry in entries]
    finally:
        pe.close()


def dll_closure(folder, start='tesseract.exe', read_imports=pe_imports):
    """As DLLs da pasta que start carrega, direta ou indiretamente (as do Windows ficam de fora: já estão lá)."""
    folder = Path(folder)
    available = {path.name.lower(): path for path in folder.glob('*.dll')}
    if not available:  # um Tesseract sem DLLs ao lado (compilado estático, ou fora do Windows): nada a procurar
        return []
    needed, queue = set(), [folder / start]
    while queue:
        for name in read_imports(queue.pop()):
            key = name.lower()
            if key in available and key not in needed:
                needed.add(key)
                queue.append(available[key])
    return sorted(available[key].name for key in needed)


def tesseract_files(folder, read_imports=pe_imports):
    """(origem, pasta de destino no pacote) de tudo o que o Tesseract embutido precisa."""
    folder = Path(folder)
    exe = folder / 'tesseract.exe'
    if not exe.is_file():
        raise FileNotFoundError(f'tesseract.exe não está em {folder}')
    files = [(exe, 'Tesseract-OCR')]
    files += [(folder / name, 'Tesseract-OCR') for name in dll_closure(folder, read_imports=read_imports)]
    tessdata = folder / 'tessdata'
    for language in TESSERACT_LANGUAGES:
        data = tessdata / f'{language}.traineddata'
        if not data.is_file():
            raise FileNotFoundError(f'Falta o idioma {language} do Tesseract: {data}')
        files.append((data, 'Tesseract-OCR/tessdata'))
    for name in TESSDATA_KEEP_FILES:
        if (tessdata / name).is_file():
            files.append((tessdata / name, 'Tesseract-OCR/tessdata'))
    for sub in TESSDATA_KEEP_FOLDERS:
        for path in sorted((tessdata / sub).glob('*')):
            if path.is_file():
                files.append((path, f'Tesseract-OCR/tessdata/{sub}'))
    return files
