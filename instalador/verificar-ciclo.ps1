# Ciclo do instalador: instalar -> usar -> atualizar por cima -> desinstalar.
# ROADMAP 21.4. Verifica as garantias I1 e I4, que sao do INSTALADOR e por isso
# nao cabem na suite de testes: elas so existem quando ha um `.exe` de instalacao
# de verdade rodando numa maquina de verdade.
#
#     powershell -ExecutionPolicy Bypass -File instalador\verificar-ciclo.ps1
#
# Pre-requisitos: `dist\PGN_Tradutor_Pro\` construido (PyInstaller) e o Inno
# Setup 6 instalado. O roteiro compila o instalador duas vezes — a segunda com
# outra versao, para simular uma atualizacao.
#
# ELE NAO RODA SE JA HOUVER DADOS. Uma pasta `%APPDATA%\PGN Tradutor Pro` com o
# acervo de verdade dentro nao pode servir de cobaia: o roteiro escreve nela e a
# desinstalacao do fim mexeria no que ele nao criou.

$ErrorActionPreference = 'Stop'
$raiz = Split-Path -Parent $PSScriptRoot
$iscc = Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'
$dados = Join-Path $env:APPDATA 'PGN Tradutor Pro'
$programa = Join-Path $env:LOCALAPPDATA 'Programs\PGN Tradutor Pro'
$saida = Join-Path $PSScriptRoot 'saida'
$falhas = @()

function Passo($texto) { Write-Host "`n== $texto" -ForegroundColor Cyan }
function Confere($descricao, $condicao) {
    if ($condicao) { Write-Host "   [ok]    $descricao" -ForegroundColor Green }
    else { Write-Host "   [FALHOU] $descricao" -ForegroundColor Red; $script:falhas += $descricao }
}

if (Test-Path $dados) {
    throw "Ja existe $dados. Este roteiro escreve nessa pasta e nao pode rodar sobre dados de verdade."
}
if (-not (Test-Path (Join-Path $raiz 'dist\PGN_Tradutor_Pro\PGN_Tradutor_Pro.exe'))) {
    throw "Falta o dist\. Rode: python -m PyInstaller PGN_Tradutor_Pro.spec"
}

Passo 'Compilando a versao do projeto'
# A versao sai do executavel, que a recebeu de `tradutor_pgn/__version__`
# (ROADMAP 21.6). O roteiro le a mesma coisa para saber que arquivo esperar.
$versao = (Get-Item (Join-Path $raiz 'dist\PGN_Tradutor_Pro\PGN_Tradutor_Pro.exe')).VersionInfo.ProductVersion
Write-Host "   versao do executavel: $versao"
& $iscc (Join-Path $PSScriptRoot 'PGN_Tradutor_Pro.iss') | Select-Object -Last 1
$instalador = Join-Path $saida "PGN-Tradutor-Pro-$versao-instalador.exe"
Confere 'o instalador saiu com a versao do executavel no nome' (Test-Path $instalador)

Passo 'Instalando (silencioso)'
Start-Process -FilePath $instalador -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait
Confere 'o programa foi instalado' (Test-Path (Join-Path $programa 'PGN_Tradutor_Pro.exe'))
Confere 'nenhum dado foi instalado junto' (-not (Test-Path (Join-Path $programa 'Substituicoes.txt')))

Passo 'Primeira execucao: a pasta de dados nasce'
$app = Start-Process -FilePath (Join-Path $programa 'PGN_Tradutor_Pro.exe') -PassThru
$glossario = Join-Path $dados 'Substituicoes.txt'
for ($i = 0; $i -lt 40 -and -not (Test-Path $glossario); $i++) { Start-Sleep -Milliseconds 750 }
Confere 'a pasta de dados foi criada em %APPDATA%' (Test-Path $dados)
Confere 'o glossario inicial foi instalado nela' (Test-Path $glossario)
Get-Process -Name 'PGN_Tradutor_Pro' -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 500

Passo 'Simulando o trabalho do usuario'
# Uma regra que so existe aqui: e ela que a atualizacao nao pode levar.
Add-Content -Path $glossario -Value "# marca do roteiro: nao pode sumir numa atualizacao" -Encoding utf8
$antes = (Get-FileHash $glossario).Hash
$marcador = Join-Path $dados 'traducoes.db'
Set-Content -Path $marcador -Value 'banco de mentira do roteiro' -Encoding utf8 -NoNewline
Write-Host "   glossario com $((Get-Content $glossario).Count) linhas, hash $($antes.Substring(0,12))..."

Passo 'Compilando uma versao mais nova e instalando POR CIMA'
# Sem copiar a receita: a versao vira parametro (`/DAppVersion`), que e o mesmo
# `#ifndef` que existe para este roteiro. Simular uma atualizacao deixou de
# exigir reconstruir o executavel.
$maisNova = '99.0.0'
& $iscc "/O$saida" "/DAppVersion=$maisNova" (Join-Path $PSScriptRoot 'PGN_Tradutor_Pro.iss') |
    Select-Object -Last 1
Start-Process -FilePath (Join-Path $saida "PGN-Tradutor-Pro-$maisNova-instalador.exe") `
    -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait

Confere 'I1: o glossario sobreviveu a atualizacao, byte a byte' ((Get-FileHash $glossario).Hash -eq $antes)
Confere 'I1: o banco sobreviveu a atualizacao' ((Get-Content $marcador -Raw) -eq 'banco de mentira do roteiro')
Confere 'o programa continua instalado' (Test-Path (Join-Path $programa 'PGN_Tradutor_Pro.exe'))

function VersaoInstalada {
    $chave = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{7C1D9F2E-5A64-4B7C-9E3D-1F2A6B8C4D50}_is1'
    (Get-ItemProperty -Path $chave -ErrorAction SilentlyContinue).DisplayVersion
}
Confere "o registro diz $maisNova" ((VersaoInstalada) -eq $maisNova)

Passo 'Tentando instalar a versao ANTERIOR por cima da mais nova'
# Numa instalacao silenciosa o instalador RECUSA sem perguntar. A primeira versao
# desta checagem supunha que `/SUPPRESSMSGBOXES` responderia o botao padrao
# ("Nao"), e ela reprovou: ele responde SIM, e a versao velha entrava em
# silencio. Hoje o `WizardSilent` decide antes de qualquer `MsgBox`.
$voltar = Start-Process -FilePath $instalador -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait -PassThru
Confere 'a instalacao mais velha foi recusada' ($voltar.ExitCode -ne 0)
Confere "a versao instalada continua $maisNova" ((VersaoInstalada) -eq $maisNova)
Confere 'I1: e o glossario segue intacto depois da recusa' ((Get-FileHash $glossario).Hash -eq $antes)

Passo 'Desinstalando (silencioso)'
$unins = Get-ChildItem $programa -Filter 'unins*.exe' | Select-Object -First 1
Start-Process -FilePath $unins.FullName -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait
Start-Sleep -Seconds 2
Confere 'o programa foi removido' (-not (Test-Path (Join-Path $programa 'PGN_Tradutor_Pro.exe')))
Confere 'I4: a pasta de dados sobreviveu a desinstalacao' (Test-Path $dados)
Confere 'I4: o glossario continua intacto' ((Get-FileHash $glossario).Hash -eq $antes)

Passo 'Limpando o que o roteiro criou'
Remove-Item $dados -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $saida "PGN-Tradutor-Pro-$maisNova-instalador.exe") -Force -ErrorAction SilentlyContinue
if (Test-Path $programa) { Remove-Item $programa -Recurse -Force -ErrorAction SilentlyContinue }

Write-Host ''
if ($falhas.Count -eq 0) { Write-Host 'CICLO COMPLETO: todas as checagens passaram.' -ForegroundColor Green }
else {
    Write-Host "CICLO COM $($falhas.Count) FALHA(S):" -ForegroundColor Red
    $falhas | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}
