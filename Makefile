.DEFAULT_GOAL := build
.PHONY: build deploy

build:
	git submodule update --init --recursive
	docker compose run --rm --no-deps hugo-build
	test -s public/index.html
	test -s public/keys/index.html

deploy: build
	docker compose up -d --force-recreate onderka-site
