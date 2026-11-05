.PHONY: install run generate link pseudo evaluate test lint sample clean

install:      ## instala o projeto e as dependências de desenvolvimento
	pip install -e ".[dev]"

run: generate link pseudo evaluate ## fluxo completo: gerar, cruzar, pseudonimizar e avaliar

generate:     ## gera data/base_a.csv, data/base_b.csv e data/gabarito.csv
	rlk generate

link:         ## padroniza, bloca, compara, pontua e classifica (saídas em reports/)
	rlk link --config config/default.yaml

# Sem RLK_SALT definido, gera um sal efêmero só para esta execução (demonstração). Ele não é
# gravado em lugar nenhum. Num cruzamento real, as duas organizações combinam o sal fora do Git.
pseudo:       ## cruzamento por hashes SHA-256 com sal secreto (RLK_SALT)
	@RLK_SALT="$${RLK_SALT:-$$(python -c 'import secrets; print(secrets.token_hex(32))')}" \
		rlk pseudo --config config/default.yaml

evaluate:     ## métricas contra o gabarito e relatório (reports/relatorio.html)
	rlk evaluate --config config/default.yaml

test:         ## testes unitários e de ponta a ponta (amostra sintética)
	python -m pytest

lint:         ## verificação de estilo
	python -m ruff check .

sample:       ## regenera a amostra pequena usada nos testes (data/sample/)
	rlk generate --out data/sample --n-a 200 --n-b 120 --seed 7

clean:        ## apaga as saídas geradas (mantém data/sample/ e o relatório versionado)
	rm -f data/*.csv reports/*.csv reports/pseudonimizado/*.csv reports/pseudo_metricas.json
