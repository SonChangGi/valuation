.PHONY: generate-data validate test build serve

generate-data:
	npm run generate-data

validate:
	python scripts/validate_data.py --data-dir docs/data --check-static

test:
	npm test

build:
	npm run build

serve:
	npm run serve
