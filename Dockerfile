
# ----------------------------------------
# 第一阶段，拉取 node 基础镜像并安装依赖，执行构建
FROM docker.1ms.run/library/node:16-alpine AS builder
ARG BUILD_COUNTRY=""

WORKDIR /build
RUN if [ "x${BUILD_COUNTRY}" = "xCN" ]; then \
    echo "using repo mirrors for ${BUILD_COUNTRY}"; \
    npm config set registry https://registry.npmmirror.com; \
    fi

COPY app/package.json app/package-lock.json* ./
RUN npm install

# spa build mode will clear ssr build data, run it first
COPY app/ /build/
RUN mkdir -p /app-ssr/ /app-static/ && \
    npm run build && \
    ls -al && \
    cp -r .nuxt node_modules package* /app-ssr/ && \
    npm run build-spa && \
    cp -r dist nuxt.config.js package* /app-static/

# ----------------------------------------
# 第二阶段，构建环境（基于预构建的基础镜像，含系统包、python依赖及calibre补丁）
# 基础镜像构建：make build-base-multiarch

# ----------------------------------------
# 测试阶段 (--break-system-packages)
FROM docker.1ms.run/poxenstudio/mybooks_base:latest AS test
RUN pip install flake8 pytest --break-system-packages
COPY webserver/ /var/www/talebook/webserver/
COPY tests/ /var/www/talebook/tests/
CMD ["pytest", "/var/www/talebook/tests"]

# ----------------------------------------
# 生产环境
FROM docker.1ms.run/poxenstudio/mybooks_base:latest AS production
ARG BUILD_COUNTRY="CN"
ARG GIT_VERSION=""

LABEL Author="horky <horky.chen@gmail.com>"
LABEL Thanks="Rex <talebook@foxmail.com>, oldiy <oldiy2018@gmail.com>"
LABEL org.opencontainers.image.title="mybooks" \
      org.opencontainers.image.vendor="PoxenStudio" \
      org.opencontainers.image.source="https://github.com/PoxenStudio/mybooks"

# set default language
ENV TZ=Asia/Shanghai
ENV LANG=C.UTF-8
ENV PUID=1000
ENV PGID=1000


# prepare dirs
RUN mkdir -p /data/log/nginx/ && \
    mkdir -p /data/books/library  && \
    mkdir -p /data/books/extract  && \
    mkdir -p /data/books/upload  && \
    mkdir -p /data/books/imports  && \
    mkdir -p /data/books/convert  && \
    mkdir -p /data/books/progress  && \
    mkdir -p /data/books/settings && \
    mkdir -p /data/books/logo && \
    mkdir -p /data/books/avatar && \
    mkdir -p /data/books/audios && \
    mkdir -p /data/books/ssl && \
    mkdir -p /var/www/talebook/ && \
    chmod a+w -R /data/log /data/books /var/www

COPY server.py /var/www/talebook/
COPY docker/ /var/www/talebook/docker/
COPY webserver/ /var/www/talebook/webserver/
COPY conf/nginx/ssl.* /data/books/ssl/
COPY conf/nginx/talebook.conf /etc/nginx/conf.d/
COPY conf/supervisor/talebook.conf /etc/supervisor/conf.d/
COPY --from=builder /app-static/ /var/www/talebook/app/
COPY --from=builder /app-static/dist/logo/ /data/books/logo/
COPY --from=builder /app-static/dist/avatar/ /data/books/avatar/
COPY release_notes.txt /var/www/talebook/app/dist/static/


RUN rm -f /etc/nginx/conf.d/default.conf /var/www/html -rf && \
    cd /var/www/talebook/ && \
    ln -snf /usr/share/zoneinfo/${TZ} /etc/localtime && \
    echo ${TZ} > /etc/timezone && \
    echo "VERSION = \"$GIT_VERSION\"" > webserver/version.py && \
    echo 'settings = {}' > /data/books/settings/auto.py && \
    chmod a+w /data/books/settings/auto.py && \
    calibredb add --library-path=/data/books/library/ -r docker/book/ && \
    python3 server.py --syncdb  && \
    python3 server.py --update-config  && \
    find webserver -name "*.pyc" -type f -delete && \
    rm -rf app/src && \
    rm -rf app/dist/logo && \
    ln -s /data/books/logo app/dist/logo && \
    rm -rf app/dist/avatar && \
    ln -s /data/books/avatar app/dist/avatar && \
    ln -s /data/books/audios app/dist/audios && \
    mkdir -p /prebuilt/ && \
    mv /data/* /prebuilt/ && \
    chmod +x /var/www/talebook/docker/start.sh

EXPOSE 80 443

VOLUME ["/data"]

CMD ["/var/www/talebook/docker/start.sh"]

# ----------------------------------------
# 生产环境（server side render版)
FROM production AS production-ssr
COPY conf/nginx/server-side-render.conf /etc/nginx/conf.d/talebook.conf
COPY conf/supervisor/server-side-render.conf /etc/supervisor/conf.d/talebook.conf
COPY --from=builder /app-ssr/ /var/www/talebook/app/
