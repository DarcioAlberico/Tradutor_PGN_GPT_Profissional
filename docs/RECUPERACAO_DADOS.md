# Backup e recuperação dos dados

Este roteiro protege o acervo de traduções, o glossário, as configurações e os
arquivos de saída. A verificação ajuda a identificar problemas, mas não substitui
um backup nem garante que todos os documentos e traduções estejam corretos.

## Localize seus dados

A pasta de dados depende do modo de execução, nesta ordem:

| Modo | Pasta de dados |
|---|---|
| Variável `PGN_TRADUTOR_DATA` definida | A pasta indicada pela variável, que prevalece sobre os demais modos |
| Executável portátil, com `portatil.txt` ao lado | Pasta `dados` dentro da pasta do programa |
| Executável instalado | `%APPDATA%\PGN Tradutor Pro` |
| Execução pelo código-fonte | Pasta do script `PGN_Tradutor_Pro.py` |

Confirme o caminho realmente usado antes de copiar ou restaurar. O atalho de
uma instalação pode definir uma pasta diferente. Saídas escolhidas manualmente
fora de `Minhas Traduções` e PGNs de origem em outras pastas precisam ser
incluídos no backup separadamente.

## Faça uma cópia completa

O arquivo `pgn_tradutor_pro_settings.json.lock` coordena a gravação das
configurações entre instâncias atualizadas. Não o remova enquanto o programa
estiver aberto. Versões antigas não usam esse bloqueio; evite que elas gravem
na mesma pasta ao mesmo tempo que a versão atual.

1. Termine ou cancele as operações em andamento, feche todas as janelas e
   instâncias do Tradutor e aguarde seu encerramento. Feche também qualquer
   outro programa que esteja usando os bancos.
2. Copie a **pasta de dados inteira** para outro local ou dispositivo, sem
   apagar a original. Inclua `traducoes.db`, `glossario-v2.db`,
   `Substituicoes.txt`, `pgn_tradutor_pro_settings.json`, `chaves-api.json`,
   `backups`, `Minhas Traduções` e os demais arquivos e subpastas existentes.
   Alguns podem não existir em instalações que ainda não usaram esses recursos.
3. Copie também os arquivos originais e resultados mantidos fora dessa pasta.
   Confira se a cópia foi concluída e guarde pelo menos uma versão anterior em
   outro dispositivo. A retenção automática da pasta `backups` não substitui
   uma cópia externa.
4. Teste periodicamente a restauração em uma pasta separada, como descrito
   abaixo, mantendo o backup original intacto.

Os bancos SQLite podem ter arquivos auxiliares `-wal` e `-shm`. Transações
confirmadas podem estar no WAL e ainda não no arquivo `.db`. Nunca considere
segura uma cópia apenas do `.db` enquanto houver acesso ao banco, nem apague
ou separe esses arquivos para forçar uma recuperação. Feche os processos e
copie a pasta inteira, inclusive os auxiliares que ainda existirem. Se não for
possível interromper o uso, as funções de backup do banco e do glossário usam a
API de backup do SQLite para obter uma cópia consistente de cada banco; elas
não garantem, por si só, uma fotografia simultânea dos dois bancos, das
configurações e dos PGNs.

O backup do banco de traduções pode ser criado pela ferramenta de backup do
programa. No editor de glossário, **Backup** cria um backup SQLite V2 do
catálogo. Anote os locais mostrados pelo aplicativo e copie-os para fora da
máquina. Proteja os backups: comentários, caminhos, configurações e credenciais
podem conter informações privadas. Não envie o acervo ou o arquivo de chaves em
um chamado de suporte sem antes avaliar seu conteúdo.

## Verifique os dados

Em **Ferramentas**, escolha **Verificar meus dados**. A verificação faz cópias
temporárias dos bancos para análise e apresenta resultados agregados, sem
incluir o conteúdo das traduções no relatório. Leia os avisos: um banco em uso
ou com WAL pode mudar durante a cópia; portanto, para avaliar um acervo fechado,
prefira executar a verificação sobre uma cópia feita com o programa encerrado.
Uma verificação aprovada identifica as condições testadas, não prova que um
backup seja completo ou recuperável em todos os cenários.

## Ensaie a restauração sem substituir seu acervo

1. Preserve a cópia original do backup e faça outra cópia dela em uma pasta
   vazia de teste. Não copie por cima da pasta de dados atual.
2. Na máquina de destino, use uma versão compatível do programa e aponte
   temporariamente `PGN_TRADUTOR_DATA` para essa pasta de teste antes de abrir
   o aplicativo. Confira a variável e o caminho configurado antes de iniciar.
   Não use a pasta de produção para esse ensaio.
3. Verifique o acervo e confira no programa algumas traduções, entradas e
   escopos do glossário, configurações e rascunhos. Abra amostras de PGNs
   originais e traduzidos da cópia em `Minhas Traduções` e de eventuais pastas
   externas. Se houver divergência, preserve todas as cópias para investigação.
4. Feche o programa ao terminar. Para uma restauração definitiva, primeiro
   faça uma cópia independente do acervo de destino e escolha uma pasta de
   destino vazia; só passe a usá-la depois de conferir o resultado. Não faça
   substituição parcial de arquivos de um banco em uso.

Por exemplo, ao executar pelo código-fonte no PowerShell, abra um terminal na
pasta do projeto e use o caminho da **cópia de teste**:

```powershell
$env:PGN_TRADUTOR_DATA = 'C:\caminho\para\copia-de-teste'
python .\PGN_Tradutor_Pro.py
Remove-Item Env:PGN_TRADUTOR_DATA
```

Substitua o caminho pelo seu antes de executar. A variável vale nesse terminal
e nos processos iniciados por ele; removê-la depois evita reutilizar o caminho
por engano em outra execução. O aplicativo pode atualizar dados e executar sua
retenção normal na pasta de teste: nunca aponte o ensaio para o único backup.

Para recuperar **apenas o banco de traduções**, a função **Restaurar Banco de
Dados** pede confirmação, cria um backup de segurança do banco atual e o
substitui. Para o glossário, **Restaurar backup** no editor aceita um backup
SQLite V2 validado, cria backup de segurança e substitui o catálogo. Confira o
arquivo selecionado e guarde as cópias de segurança. CSV é importação, não
restauração integral. Backups do glossário anterior à migração não são backups
V2 restauráveis por esse comando. `Substituicoes.txt` é um espelho legado; não
substitua o catálogo V2 por esse arquivo nem descarte possíveis alterações
externas sem revisão.

## Chaves de API em outra máquina

No Windows, as chaves gravadas em `chaves-api.json` usam DPAPI da conta e da
máquina originais. Em outra conta ou máquina, elas podem não ser decifráveis:
cadastre novamente as chaves necessárias nas configurações, sem publicar nem
compartilhar o arquivo. Variáveis de ambiente de chaves, quando usadas,
precisam ser configuradas novamente. Fora do Windows o arquivo pode guardar
valores apenas codificados, legíveis por quem o abrir; trate-o como segredo.
O acervo de traduções e o glossário devem ser verificados independentemente da
disponibilidade dessas chaves.
