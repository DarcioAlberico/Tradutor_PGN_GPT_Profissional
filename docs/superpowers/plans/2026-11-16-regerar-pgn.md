# Regerar PGN com correções salvas

**Objetivo:** produzir uma nova versão de um pacote a partir das traduções salvas no banco, sem consultar provedores nem sobrescrever versões anteriores.

**Segurança:** usar o original do pacote validado e vínculo confiável; recusar a geração se faltar tradução, informando quantos comentários precisam ser resolvidos; preservar opções de saída e dados existentes. As leituras do banco são feitas em snapshot; a publicação usa o protocolo transacional existente.

**Interface:** botão na Biblioteca, trabalho em segundo plano com cancelamento, resultado e aviso de comentários ausentes, atualização da lista.

**Testes:** correção salva, par de idiomas, comentários ausentes, integridade, cancelamento, ausência de chamadas de rede e preservação dos pacotes anteriores.
