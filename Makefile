install:
	python -m pip install -e .[dev]

infra:
	docker compose up -d

migrate:
	alembic upgrade head

seed:
	python -m scripts.seed

test:
	pytest -q

audit:
	python scripts/audit.py

dashboard:
	uvicorn app.dashboard.main:app --reload

bot:
	python main.py
