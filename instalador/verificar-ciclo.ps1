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

Passo 'Compilando a versao 1.0.0'
& $iscc (Join-Path $PSScriptRoot 'PGN_Tradutor_Pro.iss') | Select-Object -Last 1
$instalador = Join-Path $saida 'PGN-Tradutor-Pro-1.0.0-instalador.exe'

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

Passo 'Compilando a versao 1.0.1 e instalando POR CIMA'
$iss = Get-Content (Join-Path $PSScriptRoot 'PGN_Tradutor_Pro.iss') -Raw
$novo = Join-Path $env:TEMP 'PGN_Tradutor_Pro-1.0.1.iss'
# A receita e copiada para o TEMP com a versao trocada: mexer no arquivo
# versionado para rodar um teste deixaria a arvore suja se o roteiro falhasse
# no meio.
$iss.Replace('#define AppVersion "1.0.0"', '#define AppVersion "1.0.1"') |
    Set-Content -Path $novo -Encoding utf8
# `/DDistDir` absoluto: a copia esta no TEMP, e o caminho relativo da receita
# ("..\dist\...") apontaria para fora dali. Foi assim que a primeira execucao
# deste roteiro morreu.
& $iscc "/O$saida" "/DDistDir=$(Join-Path $raiz 'dist\PGN_Tradutor_Pro')" $novo |
    Select-Object -Last 1
Start-Process -FilePath (Join-Path $saida 'PGN-Tradutor-Pro-1.0.1-instalador.exe') `
    -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait

Confere 'I1: o glossario sobreviveu a atualizacao, byte a byte' ((Get-FileHash $glossario).Hash -eq $antes)
Confere 'I1: o banco sobreviveu a atualizacao' ((Get-Content $marcador -Raw) -eq 'banco de mentira do roteiro')
$versao = (Get-Item (Join-Path $programa 'unins000.exe') -ErrorAction SilentlyContinue)
Confere 'o programa continua instalado' (Test-Path (Join-Path $programa 'PGN_Tradutor_Pro.exe'))

Passo 'Desinstalando (silencioso)'
$unins = Get-ChildItem $programa -Filter 'unins*.exe' | Select-Object -First 1
Start-Process -FilePath $unins.FullName -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait
Start-Sleep -Seconds 2
Confere 'o programa foi removido' (-not (Test-Path (Join-Path $programa 'PGN_Tradutor_Pro.exe')))
Confere 'I4: a pasta de dados sobreviveu a desinstalacao' (Test-Path $dados)
Confere 'I4: o glossario continua intacto' ((Get-FileHash $glossario).Hash -eq $antes)

Passo 'Limpando o que o roteiro criou'
Remove-Item $dados -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $novo -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $saida 'PGN-Tradutor-Pro-1.0.1-instalador.exe') -Force -ErrorAction SilentlyContinue
if (Test-Path $programa) { Remove-Item $programa -Recurse -Force -ErrorAction SilentlyContinue }

Write-Host ''
if ($falhas.Count -eq 0) { Write-Host 'CICLO COMPLETO: todas as checagens passaram.' -ForegroundColor Green }
else {
    Write-Host "CICLO COM $($falhas.Count) FALHA(S):" -ForegroundColor Red
    $falhas | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}
