# RDF - Ferramentas de PDF e Renomeador de Folhas

Aplicativo desktop (Windows, Qt/PySide6) com uma caixa de ferramentas de PDF que funciona **offline**: seus
arquivos não saem do computador. A função original do RDF, ler folhas de ponto, atestados e declarações
por texto embutido ou OCR (Tesseract) e renomear os arquivos com revisão humana, é uma das ferramentas.

> Versão para avaliação interna, não homologada para uso com dados reais. Veja `docs/LEIA-ME.txt` e `docs/termos/`.

## Ferramentas

| Categoria | Ferramentas |
|---|---|
| Folha de ponto | Renomear folhas de ponto (matrícula, nome e mês; atestados e declarações) |
| Organizar | Unir (com botão Imprimir, pela janela de impressão do Windows), Dividir, Remover páginas, Extrair páginas, Organizar páginas |
| Otimizar | Comprimir, Reparar, OCR (PDF pesquisável) |
| Converter | Imagem para PDF, PDF para imagem (páginas em JPG/PNG ou imagens embutidas) |
| Editar | Girar, Cortar margens, Números de página, Marca d'água |
| Segurança | Proteger (AES-256) e Desbloquear PDF |

### Outros tipos de arquivo

As ferramentas (menos Reparar e Desbloquear) e a impressão aceitam também imagens (JPG, PNG, BMP, GIF, TIFF, WEBP),
textos (TXT, MD, CSV, LOG, JSON, XML), HTML, SVG, CBZ e documentos do Word, Excel e PowerPoint. Eles são convertidos para PDF
antes (`rdf/pdftools/sources.py`): imagem, texto e HTML pelo próprio app; Office pelo Microsoft Office instalado no
computador (PowerShell e COM, em segundo plano, macros desligadas e sem fechar o Word que o usuário já tinha aberto).

Fora do escopo por enquanto: converter PDF para Word, Excel e PowerPoint, assinar, comparar e editar o texto do PDF.

## Requisitos

- Python 3.10 ou superior
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) com os idiomas `por` e `eng`, usado pelo OCR e pelo
  renomeador (o app procura nas pastas comuns; para outro local, crie `tesseract_path.txt` na raiz com o caminho do `tesseract.exe`)

## Como rodar

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt -r requirements-dev.txt
.venv\Scripts\python -m rdf
```

`python rdf_app.py` faz o mesmo (é o ponto de entrada usado pelo PyInstaller e pelo `Iniciar RDF.bat`).

O app abre em Qt (PySide6).

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
`.venv_build`, gera `dist\RDF.exe` com o PyInstaller (a partir de `rdf_app.py`), monta o instalador
com `packaging\installer.iss` e entrega tudo em `RDF_DELIVERY_PACKAGE\` com o hash SHA-256.

A versão fica em um único lugar: `APP_VERSION` em `rdf/__init__.py`. O build lê a versão desse arquivo,
e o teste `tests/test_release.py` confere se o `installer.iss` está igual.

## Estrutura

```
rdf/
├── __init__.py          APP_VERSION
├── __main__.py          python -m rdf: abre o app em Qt
├── core/                renomeador de folhas, sem interface
│   ├── batch.py         o lote: arquivos, linhas, status, nomes e sessão
│   ├── inputs.py        entrada de arquivos: limites, conversão de imagens, separação de páginas
│   ├── analysis_runner.py  leitura em paralelo, com cancelamento
│   ├── exporter.py      exportação com nomes novos, sem nunca sobrescrever
│   └── ocr.py, parsing.py, classifier.py, naming.py ...  leitura e classificação dos documentos
├── pdftools/            ferramentas de PDF, sem interface
│   ├── ops.py           as operações (unir, dividir, comprimir, girar, proteger, ...)
│   ├── pages.py         leitura de intervalos como "1-3, 5, 8-"
│   ├── jobs.py          destinos sem colisão, valores das opções, execução e resumo
│   └── registry.py      catálogo: opções de cada ferramenta e a operação que executa
└── qt/                  janela Qt: tema, tela inicial, ferramentas e renomeador
tests/                   testes de comportamento (unittest)
assets/                  ícone do aplicativo
docs/                    histórico de versões, leia-me e termos de uso (docs/termos)
packaging/               script de build e instalador (Inno Setup)
```

### Como criar uma ferramenta nova

1. Escreva a operação em `rdf/pdftools/ops.py` (receba caminhos, devolva um `Result`, avise erros com `PdfToolError`).
2. Acrescente um `Tool` em `rdf/pdftools/registry.py` com as opções que ela pede. A tela, o formulário, a validação,
   o "salvar como" e a execução em segundo plano aparecem sozinhos.
3. O teste `test_default_options_run_every_tool_end_to_end` já cobre a ferramenta nova com as opções padrão.

## Dados pessoais

Os documentos de teste reais ficam fora do git (`pdf pra testar programa/` e `resultados/` estão no
`.gitignore`): são dados pessoais e de saúde (LGPD). Para testes automatizados, use apenas documentos
fictícios gerados pelo próprio teste, como fazem os testes atuais.
