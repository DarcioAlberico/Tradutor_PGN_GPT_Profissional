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
#define AppExe "PGN_Tradutor_Pro.exe"

; O GUID da instalacao, SEM chaves, definido uma vez.
;
; Ele aparece em dois lugares que precisam de formas diferentes: o `AppId` quer a
; forma escapada (`{{...}`, porque `{` inicia constante no Inno) e a chave do
; registro quer a forma crua (`{...}`). A primeira versao usava
; `SetupSetting("AppId")` no `[Code]`, que devolve o texto **cru da diretiva** —
; ou seja, com o `{{` do escape — e montava um caminho de registro que nao existe.
; A guarda contra downgrade entao saia liberando tudo, em silencio, e so o ciclo
; de verificacao mostrou.
#define AppGuid "7C1D9F2E-5A64-4B7C-9E3D-1F2A6B8C4D50"

; O `#ifndef` deixa a linha de comando mandar (`ISCC /DDistDir=<pasta>`), e nao e
; luxo: o roteiro de verificacao compila uma copia desta receita fora da pasta do
; projeto, e um caminho relativo resolvido a partir DELA aponta para o vazio.
#ifndef DistDir
  #define DistDir "..\dist\PGN_Tradutor_Pro"
#endif

; A VERSAO E LIDA DO PROPRIO EXECUTAVEL, e nao declarada aqui (ROADMAP 21.6). O
; `.spec` carimba nele o que `tradutor_pgn/__version__` diz, e este arquivo le de
; la — entao nao existe um segundo numero para esquecer de atualizar. Um
; instalador anunciando 1.0.0 sobre um programa 0.3.0 e o tipo de mentira que so
; aparece quando alguem tenta descobrir qual versao esta instalada.
;
; O `#ifndef` existe para o roteiro de verificacao, que simula uma atualizacao
; sem reconstruir o executavel (`ISCC /DAppVersion=...`).
#ifndef AppVersion
  #define AppVersion GetStringFileInfo(AddBackslash(DistDir) + AppExe, "ProductVersion")
#endif

[Setup]
AppId={{{#AppGuid}}
AppName={#AppName}
AppVersion={#AppVersion}
; O que aparece em "Programas e Recursos" e no titulo do assistente. Com o nome
; junto, a versao instalada fica visivel sem abrir nada.
AppVerName={#AppName} {#AppVersion}
; A versao do proprio instalador, para que as propriedades do `.exe` de setup
; digam o mesmo que o programa que ele carrega.
VersionInfoVersion={#AppVersion}
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
// Instalar uma versao MAIS VELHA por cima de uma mais nova nao e recusado pelo
// Inno sozinho, e o estrago e do tipo que ninguem associa a causa: o programa
// volta no tempo, os dados ficam (a pasta deles nao e tocada — I1) e a versao
// antiga pode nao entender um esquema de banco que a nova ja migrou.
//
// A comparacao usa `StrToVersion`/`ComparePackedVersion`, e nao texto: "0.10.0"
// e maior que "0.9.0" e MENOR em ordem alfabetica.
//
// E um AVISO, e nao um bloqueio: voltar para a versao anterior de proposito e um
// caminho legitimo quando a nova tem um defeito. O que nao pode e acontecer sem
// que a pessoa saiba.
function InitializeSetup(): Boolean;
var
  Chave, Instalada, Aviso: String;
  Antiga, Nova: Int64;
begin
  Result := True;
  Chave := 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{#AppGuid}}_is1';
  if not RegQueryStringValue(HKA, Chave, 'DisplayVersion', Instalada) then
    Exit;
  if not (StrToVersion(Instalada, Antiga) and StrToVersion('{#AppVersion}', Nova)) then
    Exit;
  if ComparePackedVersion(Antiga, Nova) > 0 then
  begin
    // **Silencioso RECUSA, sem perguntar.** A primeira versao disto confiava no
    // `/SUPPRESSMSGBOXES` responder o botao padrao ("Nao"), e o ciclo mostrou
    // que ele responde SIM: a instalacao mais velha passava direto, em silencio,
    // que e justamente o caso de um atualizador automatico. Quem quiser voltar
    // de proposito roda o instalador sem `/SILENT` e responde a pergunta.
    if WizardSilent then
    begin
      Log('Recusado: a versao instalada (' + Instalada + ') e mais nova que a ' +
          'deste instalador ({#AppVersion}).');
      Result := False;
      Exit;
    end;
    // Nenhuma linha pode COMECAR com `#`: o preprocessador do Inno le a linha
    // como diretiva e o compile aborta com "Unknown preprocessor directive" —
    // apontando para uma linha de texto no meio de um `MsgBox`. Por isso as
    // quebras (`#13#10`) ficam sempre no fim da linha anterior.
    Aviso := 'Ja esta instalada a versao ' + Instalada + ', mais nova que a ' +
             '{#AppVersion} deste instalador.' + #13#10 + #13#10 +
             'Instalar por cima faz o programa voltar no tempo. Os seus dados ' +
             'nao serao tocados, mas a versao antiga pode nao entender um ' +
             'banco que a nova ja atualizou.' + #13#10 + #13#10 +
             'Continuar mesmo assim?';
    Result := MsgBox(Aviso, mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES;
  end;
end;

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
      // Numa desinstalacao silenciosa (`/VERYSILENT`, que e como um atualizador
      // ou um script chamam) nao ha ninguem para responder: o `MsgBox` ficaria
      // esperando um clique que nunca vem, e a desinstalacao travaria sem dizer
      // por que. Sem pergunta, a resposta e a conservadora — os dados ficam.
      if UninstallSilent then
        Exit;
      if MsgBox('Apagar tambem os seus dados?' + #13#10#13#10 +
                'Isto remove o glossario, o banco de traducoes, os backups e as ' +
                'configuracoes em:' + #13#10 + Dados + #13#10#13#10 +
                'Se voce for reinstalar o programa, responda Nao.',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(Dados, True, True, True);
    end;
  end;
end;
