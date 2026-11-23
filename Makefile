.DEFAULT_GOAL := help

SCENARIO ?= bad_deploy

.PHONY: help up break heal test investigate dashboard monitor seed-demo bad-deploy-demo

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

seed-demo:
	@python main.py seed-demo

bad-deploy-demo:
	@python scripts/bad_deploy_demo.py
