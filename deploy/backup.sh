#!/usr/bin/env bash
# 数据库备份。放进 crontab 每天跑一次。
#
#   sudo crontab -e
#   17 3 * * * /opt/couple-calendar/deploy/backup.sh >> /var/log/couple-backup.log 2>&1
#
# 图片的字节也在库里，所以这一个 dump 就包含了全部数据，不用单独备份文件。

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/couple-calendar}"
BACKUP_DIR="${BACKUP_DIR:-/opt/couple-backups}"
KEEP_DAYS="${KEEP_DAYS:-30}"
COMPOSE="docker compose -f ${APP_DIR}/docker-compose.prod.yml --env-file ${APP_DIR}/.env.prod"

cd "$APP_DIR"

# shellcheck disable=SC1091
set -a; source "${APP_DIR}/.env.prod"; set +a

mkdir -p "$BACKUP_DIR"
stamp=$(date +%Y%m%d_%H%M%S)
target="${BACKUP_DIR}/couple_${stamp}.sql.gz"

echo "[$(date '+%F %T')] 开始备份 → ${target}"

# -T 关掉 TTY 分配，否则 cron 环境下会报 "the input device is not a TTY"
$COMPOSE exec -T db \
  pg_dump -U "${POSTGRES_USER:-couple}" -d "${POSTGRES_DB:-couple}" \
  | gzip > "$target"

size=$(du -h "$target" | cut -f1)
echo "[$(date '+%F %T')] 完成，大小 ${size}"

# 空文件说明 pg_dump 失败了（管道里 gzip 仍会成功，所以要单独查）
if [ ! -s "$target" ]; then
  echo "[$(date '+%F %T')] 备份文件是空的，pg_dump 很可能失败了！" >&2
  rm -f "$target"
  exit 1
fi

deleted=$(find "$BACKUP_DIR" -name 'couple_*.sql.gz' -mtime "+${KEEP_DAYS}" -print -delete | wc -l)
echo "[$(date '+%F %T')] 清理了 ${deleted} 个超过 ${KEEP_DAYS} 天的旧备份"

# ⚠️ 本地备份只防「误删数据」，不防「服务器整台挂掉」。
# 想防后者，取消下面注释，先 rclone config 配好阿里云 OSS：
# rclone copy "$target" aliyun-oss:你的bucket/couple-backups/
