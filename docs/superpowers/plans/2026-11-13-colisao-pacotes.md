# Publicação concorrente de pacotes

**Roadmap:** RG-000B e RG-031. Coordenar a escolha final de nomes entre
instâncias do aplicativo após a geração, sem bloquear o tempo de tradução.
Quando houver colisão, renomear o arquivo no diretório temporário e registrar
o nome correto no manifesto antes de publicar. Preservar o protocolo existente
de cancelamento, cópia de origem, hashes e remoção de temporários.

**Limite:** o bloqueio coordena apenas versões do programa que usam esse
protocolo; modificações externas na pasta não são serializadas.
