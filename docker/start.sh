#!/bin/sh

PUID=${PUID:-0}
PGID=${PGID:-0}

# 显式补全基础路径，避免有些环境下 gosu/supervisord 下找不到命令
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:${PATH}"

groupmod -o -g "${PGID}" talebook
usermod -o -u "${PUID}" talebook

echo "[PoxenStudio/Talebook]Starting...."

# 使用预设的书库和配置
if [ ! -d "/data/books" ]; then
  cp -rf /prebuilt/books /data/
fi

if [ ! -d "/data/books/imports/audiobooks" ]; then
  mkdir -p /data/books/imports/audiobooks
  chown -R talebook:talebook /data/books/imports/audiobooks
fi

if [ ! -s "/data/books/calibre-webserver.db" ]; then
  cp /prebuilt/books/calibre-webserver.db-* /data/books/
fi

if [ ! -d "/data/log" ]; then
  cp -rf /prebuilt/log /data/
fi

if [ ! -d "/data/log/nginx" ]; then
  mkdir -p /data/log/nginx
  chown -R talebook:talebook /data/log/nginx
fi

echo "[PoxenStudio/Talebook] Checked and parepared the default folders."

# 检查目录，拷贝并创建目录
cd /prebuilt/books/;
for f in *; do
  if [ -d "$f" -a ! -d "/data/books/$f" ]; then
    cp -rvf "/prebuilt/books/$f" /data/books/
  fi
done

# 检查文件，并拷贝过去
find . \( -path ./library -o -name '*.pyc' -o -name '*.db*' \) -prune -o -type f -print | while read f; do
    target="/data/books/$f"
    if [ ! -e "$target" ]; then
        cp "$f" "$target"
    fi
done
echo "[PoxenStudio/Talebook] Checked the library"

mkdir -p /root/.npm

echo "[PoxenStudio/Talebook] Checking the permission..."
# 设置PUID/GUID权限
permission_file=/data/.permission
touch $permission_file
permission=`cat $permission_file`
if [ "x$permission" != "x$PUID:$PGID" ]; then
    echo "updating '/data/' permission to $PUID:$PGID"
    chown -R talebook:talebook /data
    echo "$PUID:$PGID" > $permission_file
    echo "[PoxenStudio/Talebook] permission updated!"
fi

# 设置系统文件的权限（数量较少）
chown -R talebook:talebook \
  /data/log/ \
  /root/.config/calibre \
  /root/.npm \
  /var/www/talebook/app/.env \
  /var/www/talebook/app/dist \
  /var/www/talebook/webserver \
  /var/www/talebook/server.py

echo "[PoxenStudio/Talebook] Checked the permission"

# 检测权限
TEST_WRITE_FILE=/data/books/library/test_writeable.txt
date > $TEST_WRITE_FILE
if [ $? -ne 0 ]; then
    echo "目录权限异常，无法写入";
    exit 1
else
    rm $TEST_WRITE_FILE
fi

# 启动
echo "[PoxenStudio/Talebook] Prepared the running environments."

export PYTHONDONTWRITEBYTECODE=1

PYTHON_BIN="$(command -v python3 2>/dev/null || true)"
if [ -z "$PYTHON_BIN" ]; then
  for candidate in /usr/bin/python3 /usr/local/bin/python3; do
    if [ -x "$candidate" ]; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
fi

if [ -z "$PYTHON_BIN" ]; then
  echo "python3 not found. PATH=$PATH"
  exit 1
fi

USE_GOSU=0
if command -v gosu >/dev/null 2>&1; then
  if gosu talebook:talebook /bin/true >/dev/null 2>&1; then
    USE_GOSU=1
  else
    echo "warning: gosu probe failed, fallback to current user"
  fi
else
  echo "warning: gosu not found, fallback to current user"
fi

run_as_talebook() {
  if [ "$USE_GOSU" = "1" ]; then
    gosu talebook:talebook "$@"
  else
    "$@"
  fi
}

echo
echo "[PoxenStudio/Talebook] Checking the nginx config..."
nginx -t || exit 1

echo
echo "[PoxenStudio/Talebook] Syncing db as needed..."
run_as_talebook "$PYTHON_BIN" /var/www/talebook/server.py --syncdb

echo
echo "[PoxenStudio/Talebook] Updating talebook config..."
run_as_talebook "$PYTHON_BIN" /var/www/talebook/server.py --update-config

echo
echo "[PoxenStudio/Talebook] All done, launch the service..."
exec /usr/bin/supervisord --nodaemon -u root -c /etc/supervisor/supervisord.conf

