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
registra as contagens e hashes. A medição usou um protótipo ortográfico que foi
posteriormente rejeitado por gerar sugestões incorretas; os números não são
resultado da versão atual. A amostra é pequena e não comprova equivalência geral.

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
O [ZIP portátil oficial 5.38.2.2-64bit](https://github.com/StrawberryPerl/Perl-Dist-Strawberry/releases/download/SP_53822_64bit/strawberry-perl-5.38.2.2-64bit-portable.zip)
foi baixado e teve SHA-256 `ea451686065d6338d7e4d4a04c9af49f17951d15aa4c9ef2e19ab8cb56fa2373440`.
Uma [comparação reproduzível](task-8-toolchain-identity-2026-11-05.json), com
`task-8-compare-toolchain-2026-11-05.py`, encontrou os mesmos hashes nos nove
membros verificados: o compilador e oito arquivos estáticos ou de importação
observados no mapa de ligação. Isso identifica os bytes desses membros, mas
não identifica as revisões de fontes, patches ou todos os avisos aplicáveis.

A [receita Strawberry da versão fixada](https://github.com/StrawberryPerl/Perl-Dist-Strawberry/blob/SP_53822_64bit/share/64bit-5.38.2.2.pp)
aponta para o [pacote de ferramenta gcc13.1r5](https://github.com/StrawberryPerl/build-extlibs/releases/tag/dev_gcc13.1_20230606).
O ZIP `winlibs_gcc13.1r5_sans_make.zip` dessa página teve SHA-256
`e51e16e7cd70d4b644a44929ac8dfd1d2d13690e323e235aa6556f3c12774298`;
os [mesmos nove membros coincidem](task-8-winlibs-identity-2026-11-05.json)
com a instalação usada na compilação. A página descreve a origem como WinLibs
GCC 13.1 release 5, mas a identidade desses bytes com uma variante exata da
distribuição original WinLibs ainda não havia sido demonstrada.

Em seguida, o [pacote WinLibs x86_64 POSIX MSVCRT release 5](https://github.com/brechtsanders/winlibs_mingw/releases/tag/13.1.0-16.0.5-11.0.0-msvcrt-r5)
foi baixado; seu SHA-256 `2dfc45f33bef4e598219c7d31d598c24eca08ab80b6a54d9fbe0bb10471fd239`
confere com o arquivo `.sha256` disponibilizado na mesma release. A
[comparação](task-8-upstream-winlibs-identity-2026-11-05.json) encontrou
identidade nos mesmos nove membros. O ZIP não continha arquivos com nomes
`COPYING.RUNTIME`, `COPYING.MinGW-w64-runtime` ou `COPYING.winpthreads`, nem
diretório `/src/`; essa busca por nomes não garante ausência de outros avisos.
Identidade de binários continua distinta de fonte correspondente e cumprimento
dos termos de licença.

Como ponto de partida para essa conferência, as tags oficiais
[`releases/gcc-13.1.0`](https://github.com/gcc-mirror/gcc/tree/cc035c5d8672f87dc8c2756d9f8367903aa72d93)
e [`mingw-w64 v11.0.0`](https://github.com/mingw-w64/mingw-w64/tree/f9500e2d85b9400c0982518663660a127e1dc61a)
resolvem, respectivamente, aos commits `cc035c5d8672f87dc8c2756d9f8367903aa72d93`
e `f9500e2d85b9400c0982518663660a127e1dc61a`. As versões são compatíveis com a
descrição da release, mas não foi provado que esses commits e os respectivos
patches produzam os objetos do pacote. São candidatos de investigação, não
fontes correspondentes aprovadas.

Foram localizadas também versões anteriores à data da release das receitas
WinLibs de [GCC](https://github.com/brechtsanders/winlibs_recipes/blob/5ac8cf5ddee0371949ce55eab19b2ee767fbcd4d/recipes/gcc.winlib)
e [MinGW-w64](https://github.com/brechtsanders/winlibs_recipes/blob/5ac8cf5ddee0371949ce55eab19b2ee767fbcd4d/recipes/mingw-w64.winlib).
A segunda declara a versão 11.0.0 e contém patches para `winpthreads` e CRT;
a receita GCC também contém patches. Essas receitas são evidência adicional
de possíveis alterações em relação às fontes upstream, não prova de que o
pacote foi produzido exatamente com esse commit. É necessário estabelecer a
relação com o build release 5 e preservar a fonte e os patches correspondentes.

Os artefatos experimentais permanecem locais e fora de controle de versão.
Antes de qualquer entrega, ainda é necessário revisar todas as fontes, versões,
licenças e avisos, inclusive dos componentes estáticos GCC/MinGW e dependências
transitivas, comprovar os arquivos que integram o candidato final, revalidar o
SBOM e executar o smoke do instalador e pacote portátil. O manifesto de aprovação
permanece bloqueado.
