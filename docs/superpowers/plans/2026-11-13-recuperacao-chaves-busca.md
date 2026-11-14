# Recuperação, chaves e busca

**Roadmap:** RG-003, RG-031 e RG-051.

- Identificar a origem real da credencial e explicar a proteção disponível.
- Não revelar credenciais curtas nem sobrescrever um arquivo de chaves ilegível.
- Sincronizar atualizações de chaves entre instâncias e publicar por temporário
  exclusivo; avisar quando a gravação das configurações puder ser parcial.
- Reconhecer configurações com BOM, tratar JSON aninhado e preservar backups
  de configurações corrompidas com nomes distintos.
- Permitir busca na biblioteca por termos sem acento, em qualquer ordem e em
  campos diferentes, mantendo os filtros existentes.
- Verificar comportamento em diretórios temporários, concorrência e cópia
  integrada, sem tocar nos dados reais do usuário.
