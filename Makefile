.PHONY: sync test pack-test lint fmt schema schema-check clean

sync:
	uv sync --all-extras

test:                       ## 모델 호출 0회로 전부 돈다
	uv run pytest
	uv run policypack test --strict

pack-test:                  ## 정책 팩 픽스처. 대안마다 혼자 푸는 픽스처·정적 대안마다 음성 픽스처가 없으면 실패
	uv run policypack test --strict

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff format .
	uv run ruff check --fix .

schema:                     ## pydantic 모델에서 JSON Schema 를 다시 만든다(모델에 없는 옛 파일은 지운다)
	uv run policypack schema --write

schema-check:               ## 커밋된 schemas/ 와 모델이 어긋나거나 모델에 없는 파일이 있으면 실패
	uv run policypack schema --check

clean:
	rm -rf .pytest_cache .ruff_cache dist build
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
