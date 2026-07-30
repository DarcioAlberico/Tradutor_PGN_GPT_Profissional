; Instalador do PGN Tradutor Pro (Inno Setup 6). ROADMAP 21.
;
;   1. python -m PyInstaller PGN_Tradutor_Pro.spec
;   2. compilar este arquivo (ISCC.exe instalador\PGN_Tradutor_Pro.iss)
;
; Sai em `instalador\saida\PGN-Tradutor-Pro-<versao>-instalador.exe`.
;
; ---------------------------------------------------------------------------
; A REGRA QUE GOVERNA ESTE ARQUIVO
;
; O instalador **nao distribui nem toca em nenhum arquivo de dados**. Nem o
; glossario, nem o banco, nem as configuracoes, nem `backups\` ou `logs\`. Eles
; vivem em `%APPDATA%\PGN Tradutor Pro\`, que este instalador nao conhece.
;
; O glossario inicial de uma instalacao nova vai DENTRO do pacote (o
; `Substituicoes-inicial.txt`, em `_internal\tradutor_pgn\`), e quem o instala e
; a primeira execucao do programa — e so quando nao ha glossario nenhum na pasta
; de dados. E o que garante que atualizar nunca passe por cima do trabalho de
; quem usa: o instalador nao tem o arquivo para sobrescrever.
;
; Ate a versao anterior o README mandava copiar o `Substituicoes.txt` para dentro
; de `dist\` antes de distribuir. Um instalador construido sobre aquela pasta
; levaria o glossario junto e o sobrescreveria a cada atualizacao — em silencio,
; e justamente o arquivo que representa meses de curadoria.
; ---------------------------------------------------------------------------

#define AppName "PGN Tradutor Pro"
#define AppVersion "1.0.0"
#define AppExe "PGN_Tradutor_Pro.exe"
#define DistDir "..\dist\PGN_Tradutor_Pro"

[Setup]
AppId={{7C1D9F2E-5A64-4B7C-9E3D-1F2A6B8C4D50}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=DarcioAlberico
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir=saida
OutputBaseFilename=PGN-Tradutor-Pro-{#AppVersion}-instalador
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Por usuario, sem pedir administrador. Nao e so conveniencia: sem elevacao o
; SmartScreen incomoda menos, e o programa nao e assinado (o README explica).
; Com os dados fora da pasta do programa, instalar em `Program Files` tambem
; funcionaria — o que nao funcionava era a versao anterior, que gravava banco e
; backups ao lado do `.exe`.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#AppExe}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na area de trabalho"; GroupDescription: "Atalhos:"

[Files]
; A pasta do PyInstaller inteira. `recursesubdirs` leva o `_internal`, onde estao
; o `spelling.ssp`, a semente, os termos suspeitos e o glossario inicial.
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir o {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; O indice de grafias (`spelling.db`, ~25 MB) e derivado e fica na pasta de
; DADOS, entao a desinstalacao nao o alcanca — e nem deve: apagar a pasta de
; dados apagaria o glossario junto. Aqui ficam so sobras da pasta do programa.
Type: filesandordirs; Name: "{app}\_internal\__pycache__"

[Code]
// O desinstalador NAO apaga a pasta de dados por conta propria. Ele pergunta, e
// o padrao e nao apagar: quem desinstala para reinstalar uma versao nova nao
// quer perder 200 mil traducoes por ter clicado rapido demais.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Dados: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    Dados := ExpandConstant('{userappdata}\{#AppName}');
    if DirExists(Dados) then
    begin
      if MsgBox('Apagar tambem os seus dados?' + #13#10#13#10 +
                'Isto remove o glossario, o banco de traducoes, os backups e as ' +
                'configuracoes em:' + #13#10 + Dados + #13#10#13#10 +
                'Se voce for reinstalar o programa, responda Nao.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Dados, True, True, True);
    end;
  end;
end;
