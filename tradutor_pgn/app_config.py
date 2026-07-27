LANGUAGE_OUTPUT_SUFFIXES = {
    "pt": "BR",
    "en": "EN",
    "es": "ES",
    "fr": "FR",
    "de": "DE",
    "it": "IT",
    "ru": "RU",
}

MAX_TRANSLATE_CHARS = 5000

# Intervalo normal entre requisicoes de traducao. Baixo de proposito: rende mais.
# O preco e mais chance de 429, e o retry sozinho nao e defesa contra isso —
# esgotadas as tentativas o comentario falha do mesmo jeito. Por isso o intervalo
# nao e fixo: `RequestPacer` multiplica este valor quando a API reclama e volta a
# reduzi-lo depois de uma sequencia limpa (ROADMAP 7.2).
TRANSLATION_REQUEST_DELAY_SECONDS = (0.04, 0.12)

# O ritmo sobe rapido e desce devagar, de proposito. O custo de insistir rapido
# demais e um comentario perdido depois de tres tentativas; o custo de esperar
# demais e so tempo. A assimetria e a escolha entre os dois.
PACE_FIRST_MULTIPLIER = 6.0   # o primeiro 429 ja tira o ritmo do piso
PACE_GROWTH = 5.0             # cada 429 seguinte multiplica de novo
PACE_MAX_MULTIPLIER = 60.0    # teto: ~2,4 a 7,2 s entre requisicoes
PACE_DECAY = 0.5              # a recuperacao e pela metade, nao de volta ao piso
PACE_CLEAN_STREAK = 25        # ...e so depois de 25 requisicoes sem reclamacao

# Retencao de `backups/`. O limite do glossario e maior porque cada copia e um
# arquivo texto (~334 KB) e a gravacao e frequente; a do banco e o banco
# inteiro, entao guarda-se menos. Ver `backup_retention.py`.
GLOSSARY_BACKUP_KEEP_COUNT = 30
DATABASE_BACKUP_KEEP_COUNT = 10
BACKUP_MAX_AGE_DAYS = 60
# Piso: nunca descartar por idade os N mais novos, para que uma pasta parada
# por meses nao fique sem backup nenhum.
BACKUP_KEEP_MINIMUM = 3

# Retencao de `logs/`. Cada execucao de traducao gera um arquivo (~200 KB), e
# ate agora nada os removia. O limite e generoso porque um log e barato e serve
# justamente para investigar uma execucao antiga.
LOG_KEEP_COUNT = 50
LOG_MAX_AGE_DAYS = 90
