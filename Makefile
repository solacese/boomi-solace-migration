.PHONY: install check lint type test schema-fixtures

install:
	python3 -m pip install -e ".[dev]" -c requirements-dev.lock

lint:
	python3 -m ruff check .

type:
	python3 -m mypy src

test:
	python3 -m pytest

schema-fixtures:
	python3 -m boomi_solace_migration.cli validate --config examples/migration.example.yaml --connector-profile examples/connector-profile.example.yaml --naming-policy examples/naming-policy.example.yaml --offline-only

check: lint type test schema-fixtures
