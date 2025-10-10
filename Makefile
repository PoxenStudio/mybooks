.PHONY: all build push test

VER := $(shell git branch --show-current)
IMAGE := poxenstudio/talebook:$(VER)
REPO1 := poxenstudio/talebook:latest
TAG1 := poxenstudio/talebook:server-side-render
TAG2 := poxenstudio/talebook:server-side-render-$(VER)
ARCH := $(shell uname -m)
PLATFORM ?= linux/$(shell if [ "$(ARCH)" = "x86_64" ]; then echo "amd64"; elif [ "$(ARCH)" = "aarch64" ] || [ "$(ARCH)" = "arm64" ]; then echo "arm64"; else echo "amd64"; fi)

$(info Building for platform: $(PLATFORM))
$(info Building image: $(IMAGE))
$(info Building tag1: $(TAG1))
$(info Building tag2: $(TAG2))


all: build up

build: test
	docker build --platform=$(PLATFORM) --no-cache=false --build-arg BUILD_COUNTRY=CN --build-arg GIT_VERSION=$(VER) \
		-f Dockerfile -t $(IMAGE) -t $(REPO1) --target production .
	docker build --platform=$(PLATFORM) --no-cache=false --build-arg BUILD_COUNTRY=CN --build-arg GIT_VERSION=$(VER) \
		-f Dockerfile -t $(TAG1) -t $(TAG2) --target production-ssr .

push:
	docker push $(IMAGE)
	docker push $(REPO1)

test: lint
	rm -f unittest.log
	docker build --platform=$(PLATFORM) --build-arg BUILD_COUNTRY=CN -t talebook/test --target test -f Dockerfile .
	docker run --rm --name=talebook-docker-test -v "$$PWD":"$$PWD" -w "$$PWD" talebook/test pytest --log-file=unittest.log --log-level=INFO tests

lint:
	flake8 webserver --count --select=E9,F63,F7,F82 --show-source --statistics --exclude epub_to_audio,test
	flake8 webserver --count --statistics --config .style.yapf --exclude epub_to_audio,test

pytest: lint
	pytest tests

testv:
	coverage run -m unittest
	coverage report --include "*talebook*"

testvv: testv
	coverage html -d ".htmlcov" --include "*talebook*"
	cd ".htmlcov" && python3 -m http.server 7777

up:
	docker compose up

down:
	docker compose stop
