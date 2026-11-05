# Alternativas experimentais para distribuição — 2026-11-05

Estado: investigação local; **a distribuição continua bloqueada**. Nenhum
binário ou licença foi aprovado por este relatório.

Foi construído em `build/task8-neutral-frequency-2026-11-05/` um candidato de
dicionários portugueses com frequências uniformes, sem as listas Gaia. O probe
`task-8-neutral-replay-2026-11-05.py` registra o procedimento. A enumeração
dos autômatos apontou o mesmo conjunto de palavras dos dicionários anteriores;
isso não garante a mesma ordem de sugestões. No corpus sintético inalterado de
18 casos, os dois candidatos produziram 10 acertos, nenhum falso positivo e um
erro não detectado, conforme a [comparação do corpus](task-8-neutral-corpus-comparison-2026-11-05.json).
A [comparação dos conjuntos](task-8-neutral-word-equivalence-2026-11-05.json)
registra as contagens e hashes. A amostra é pequena e não comprova equivalência geral.

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
O [guia de licenciamento MinGW-w64](https://github.com/mingw-w64/mingw-w64/blob/master/COPYING.MinGW-w64/COPYING.MinGW-w64.txt)
remete a avisos específicos do runtime, mas o documento da branch atual não
identifica automaticamente a versão usada pelo compilador local. É necessário
fixar a revisão exata e conferir os objetos e avisos correspondentes.

O `README.txt` do ambiente de compilação local identifica Strawberry Perl
5.38.2.2-64bit. A [nota oficial dessa versão](https://strawberryperl.com/release-notes/5.38.2.2-64bit.html)
descreve GCC 13.1.0 com configuração compatível com a observada localmente.
Os SHA-256 observados de `g++.exe` e `libstdc++.a` são, respectivamente,
`5184372df96eaf7e93428f2eb1451b5af8bde6eddbd44878295db51f520e5bc7` e
`1e29d6fc6affeb3b0c67036ad82ba0f428f7a0e422ec4a4768ed8045a8ea3a0c`.
Essa correspondência de versão e configuração não é uma comparação dos bytes
com a distribuição oficial nem identifica as revisões das fontes e patches.

Os artefatos experimentais permanecem locais e fora de controle de versão.
Antes de qualquer entrega, ainda é necessário revisar todas as fontes, versões,
licenças e avisos, inclusive dos componentes estáticos GCC/MinGW e dependências
transitivas, comprovar os arquivos que integram o candidato final, revalidar o
SBOM e executar o smoke do instalador e pacote portátil. O manifesto de aprovação
permanece bloqueado.
