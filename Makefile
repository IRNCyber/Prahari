.DEFAULT_GOAL := help

SCENARIO ?= bad_deploy

.PHONY: help up break heal test investigate dashboard monitor

help:
	@python main.py --help

up:
	@docker compose up --build

break:
	@python main.py break --scenario $(SCENARIO)

heal:
	@python main.py heal

test:
	@python -m pytest -q

investigate:
	@python main.py investigate

dashboard:
	@python main.py dashboard

monitor:
	@python -m detector.watcher --url http://localhost:8000
