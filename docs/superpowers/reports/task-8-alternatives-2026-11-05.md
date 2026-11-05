# Alternativas experimentais para distribuição — 2026-11-05

Estado: investigação local; **a distribuição continua bloqueada**. Nenhum
binário ou licença foi aprovado por este relatório.

Foi construído em `build/task8-neutral-frequency-2026-11-05/` um candidato de
dicionários portugueses com frequências uniformes, sem as listas Gaia. O probe
`task-8-neutral-replay-2026-11-05.py` registra o procedimento. A enumeração
dos autômatos apontou o mesmo conjunto de palavras dos dicionários anteriores;
isso não garante a mesma ordem de sugestões. No corpus sintético inalterado de
18 casos, os dois candidatos produziram 10 acertos, nenhum falso positivo e um
erro não detectado, conforme `corpus-comparison.json`. A amostra é pequena e
não comprova equivalência geral.

Uma segunda experiência compilou para Windows um candidato Hunspell a partir
da revisão `1180421f50f211984211e968eb6801ffd3390b8f`. O comando e seus
resultados estão em `native-build.json` e `native-repro.json` no mesmo diretório
local; o probe `task-8-hunspell-rebuild-probe-2026-11-05.py` registra a
investigação. O DLL inicial teve SHA-256
`cd37b304e3b6b757122efc107041a6f5d2d82297f660070cff471e50d55cc34d`.
Carregamento e consultas de exemplo foram exercitados via JNA. Esses resultados
não estabelecem equivalência ao binário anterior nem conformidade de distribuição.

A documentação do [libstdc++ do GCC](https://gcc.gnu.org/onlinedocs/libstdc%2B%2B/manual/license.html)
descreve GPLv3 com a exceção de runtime do GCC para o código da biblioteca.
Essa declaração geral não identifica, por si só, os objetos específicos
incorporados ao DLL experimental, suas fontes correspondentes ou os termos dos
outros componentes estáticos. Essas associações ainda precisam de auditoria.

Os artefatos experimentais permanecem locais e fora de controle de versão.
Antes de qualquer entrega, ainda é necessário revisar todas as fontes, versões,
licenças e avisos, inclusive dos componentes estáticos GCC/MinGW e dependências
transitivas, comprovar os arquivos que integram o candidato final, revalidar o
SBOM e executar o smoke do instalador e pacote portátil. O manifesto de aprovação
permanece bloqueado.
