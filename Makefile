.PHONY: up down reset seed-demo seed-partner test test-unit test-integration \
        smoke gigachat-smoke qwen-smoke smtp-smoke

# --- Docker compose lifecycle ----------------------------------------------
up:
	cd infra && docker compose up -d --build

down:
	cd infra && docker compose down

reset:
	cd infra && docker compose down -v
	rm -rf backend/data

# --- Seed demo data ---------------------------------------------------------
seed-demo:
	cd infra && docker compose exec api python -m scripts.seed_demo $(SEED_ARGS)

# Seeds the shared "partner products" knowledge base into ChromaDB.
# Source docs are not bundled with this repo — see the companion dataset.
seed-partner:
	cd infra && docker compose exec api python -m scripts.seed_partner_products

# --- Tests ------------------------------------------------------------------
test:
	cd backend && uv run pytest tests/

test-unit:
	cd backend && uv run pytest tests/unit -v

test-integration:
	cd backend && uv run pytest tests/integration -v -m integration

# --- Health / external API smoke -------------------------------------------
smoke:
	curl -fsS http://localhost:8000/healthz | grep -q '"ok"' && echo "smoke OK" || (echo "smoke FAILED" && exit 1)

gigachat-smoke:
	bash scripts/gigachat-smoke.sh

qwen-smoke:
	bash scripts/qwen-smoke.sh

smtp-smoke: ## Send test email via configured SMTP. Usage: make smtp-smoke EMAIL=foo@example.com
	@test -n "$(EMAIL)" || (echo "Usage: make smtp-smoke EMAIL=<your-real-email>" && exit 1)
	@cd backend && python -m scripts.smtp_smoke "$(EMAIL)"
