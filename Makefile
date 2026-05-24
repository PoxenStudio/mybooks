.PHONY: all build push test

VER := $(shell git branch --show-current)
IMAGE := poxenstudio/mybooks:$(VER)
REPO1 := poxenstudio/mybooks:latest
TAG1 := poxenstudio/mybooks:server-side-render
TAG2 := poxenstudio/mybooks:server-side-render-$(VER)
BASE_IMAGE := poxenstudio/mybooks_base:$(VER)
BASE_REPO1 := poxenstudio/mybooks_base:latest
BUILDER := shukubuilder
ARCH := $(shell uname -m)
PLATFORM ?= linux/$(shell if [ "$(ARCH)" = "x86_64" ]; then echo "amd64"; elif [ "$(ARCH)" = "aarch64" ] || [ "$(ARCH)" = "arm64" ]; then echo "arm64"; else echo "amd64"; fi)

$(info Building for platform: $(PLATFORM))
$(info Building image: $(IMAGE))
$(info Building tag1: $(TAG1))
$(info Building tag2: $(TAG2))


all: build up

build:
	docker build --pull --platform=$(PLATFORM) --no-cache=false --build-arg BUILD_COUNTRY=CN --build-arg GIT_VERSION=$(VER) \
		-f Dockerfile -t $(IMAGE) -t $(REPO1) --target production .

push:
	docker push $(IMAGE)
	docker push $(REPO1)

# 初始化多架构构建环境（Linux必须要运行一次），不要使用snap安装的docker
setup-multiarch:
	docker run --privileged --rm tonistiigi/binfmt --install all
	docker buildx create --use --name $(BUILDER) || docker buildx use $(BUILDER)
	docker buildx inspect $(BUILDER) --bootstrap


# 构建并推送基础镜像多架构版本（ubuntu + 系统包 + python依赖 + calibre补丁）
# 仅在 requirements.txt / calibre补丁 / 系统包变更时需重新构建
build-base-multiarch:
	docker buildx build --pull --platform=linux/amd64,linux/arm64 \
		--builder $(BUILDER) \
		--build-arg BUILD_COUNTRY=CN \
		-f Dockerfile.base -t $(BASE_IMAGE) -t $(BASE_REPO1) \
		--load .

# 构建并推送多架构镜像（同时支持 amd64 和 arm64）
build-multiarch:
	docker buildx build --pull --platform=linux/amd64,linux/arm64 \
		--builder $(BUILDER) \
		--build-arg BUILD_COUNTRY=CN --build-arg GIT_VERSION=$(VER) \
		-f Dockerfile -t $(IMAGE) -t $(REPO1) \
		--target production --push .

# 仅构建多架构镜像到本地缓存（不推送）
build-multiarch-local:
	docker buildx build --pull --platform=linux/amd64,linux/arm64 \
		--builder $(BUILDER) \
		--build-arg BUILD_COUNTRY=CN --build-arg GIT_VERSION=$(VER) \
		-f Dockerfile -t $(IMAGE) -t $(REPO1) \
		--target production --load .

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
