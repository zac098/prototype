# Histórico de alterações

## 4.0.0 - Visual novo, tema escuro e seis ferramentas novas

### Visual e uso
- **Tema claro, escuro ou igual ao Windows**, trocando na hora (botão na tela inicial, Configurações ou Ctrl+Shift+T). No modo "igual ao Windows" o app acompanha a troca do sistema, e a barra de título também escurece. Todas as cores passam pelo tema, com contraste conferido nos dois.
- **Tela inicial nova**: barra com a marca, a versão, a busca e os botões de tema, configurações e ajuda; **favoritas** (estrela em cada ferramenta ou Ctrl+D) e **usadas recentemente** no topo; filtros por categoria; selo "Novo" nas ferramentas desta versão.
- **Busca melhor**: não diferencia acentos nem maiúsculas ("numeros" acha "Números"), acha por começo de palavra e mostra primeiro o mais relevante. Enter abre o primeiro resultado; as setas andam entre as ferramentas.
- **Configurações** (Ctrl+,): tema, abrir a pasta do resultado ao terminar, iniciar com o Windows, situação do Tesseract e pasta de dados. **Sobre** com as versões dos componentes e **lista de atalhos** (F1).
- A janela volta com o **tamanho e a posição** da última vez, e as janelas de escolher arquivos lembram a última pasta mesmo depois de fechar o app.

### Ferramentas de PDF
- Novas: **Tarjar dados (LGPD)** (apaga de verdade CPF, CNPJ, e-mail, telefone e textos digitados; o texto sai do arquivo e a imagem embaixo fica preta), **Metadados do PDF** (mostra autor, programa e datas, edita ou remove tudo), **PDF para texto** (.txt), **Escala de cinza**, **Várias páginas por folha** (2, 4, 6 ou 9) e **Ajustar tamanho do papel** (A4, Carta, Ofício, A3).
- **Miniaturas das páginas** em Remover, Extrair e Organizar páginas: clicar nas miniaturas preenche o campo de páginas (e vice-versa), com atalhos para todas, nenhuma, ímpares e pares; em Organizar, arrastar muda a ordem. Em Remover, as páginas marcadas ficam com o número em vermelho.
- Em Unir e Imagem para PDF, **arrastar os arquivos na lista** muda a ordem, e "A→Z" ordena por nome do jeito humano ("folha 2" antes de "folha 10").
- A prévia e as miniaturas são desenhadas em segundo plano: a janela não trava abrindo um PDF grande.
- Ao terminar: "Abrir arquivo", "Abrir pasta" e "Começar de novo".

### Renomear folhas de ponto
- **OCR até 4x mais rápido** com os mesmos resultados: cada Tesseract usa uma thread (com as quatro leituras em paralelo, as threads disputavam a CPU), a leitura do cabeçalho para assim que tem matrícula, nome e mês com boa confiança, e uma folha já reconhecida não tem a página inteira lida à procura de atestado. Nas 20 folhas de teste: 20 de 20 prontas, de 63 s para 16 s, com matrícula, nome e mês idênticos aos da versão anterior.
- Status em **pílulas coloridas**, **busca no lote** (Ctrl+L) por nome, novo nome ou matrícula, e **"Próximo a revisar" (F3)**, que leva direto ao próximo arquivo que precisa de conferência.
- Tempo restante estimado durante a análise, lote vazio com um convite para arrastar os documentos e botão "Abrir pasta exportada" depois de exportar.

### Correções e código
- O PyMuPDF não aceita duas threads ao mesmo tempo: as ferramentas, a prévia, as miniaturas e a impressão passam a usar a mesma trava que o renomeador já usava.
- Exportação do renomeador: cada destino planejado é conferido (a checagem anterior podia pular caminhos).
- Erros inesperados não somem mais calados: vão para o log e aparecem num aviso com o caminho dele.
- O mínimo passa a ser o **Python 3.11** (o Pillow fixado não instala no 3.10, que o projeto dizia aceitar); `Iniciar RDF.bat` e o build deixam de procurar o 3.10.
- Preferências do usuário em `preferencias.json` (só escolhas de uso, nada dos documentos), gravadas sem nunca ficar pela metade.
- CI também no Linux com o Python mínimo; regras extras do ruff (bugbear, pyupgrade); a suíte de testes caiu de 145 s para cerca de 80 s mesmo com mais de 100 testes novos.


## Imprimir passou para "Unir PDF"
- A ferramenta "Imprimir arquivos" foi removida. No lugar, "Unir PDF" ganhou o botão **Imprimir…** (atalho Ctrl+P): ele junta a lista, na ordem, e abre a janela de impressão do Windows, onde se escolhe impressora, papel, cópias, páginas, cor e frente e verso. Não precisa unir antes, e com um arquivo só ele é impresso sozinho. Aceita os mesmos tipos de arquivo das outras ferramentas (imagens, textos, Office).
- "Imprimir com o RDF" (botão direito) e "RDF - Imprimir arquivos" (Enviar para) agora abrem "Unir PDF" com os arquivos já na lista, prontos para o botão Imprimir. O ícone da bandeja tem "Imprimir ou unir PDFs".
- Corrigido o erro "no such file" com imagens: se o PDF convertido de uma imagem sumir da pasta temporária, o RDF converte de novo a partir do original em vez de falhar.
- A limpeza ao abrir o app só apaga pastas temporárias das ferramentas paradas há mais de 1 hora, para nunca apagar a de uma tela em uso.

## Outros tipos de arquivo nas ferramentas e na impressão
- Todas as ferramentas de PDF, e também "Imprimir PDFs", aceitam agora imagens (JPG, PNG, BMP, GIF, TIFF, WEBP), textos (TXT, MD, CSV, LOG, JSON, XML), HTML, SVG, CBZ e documentos do Word, Excel e PowerPoint (DOC, DOCX, RTF, ODT, XLS, XLSX, PPT, PPTX). Só "Reparar" e "Desbloquear" continuam só com PDF, porque só fazem sentido nele.
- É possível misturar tipos: por exemplo, unir um PDF, uma foto e um documento do Word num único PDF. A lista mostra o tipo de cada arquivo.
- Imagens, texto e HTML são convertidos ao adicionar (a lista já mostra as páginas). Documentos do Office usam o Microsoft Office instalado no computador, em segundo plano e com as macros desligadas, e são convertidos na hora de executar (leva alguns segundos por arquivo). Sem o Office, o app diz qual programa falta.
- As fotos viram páginas que nunca passam de uma folha A4 (a rotação do EXIF é aplicada e a transparência ganha fundo branco); texto e HTML saem em páginas A4 com margem e acentos.
- As conversões ficam numa pasta temporária de cada tela e são apagadas ao remover o arquivo, limpar a lista, sair da ferramenta ou fechar o app. O arquivo original nunca é alterado.
- "Imprimir com o RDF" aparece no botão direito de todos esses formatos (imagens, texto, HTML, Office e PDF), não só do PDF, e também aceita os arquivos na linha de comando. Selecionando tipos misturados (um PDF e uma foto, por exemplo) a opção continua aparecendo. Vale o limite do Windows de 15 arquivos por vez; "Enviar para" não tem limite.

## Fotos e imagens (JPG, PNG...) no renomeador
- A rotação gravada no EXIF é aplicada: a folha de scanner ou de celular que vinha de cabeça para baixo agora é lida de pé (de 15 s para 3 s por arquivo, quando antes dava certo; e arquivos que falhavam passam a funcionar).
- PNG com transparência ganha fundo branco (antes o fundo podia virar preto).
- O tamanho da página criada a partir da imagem acompanha a imagem, com teto para fotos grandes de scanner (o OCR não fica mais lento sem ler melhor).
- A folha inteira de um scanner não é mais cortada na tabela, o que jogava fora o cabeçalho com matrícula e nome.
- O rótulo "Chapa/Nome" lido com erro pelo OCR em imagens de baixa resolução (por exemplo "Chapalioma") é reconhecido, e um "Data de admissão" mal lido encerra o nome.
- Quando o cabeçalho não é lido (ou só lido pela metade), o app tenta uma leitura de resgate: ampliando imagens pequenas, e, em fotos de celular onde a folha não começa no topo da imagem, lendo a página inteira. Só roda nos arquivos que falhariam, então o lote não fica mais lento.
- Nos 5 arquivos de teste (JPG, JPEG e PNG), de 2 lidos passou-se para 5 lidos. Imagens muito pequenas ou borradas ainda podem errar uma letra do nome: o status continua pedindo conferência quando a confiança é baixa.

## Imprimir pelo menu do botão direito
- O instalador (opcional, marcado por padrão) acrescenta "Imprimir com o RDF" ao menu do botão direito dos PDFs e "RDF - Imprimir PDFs" ao menu "Enviar para". Por usuário, sem administrador; o desinstalador remove as duas entradas.
- Selecione os PDFs no Explorer, clique com o botão direito e escolha a opção: o RDF abre direto em "Imprimir PDFs" com todos os arquivos na lista. No Windows 11 a opção fica em "Mostrar mais opções".
- O Explorer abre o programa uma vez por arquivo (e só mostra a opção com até 15 arquivos selecionados). Por isso o RDF passou a ter uma única janela: o primeiro processo recebe os arquivos dos seguintes, que fecham sozinhos. "Enviar para" não tem esse limite de 15.
- Abrir o RDF de novo com ele já aberto traz a janela existente para a frente, em vez de abrir outra.

## Imprimir PDFs em lote (substituído: ver "Imprimir passou para Unir PDF")
- Nova ferramenta "Imprimir PDFs" (categoria Folha de ponto): jogue vários PDFs, ajuste a ordem, escolha a impressora e imprima tudo de uma vez. Cada arquivo vira um documento na fila da impressora.
- Opções: cópias, frente e verso, colorido ou preto e branco, páginas de cada arquivo (ex.: só a 1) e ajustar à área de impressão. Antes de imprimir, o app mostra um resumo com o total de páginas e pede confirmação.
- As páginas são desenhadas pelo próprio app (não depende do programa que abre PDF no Windows) e mantêm a orientação de cada uma. Dá para cancelar: o documento que estava saindo não é enviado; os já enviados continuam na fila da impressora.

## Sair da ferramenta com segurança
- Durante uma tarefa, Voltar, Esc e a busca (Ctrl+F) perguntam antes de sair: sair cancela a tarefa. O padrão da pergunta é "Continuar aqui".
- Com arquivos escolhidos e ainda não processados (ou, no renomeador, um lote não exportado), a saída avisa que o trabalho será descartado. No renomeador dá para "Exportar agora" ali mesmo.
- Ao sair, a ferramenta é zerada: ao voltar, ela abre vazia (no renomeador, a sessão salva e os arquivos temporários também são apagados).
- Nas ferramentas de PDF, o botão de ação vira "Cancelar tarefa" enquanto trabalha; o cancelamento interrompe a operação sem deixar arquivo pela metade e mantém o que já estava concluído.
- Atalhos: Ctrl+O (adicionar arquivos), Ctrl+Enter (executar) e Delete (remover da lista). As janelas de escolher arquivos lembram a última pasta usada.

## Organização
- Removida a interface antiga em Tkinter (`rdf/ui`, `python -m rdf.ui`) e os testes dela; o `requirements-legacy.txt` deixou de existir. O app é só Qt.
- A regra de uma thread do OpenCV por worker (`cv2.setNumThreads(1)`) morava no pacote Tkinter e o Qt não a aplicava; agora está em `rdf/core/imaging.py`.
- `iniciar_rdf.py` virou `rdf_app.py`, para não se confundir com o `Iniciar RDF.bat` (o `.bat` é o que o usuário abre; o `.py` é o ponto de entrada usado por ele e pelo PyInstaller).

## 3.0.0 - RDF vira uma caixa de ferramentas de PDF
- O app agora abre no novo visual em Qt (PySide6), com bordas suaves e animações: `python -m rdf`; o instalador gera esta versão (sem Tkinter). A versão antiga continua em `python -m rdf.ui`. Tem a tela inicial, as ferramentas de PDF e o renomeador de folhas de ponto, com as mesmas regras do app atual (leitura por OCR, revisão, correção manual, exportação com atestados e declarações separados, sessão recuperável, arrastar e soltar, prévia com zoom).
- Regras do renomeador separadas da interface, em `rdf.core`: `batch` (lote, nomes, status, sessão), `inputs` (limites, conversão de imagens, separação de páginas), `analysis_runner` (leitura em paralelo com cancelamento) e `exporter`.
- `rdf.pdftools.jobs`: planejamento e execução das ferramentas separados da interface (destinos sem colisão, valores das opções, resumo do resultado).
- Novo layout: tela inicial com as ferramentas agrupadas por categoria e uma busca no topo; o app se adapta a telas de 800x600 até 4K; cada ferramenta abre numa tela própria, com lista de arquivos, prévia, opções e um botão de ação.
- "Renomear folhas de ponto" (a função original do RDF) passa a ser uma das ferramentas, sem mudar de comportamento.
- Novas ferramentas, todas offline: Unir, Dividir, Remover páginas, Extrair páginas, Organizar páginas, Comprimir, Reparar, OCR (PDF pesquisável), Imagem para PDF, PDF para imagem, Girar, Cortar margens, Números de página, Marca d'água, Proteger e Desbloquear PDF.
- Arquivos gerados são gravados com segurança: um erro no meio nunca deixa um PDF pela metade e nada é sobrescrito sem o usuário escolher o nome.
- Organização do projeto: `rdf/pdftools` (operações e catálogo, sem interface), `rdf/ui/renamer` (tela de renomear), `docs/`, `assets/` e `packaging/` (instalador e script de build). Removidos arquivos obsoletos (lista de arquivos desatualizada, caches).

## Correções após a organização interna
- A prévia passa a aplicar a página renderizada pela thread principal, por meio de uma fila, como já acontecia na análise.
- A mensagem "Formato de exportação: ..." volta a aparecer ao trocar o formato (antes era sobrescrita na hora pelo status do filtro).
- O `BUILD_RDF_PACKAGE.bat` aponta o Tcl/Tk do Python base para o PyInstaller, que antes deixava o tkinter fora do `RDF.exe`.

## Organização interna (sem mudança de comportamento)
- Código dividido no pacote `rdf/`: `rdf/core` (leitura, OCR, classificação e nomes) e `rdf/ui` (janela, um módulo por área).
- O aplicativo abre com `python -m rdf` ou `iniciar_rdf.py`; a versão fica só em `rdf/__init__.py`.
- Importar o código não cria pastas nem procura o Tesseract; isso acontece apenas ao abrir o aplicativo.
- Testes que liam o código-fonte como texto foram trocados por testes de comportamento, incluindo a janela real.
- Adicionados `pyproject.toml`, ruff (lint e formatação) e `README.md` para desenvolvimento.

## 2.1.0
- Mantém o acesso ao Tkinter na thread principal e recebe resultados do OCR e atualizações de progresso por meio de uma fila segura para uso entre threads.
- Reconhece erros comuns de leitura do cabeçalho Chapa/Nome pelo OCR, incluindo "Chupa/Nomo" e "Chiupa/Nomo".
- Registra o formato de saída selecionado antes de iniciar a análise em segundo plano.
- Permite deixar campos de correção manual em branco, oferece uma lista de meses em letras maiúsculas e posiciona as janelas de diálogo na área de trabalho virtual do Windows.
- Adiciona à barra de ferramentas a reanálise dos arquivos selecionados, além de propriedades do arquivo e ações organizadas no menu de contexto.
- Exporta os arquivos renomeados com nomes, extensões e marcadores de páginas em letras maiúsculas.

## 2.0.4
- Deixa de usar nomes de arquivos originais como evidência para o OCR ou para identificar a matrícula.
- Calcula a confiança somente com base na linha do cabeçalho Chapa/Nome.
- Usa o mesmo percentual arredondado na exibição e na decisão entre OK e REVISAR.
- Interrompe a captura do nome ao encontrar variações de OCR de rótulos como admissão, função, horário, lotação e contrato.

## 2.0.3
- Corrige a perspectiva e remove margens escuras de folhas fotografadas quando identifica um contorno confiável da página.
- Usa o nome original do arquivo na interpretação do OCR, permitindo que um nome de arquivo numérico confirme a matrícula em vez do nome de um PDF temporário.
- Mantém os caminhos de OCR otimizado e abrangente introduzidos na versão 2.0.2.

## 2.0.2
- Restaura a rotina abrangente de OCR, já testada, como alternativa de compatibilidade somente para arquivos que os caminhos otimizados não conseguem reconhecer.
- Mantém o processamento rápido para folhas de ponto comuns e documentos nítidos, sem deixar de recuperar digitalizações difíceis reconhecidas pela versão 2.0.0.

## 2.0.1
- Prioriza o caminho rápido de reconhecimento de folhas de ponto antes do OCR mais custoso da página inteira.
- Reduz o OCR de documentos de até doze tentativas de orientação e layout por página para duas tentativas principais e, raramente, uma alternativa com a página girada.
- Reduz a renderização da página inteira de 2,4x para 1,8x e interrompe o processamento assim que há evidências suficientes para a classificação.

## 2.0.0
- Versão final do código-fonte institucional após o protótipo validado.
- Mantém os limites operacionais de 300 arquivos, 1.000 páginas, 100 MB por arquivo, aviso para arquivos acima de 30 MB e quatro tarefas paralelas.
- Preserva o lote atual ao adicionar mais arquivos ou selecionar outra pasta.
- Limpa o lote exibido junto com os dados locais da sessão para evitar referências desatualizadas.
- Padroniza os textos finais da interface em português e remove estilos não utilizados.

## 1.8.5
- Centraliza cada janela modal personalizada sobre a janela principal e mantém-na dentro da área visível da tela.

## 1.8.4
- Padroniza as mensagens restantes da interface em português.
- Substitui os textos de exportação que mencionavam somente PDF por mensagens compatíveis com outros formatos.
- Corrige o histórico de versões e os metadados do repositório.

## 1.8.3
- Usa o nome original do arquivo para nomear automaticamente ou manualmente atestados e declarações.
- Padroniza os títulos das etapas, os contadores e a acentuação em português na interface.

## 1.8.2
- Diferencia arquivos com o mesmo nome original quando estão em pastas distintas.
- Exibe N/D para atestados e declarações classificados, em vez de apresentar um percentual de confiança artificial.
- Abre a pasta de origem do arquivo e informa os nomes originais em caso de erro na exportação.

## 1.8.1
- Mantém os atestados e as declarações prontos quando as opções de nomenclatura são alteradas.
- Desvincula as opções de nomenclatura da confiança do OCR.
- Permite analisar arquivos sem selecionar campos para compor o nome.

## 1.8.0
- Aceita imagens válidas e decodificáveis mesmo quando a extensão do arquivo não corresponde ao formato identificado.
- Usa o nome original do arquivo, sem extensão, quando todos os campos de nomenclatura estão desativados.

## 1.7.9
- Valida as assinaturas reais dos arquivos e rejeita arquivos renomeados ou corrompidos, inclusive arquivos MP4 com extensão PDF.

## 1.7.8
- Preserva o nome e a extensão originais na coluna Arquivo original.
- Faz com que a extensão em Novo nome corresponda ao formato de exportação selecionado.

## 1.7.7 — versão-base institucional
- Remove o atualizador automático e a dependência de um repositório pessoal.
- Preserva a indicação de progresso do OCR.
- Adiciona as pastas `TERMS` e `DOCUMENTATION`.
- Substitui o script de publicação no GitHub por `BUILD_RDF_PACKAGE.bat`.
