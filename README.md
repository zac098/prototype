# RDF - Ferramentas de PDF e Renomeador de Folhas

Aplicativo desktop (Windows, Qt/PySide6) com uma caixa de ferramentas de PDF que funciona **offline**: seus
arquivos não saem do computador. A função original do RDF, ler folhas de ponto, atestados e declarações
por texto embutido ou OCR (Tesseract) e renomear os arquivos com revisão humana, é uma das ferramentas.

> Versão para avaliação interna, não homologada para uso com dados reais. Veja `docs/LEIA-ME.txt` e `docs/termos/`.

## Ferramentas

| Categoria | Ferramentas |
|---|---|
| Folha de ponto | Renomear folhas de ponto (matrícula, nome e mês; atestados e declarações) |
| Organizar | Unir (com botão Imprimir, que abre tudo junto no Microsoft Edge), Dividir, Remover páginas, Extrair páginas, Organizar páginas |
| Otimizar | Comprimir, Reparar, OCR (PDF pesquisável) |
| Converter | Imagem para PDF, PDF para imagem (páginas em JPG/PNG ou imagens embutidas), PDF para texto (.txt) |
| Editar | Girar, Cortar margens, Números de página, Marca d'água, Escala de cinza, Ajustar tamanho do papel |
| Segurança | Proteger (AES-256), Desbloquear PDF, Tarjar dados (LGPD: CPF, CNPJ, e-mail, telefone e textos), Metadados do PDF |

Em Remover, Extrair e Organizar páginas, as páginas aparecem como **miniaturas**: clicar nelas (ou arrastar, em
Organizar) preenche o campo de páginas, e digitar no campo marca as miniaturas.

### Interface

- Tema **claro, escuro ou igual ao Windows** (troca na hora; contraste conferido nos dois temas pelos testes).
- Ícones vetoriais próprios (`rdf/qt/icons.py`), nítidos em qualquer escala de tela e iguais em qualquer Windows.
- Tela inicial com **favoritas** (estrela ou Ctrl+D), **usadas recentemente**, filtros por categoria e busca que não
  diferencia acentos. Enter abre o primeiro resultado e as setas andam entre as ferramentas.
- **Configurações** (Ctrl+,), **Sobre** e **atalhos do teclado** (F1). A janela volta com o tamanho e a posição da
  última vez.
- No renomeador: status em cores, busca no lote (Ctrl+L) e **Próximo a revisar** (F3).

### Outros tipos de arquivo

As ferramentas (menos Reparar e Desbloquear) e a impressão aceitam também imagens (JPG, PNG, BMP, GIF, TIFF, WEBP),
textos (TXT, MD, CSV, LOG, JSON, XML), HTML, SVG, CBZ e documentos do Word, Excel e PowerPoint. Eles são convertidos para PDF
antes (`rdf/pdftools/sources.py`): imagem, texto e HTML pelo próprio app; Office pelo Microsoft Office instalado no
computador (PowerShell e COM, em segundo plano, macros desligadas e sem fechar o Word que o usuário já tinha aberto).

Fora do escopo por enquanto: converter PDF para Word, Excel e PowerPoint, assinar, comparar e editar o texto do PDF.

## Baixar e instalar

Na página **Releases** do repositório, baixe o `RDF_Setup_<versão>.exe` da versão mais nova e execute. Ele não pede
administrador e atualiza a versão anterior mantendo as configurações. O `RDF_portatil_<versão>.exe` roda sem instalar
(mas sem o "Imprimir com o RDF" no botão direito). O Tesseract já vem dentro dos dois. O `SHA256SUMS.txt` serve para
conferir que o arquivo baixado é o original.

Depois de instalado, o próprio RDF avisa quando sai uma versão nova (aviso na tela inicial; também em Ajuda >
Procurar atualizações). Ele baixa o instalador, confere o SHA-256 publicado na release, fecha e instala em modo
silencioso, abrindo de novo no fim (`rdf/core/updates.py`, `rdf/qt/updater.py`). A procura só consulta a API de
releases do GitHub e pode ser desligada nas Configurações. Na versão portátil, o aviso abre a página da versão.

### Publicar uma versão nova

1. Troque `APP_VERSION` em `rdf/__init__.py` (e acrescente a versão no `docs/CHANGELOG.md`).
2. Leve a mudança para a `main` (merge do PR). O workflow **Instalador** (`.github/workflows/release.yml`) vê que
   essa versão ainda não tem release, monta os `.exe` num Windows do GitHub e cria a tag `vX.Y.Z` e a release, com as
   notas da versão tiradas do `docs/CHANGELOG.md`. Enviar a tag à mão (`git push origin v4.0.1`) também funciona.
3. Para só gerar os arquivos, sem release: Actions > Instalador > Run workflow.

## Requisitos

- Python 3.11 ou superior (o Pillow fixado em `requirements.txt` não instala no 3.10)
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) com os idiomas `por` e `eng`, usado pelo OCR e pelo
  renomeador (o app procura nas pastas comuns; para outro local, crie `tesseract_path.txt` na raiz com o caminho do `tesseract.exe`)

## Como rodar

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt -r requirements-dev.txt
.venv\Scripts\python -m rdf
```

`python rdf_app.py` faz o mesmo (é o ponto de entrada usado pelo PyInstaller e pelo `Iniciar RDF.bat`).

O app abre em Qt (PySide6). As preferências (tema, favoritas, tamanho da janela) ficam em
`%LOCALAPPDATA%\RDF\preferencias.json`, junto com o log e a sessão do renomeador.

### Imprimir pelo menu do botão direito (abre "Unir PDF")

O instalador pode acrescentar "Imprimir com o RDF" ao menu de todos os formatos aceitos (PDF, imagens, texto, HTML, Office)
e "RDF - Imprimir arquivos" ao "Enviar para"
(`packaging/installer.iss`, seção `[Registry]` e tarefas `contextmenu` e `sendto`). O programa recebe os arquivos com
`RDF.exe --imprimir arquivo1.pdf arquivo2.pdf ...`; só existe uma janela, e os outros processos entregam os arquivos
a ela (`rdf/qt/single_instance.py`).

## Testes e qualidade

```bash
.venv\Scripts\python -m unittest discover -s tests -q
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format .
```

- Os testes da interface Qt rodam sem janela de verdade (plataforma `offscreen`), com pastas temporárias e o
  leitor de OCR trocado por um falso (`tests/test_qt_renamer.py`, `tests/test_qt_prototype.py`). As regras do
  renomeador são testadas sem interface em `tests/test_batch.py`.
- As operações de PDF são testadas com PDFs gerados pelo próprio teste (`tests/test_pdftools.py`).
- O Tesseract é simulado nos testes de OCR do renomeador, então a suíte roda sem ele.

## Gerar o instalador

Execute `packaging\build_package.bat`. Ele precisa de Python, Tesseract e Inno Setup instalados, cria o
`.venv_build` e roda o PyInstaller com a receita `packaging\rdf.spec`, que gera numa só análise:

- `dist\RDF\` (pasta com `RDF.exe` e `_internal`): é o que o instalador copia. Abre rápido, porque nada é
  descompactado a cada abertura;
- `dist\RDF_portatil.exe`: um arquivo só, para usar sem instalar.

O que fica de fora do pacote (e por quê) está em `packaging\bundle_rules.py`: OpenGL por software, vídeo do OpenCV,
plugins sem uso do Qt, traduções que não são pt-BR, arquivos de desenvolvimento e, do Tesseract, tudo o que o
`tesseract.exe` não carrega (as DLLs são escolhidas pelo cabeçalho dos arquivos). Depois o script roda
`RDF.exe --autoteste` (bibliotecas, leitura real do Tesseract embutido, ferramentas de PDF, conexão segura e todas as
telas), monta o instalador com `packaging\installer.iss` e entrega tudo em `RDF_DELIVERY_PACKAGE\` com o hash SHA-256.
O workflow `.github/workflows/release.yml` faz o mesmo num Windows do GitHub e só publica a versão se o autoteste das
duas entregas passar.

A versão fica em um único lugar: `APP_VERSION` em `rdf/__init__.py`. O build lê a versão desse arquivo,
e o teste `tests/test_release.py` confere se o `installer.iss` está igual.

## Estrutura

```
rdf/
├── __init__.py          APP_VERSION
├── __main__.py          python -m rdf: abre o app em Qt (ou roda o autoteste, com --autoteste)
├── selftest.py          autoteste do app empacotado: bibliotecas, Tesseract, PDF, conexão segura e telas
├── core/                renomeador de folhas, sem interface
│   ├── batch.py         o lote: arquivos, linhas, status, nomes, sessão, busca e "próximo a revisar"
│   ├── settings.py      preferências do usuário (tema, favoritas, recentes, janela), gravadas com segurança
│   ├── updates.py       atualização pelo GitHub: última versão, download e conferência do SHA-256
│   ├── lazy.py          módulos carregados só no primeiro uso (abertura rápida)
│   ├── inputs.py        entrada de arquivos: limites, conversão de imagens, separação de páginas
│   ├── analysis_runner.py  leitura em paralelo, com cancelamento
│   ├── exporter.py      exportação com nomes novos, sem nunca sobrescrever
│   └── ocr.py, parsing.py, classifier.py, naming.py ...  leitura e classificação dos documentos
├── pdftools/            ferramentas de PDF, sem interface
│   ├── ops.py           as operações (unir, dividir, comprimir, girar, proteger, ...)
│   ├── formats.py       formatos aceitos (leve: usado pela tela inicial e pelo menu do botão direito)
│   ├── choices.py       listas das opções das ferramentas (tamanhos de papel, níveis de compressão...)
│   ├── pages.py         leitura (e escrita) de intervalos como "1-3, 5, 8-"
│   ├── jobs.py          destinos sem colisão, valores das opções, execução e resumo
│   └── registry.py      catálogo: opções de cada ferramenta e a operação que executa
└── qt/                  janela Qt
    ├── theme.py         paletas clara e escura, folha de estilo e troca de tema em tempo real
    ├── icons.py         ícones vetoriais do RDF (SVG), na cor do tema
    ├── updater.py       aviso de versão nova, janela de download e instalação
    ├── home.py          tela inicial (busca, favoritas, recentes, filtros)
    ├── tool_page.py     tela padrão das ferramentas (montada a partir do catálogo)
    ├── page_picker.py   miniaturas para escolher e reordenar páginas
    ├── thumbnails.py    miniaturas e prévia desenhadas em segundo plano
    ├── renamer.py       tela do renomeador de folhas
    ├── app_dialogs.py   Configurações, Sobre e atalhos
    └── errors.py        erros inesperados vão para o log e aparecem num aviso
tests/                   testes de comportamento (unittest)
assets/                  ícone do aplicativo
docs/                    histórico de versões, leia-me e termos de uso (docs/termos)
packaging/               receita do PyInstaller (rdf.spec), regras do pacote, script de build e instalador
```

### Como criar uma ferramenta nova

1. Escreva a operação em `rdf/pdftools/ops.py` (receba caminhos, devolva um `Result`, avise erros com `PdfToolError`).
2. Acrescente um `Tool` em `rdf/pdftools/registry.py` com as opções que ela pede. A tela, o formulário, a validação,
   o "salvar como" e a execução em segundo plano aparecem sozinhos.
3. O teste `test_default_options_run_every_tool_end_to_end` já cobre a ferramenta nova com as opções padrão.
4. Opcional: um ícone em `TOOL_ICONS` (código da fonte Segoe MDL2 Assets), o selo "Novo" em `NEW_TOOLS`, miniaturas
   de páginas com `page_picker=('select', 'pages')` e outro formato de saída com `output_ext='txt'`.
5. Use só cores do tema (`rdf/qt/theme.py`): nenhuma tela define cores próprias, para o tema escuro funcionar.

## Dados pessoais

Os documentos de teste reais ficam fora do git (`pdf pra testar programa/` e `resultados/` estão no
`.gitignore`): são dados pessoais e de saúde (LGPD). Para testes automatizados, use apenas documentos
fictícios gerados pelo próprio teste, como fazem os testes atuais.
