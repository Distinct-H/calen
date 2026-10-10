# 用官方镜像而不是依赖系统 Python：阿里云镜像自带的多是 3.10（Ubuntu 22.04）
# 或 3.6（Alibaba Cloud Linux 3），而本项目用了 datetime.UTC，需要 3.11+。
FROM python:3.13-slim

# 国内构建加速：compose 里会传阿里云的 PyPI 镜像
ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# 先只拷依赖清单：代码改动不会让这一层缓存失效，重新部署快很多。
# Pillow 和 psycopg[binary] 的 manylinux wheel 自带所需的 C 库，
# 所以 slim 镜像不用额外 apt 安装任何东西。
COPY requirements.txt ./
RUN pip install --index-url "${PIP_INDEX_URL}" -r requirements.txt

COPY . .

# 不用 root 跑服务
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# 启动前先跑迁移。Alembic 失败会让容器退出，比带着错的表结构硬跑要好。
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
