.PHONY: install run generate link evaluate test lint sample clean

install:      ## instala o projeto e as dependências de desenvolvimento
	pip install -e ".[dev]"

run: generate ## fluxo completo: gerar as bases sintéticas

generate:     ## gera data/base_a.csv, data/base_b.csv e data/gabarito.csv
	rlk generate

test:         ## testes unitários e de ponta a ponta (amostra sintética)
	python -m pytest

lint:         ## verificação de estilo
	python -m ruff check .

sample:       ## regenera a amostra pequena usada nos testes (data/sample/)
	rlk generate --out data/sample --n-a 200 --n-b 120 --seed 7

clean:        ## apaga as saídas geradas (mantém data/sample/)
	rm -f data/*.csv reports/*.csv
