#!/usr/bin/env bash
# 更新部署：拉代码 → 重建 → 验证。在服务器上跑。
#
#   cd /opt/couple-calendar && ./deploy/deploy.sh
#
# 更新前会自动备份一次数据库，所以迁移出问题时有退路。

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/couple-calendar}"
COMPOSE="docker compose -f ${APP_DIR}/docker-compose.prod.yml --env-file ${APP_DIR}/.env.prod"

cd "$APP_DIR"

echo "==> 更新前先备份"
if [ -x "${APP_DIR}/deploy/backup.sh" ]; then
  "${APP_DIR}/deploy/backup.sh"
else
  echo "    找不到 backup.sh，跳过（建议先把它配好）"
fi

echo "==> 记录当前版本，万一要回滚"
previous=$(git rev-parse --short HEAD)
echo "    当前: ${previous}"

echo "==> 拉取代码"
git pull --ff-only

current=$(git rev-parse --short HEAD)
if [ "$previous" = "$current" ]; then
  echo "    已经是最新，没有新提交"
else
  echo "    ${previous} → ${current}"
fi

echo "==> 重建并启动（容器启动时会自动跑 alembic upgrade head）"
$COMPOSE up -d --build

echo "==> 等待健康检查"
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8000/healthz > /dev/null 2>&1; then
    echo "    ✓ 服务已就绪"
    break
  fi
  if [ "$i" = 30 ]; then
    echo "    ✗ 60 秒内没起来，看日志：" >&2
    $COMPOSE logs --tail=50 app >&2
    echo "    回滚：git reset --hard ${previous} && ./deploy/deploy.sh" >&2
    exit 1
  fi
  sleep 2
done

echo "==> 清理旧镜像，避免磁盘越用越满"
docker image prune -f

echo "==> 当前状态"
$COMPOSE ps

echo ""
echo "完成。回滚命令（如果发现问题）："
echo "  cd ${APP_DIR} && git reset --hard ${previous} && ./deploy/deploy.sh"
echo "  注意：数据库迁移不会自动回滚，涉及删字段的要先 alembic downgrade"
