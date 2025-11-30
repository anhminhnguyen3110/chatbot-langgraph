.PHONY: help install dev-install setup-hooks format lint type-check security test test-cov clean run ci-check

help:
	@echo "Available commands:"
	@echo "  make install       - Install production dependencies"
	@echo "  make dev-install   - Install dev dependencies + git hooks"
	@echo "  make setup-hooks   - Reinstall git hooks (if needed)"
	@echo "  make format        - Format code with ruff"
	@echo "  make lint          - Lint code with ruff"
	@echo "  make type-check    - Run mypy type checking"
	@echo "  make security      - Run security checks with bandit"
	@echo "  make test          - Run all tests"
	@echo "  make test-unit     - Run only unit tests"
	@echo "  make test-integration - Run only integration tests"
	@echo "  make test-e2e      - Run only e2e tests"
	@echo "  make test-background - Run background task tests"
	@echo "  make test-cov      - Run tests with coverage"
	@echo "  make docker-build  - Build Docker image"
	@echo "  make docker-test   - Run e2e tests in Docker"
	@echo "  make ci-check      - Run all CI checks locally"
	@echo "  make clean         - Clean cache files"
	@echo "  make run           - Run the server"

install:
	uv sync --no-dev

dev-install:
	uv sync
	@uv run pre-commit install
	@uv run pre-commit install --hook-type commit-msg
	@echo ""
	@echo "✅ Dependencies installed!"
	@echo "✅ Git hooks installed!"
	@echo "🚀 You're ready to develop!"

setup-hooks:
	uv run pre-commit install
	uv run pre-commit install --hook-type commit-msg
	@echo ""
	@echo "✅ Git hooks reinstalled!"
	@echo "📝 Your commits will now be checked automatically"

format:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff check .

type-check:
	uv run mypy src/

security:
	uv run bandit -c pyproject.toml -r src/

test:
	uv run pytest

test-unit:
	uv run pytest -m unit -v

test-integration:
	uv run pytest -m integration -v

test-e2e:
	uv run pytest -m e2e -v

test-background:
	uv run pytest -m background_task -v

test-cov:
	uv run pytest --cov=src --cov-report=html --cov-report=term

docker-build:
	docker build -t aegra:latest -f deployments/docker/Dockerfile .

docker-test:
	docker-compose -f docker-compose.yml up -d postgres
	sleep 5
	docker-compose -f docker-compose.yml run --rm agent pytest -m e2e
	docker-compose -f docker-compose.yml down

ci-check: format lint type-check security test
	@echo ""
	@echo "✅ All CI checks passed!"

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov 2>/dev/null || true

run:
	uv run python run_server.py
