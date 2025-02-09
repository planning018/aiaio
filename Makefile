.PHONY: quality style test

quality:
	black --check --line-length 119 --target-version py310 .
	isort --check-only .
	flake8 --max-line-length 119

style:
	black --line-length 119 --target-version py310 .
	isort .

test:
	pytest -sv ./src/

pip:
	rm -rf build/
	rm -rf dist/
	make style && make quality
	python -m build
	twine upload dist/* --verbose

docker-build:
	docker build -t aiaio .

docker-run:
	docker run --network=host -it --rm aiaio