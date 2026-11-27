#define MyAppName "Renomeador de Folhas (RDF)"
#ifndef MyAppVersion
  #define MyAppVersion "4.0.1"
#endif
#define MyAppPublisher "RENAPSI"
#define MyAppExeName "RDF.exe"

[Setup]
AppId={{D3BE12D9-84A1-4C81-A2B7-73FB83D45C10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\RDF
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
OutputDir=..\installer_output
OutputBaseFilename=RDF_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\docs\termos\TERMS_OF_USE.txt
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
#if FileExists("..\\assets\\icone.ico")
SetupIconFile=..\assets\icone.ico
#endif

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na area de trabalho"; GroupDescription: "Atalhos adicionais:"; Flags: unchecked
Name: "contextmenu"; Description: "Adicionar ""Imprimir com o RDF"" ao menu do botao direito dos PDFs"; GroupDescription: "Integracao com o Windows:"
Name: "sendto"; Description: "Adicionar ""RDF - Imprimir arquivos"" ao menu Enviar para (serve para qualquer quantidade de arquivos)"; GroupDescription: "Integracao com o Windows:"
Name: "autostart"; Description: "Iniciar o RDF com o Windows, em segundo plano (o botao direito abre mais rapido)"; GroupDescription: "Integracao com o Windows:"; Flags: unchecked

[Files]
Source: "..\dist\RDF.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\termos\TERMS_OF_USE.txt"; DestDir: "{app}\TERMOS"; DestName: "Termos de Uso.txt"; Flags: ignoreversion
Source: "..\docs\termos\TERMS_MAINTENANCE_GUIDE.txt"; DestDir: "{app}\TERMOS"; DestName: "Orientacoes para Alteracao dos Termos.txt"; Flags: ignoreversion
#if FileExists("..\docs\DELIVERY_GUIDE.md")
Source: "..\docs\DELIVERY_GUIDE.md"; DestDir: "{app}\DOCUMENTACAO"; DestName: "Guia de Entrega.md"; Flags: ignoreversion
#endif

[Registry]
; Menu do botao direito dos PDFs (por usuario, sem administrador). No Windows 11 aparece em "Mostrar mais opcoes".
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
; Imprimir com o RDF nos outros formatos aceitos (imagens, texto, HTML, Office...). Mesma entrada do PDF.
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.bmp\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.bmp\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.bmp\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.cbz\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.cbz\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.cbz\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.csv\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.csv\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.csv\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.doc\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.doc\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.doc\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.docx\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.docx\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.docx\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.gif\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.gif\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.gif\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.htm\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.htm\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.htm\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.html\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.html\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.html\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.jpeg\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.jpeg\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.jpeg\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.jpg\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.jpg\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.jpg\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.json\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.json\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.json\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.log\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.log\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.log\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.md\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.md\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.md\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odt\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odt\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.odt\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.png\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.png\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.png\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ppt\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ppt\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.ppt\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pptx\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pptx\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pptx\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.rtf\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.rtf\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.rtf\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.svg\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.svg\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.svg\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tif\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tif\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tif\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tiff\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tiff\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.tiff\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.txt\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.txt\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.txt\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.webp\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.webp\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.webp\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xls\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xls\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xls\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xlsx\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xlsx\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xlsx\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xml\shell\RDFImprimir"; ValueType: string; ValueName: ""; ValueData: "Imprimir com o RDF"; Flags: uninsdeletekey; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xml\shell\RDFImprimir"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#MyAppExeName}"""; Tasks: contextmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.xml\shell\RDFImprimir\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" --imprimir ""%1"""; Tasks: contextmenu

; Inicio automatico (por usuario, sem administrador). Desmarcado por padrao: deixa o RDF na bandeja, perto do relogio.
Root: HKA; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "RDF"; ValueData: """{app}\{#MyAppExeName}"" --segundo-plano"; Flags: uninsdeletevalue; Tasks: autostart

[Icons]
Name: "{userprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{sendto}\RDF - Imprimir arquivos"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--imprimir"; WorkingDir: "{app}"; Tasks: sendto

[UninstallDelete]
; Sessão, cópias temporárias de documentos e logs (podem ter nomes e matrículas): não ficam para trás.
Type: filesandordirs; Name: "{localappdata}\RDF"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
// O proprio RDF tambem liga e desliga o inicio automatico (menu da bandeja), entao o valor pode existir
// mesmo sem a tarefa do instalador: ao desinstalar, apaga de qualquer jeito.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'RDF');
end;
