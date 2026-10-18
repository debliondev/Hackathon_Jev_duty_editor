# Atajos del proyecto. `make help` para ver todos.
PY ?= .venv/bin/python

.PHONY: help install datos test lint record eval eval-test barrido experimentos reporte ui api

help:
	@grep -E '^[a-z-]+:.*##' Makefile | awk -F':.*## ' '{printf "  make %-13s %s\n", $$1, $$2}'

install: ## Crea .venv e instala todo (incluye dev)
	python3 -m venv .venv && .venv/bin/pip install -q -e ".[dev]"

datos: ## Regenera el golden set sintético (determinista)
	$(PY) -m data.synthetic.generar_piezas

test: ## Tests (sin red)
	$(PY) -m pytest -q

lint: ## ruff + black
	.venv/bin/ruff check editor eval ui data tests && .venv/bin/black --check editor eval ui data tests

record: ## Graba respuestas reales de JEV para dev+test (EN) — necesita TYPESAFE_API_KEY
	JEV_MODE=record $(PY) -m eval.correr_eval --split dev
	JEV_MODE=record $(PY) -m eval.correr_eval --split test

eval: ## Eval en dev (modo de JEV según JEV_MODE; replay por defecto)
	$(PY) -m eval.correr_eval --split dev

eval-test: ## Eval en test (solo para reportar)
	$(PY) -m eval.correr_eval --split test

barrido: ## Barrido de umbrales sobre dev + curva PNG
	$(PY) -m eval.barrido_umbrales

experimentos: ## Permutación, idioma y adversarial (graba lo que falte si JEV_MODE=record)
	$(PY) -m eval.experimentos adversarial
	$(PY) -m eval.experimentos permutacion
	$(PY) -m eval.experimentos idioma

reporte: ## Regenera eval/reporte.md
	$(PY) -m eval.reporte

ui: ## Streamlit
	.venv/bin/streamlit run ui/app.py

api: ## FastAPI en http://localhost:8000/docs
	.venv/bin/uvicorn editor.api:app --reload
