"""FastAPI 入口。"""

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth import NotAuthenticatedError
from app.config import settings
from app.routers import (
    anniversaries,
    calendar,
    cron,
    events,
    images,
    kisses,
    pages,
    records,
    reminders,
    stats,
)

# 带着占位密钥上生产等于没有会话安全，宁可起不来
settings.assert_production_ready()

app = FastAPI(
    title="情侣日历",
    # 生产环境不暴露接口文档
    docs_url="/api/docs" if settings.debug else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if settings.debug else None,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    max_age=settings.session_max_age,
    same_site="lax",
    # 浏览器拒绝在 http:// 上保存 Secure Cookie，所以这个开关要能单独控制：
    # 还没配 HTTPS（比如暂时用 http://IP 访问）时必须关掉，否则登录会静默失败。
    https_only=settings.session_https_only,
)

app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="static",
)


@app.exception_handler(NotAuthenticatedError)
async def handle_not_authenticated(request: Request, _exc: NotAuthenticatedError):
    """未登录的处理方式取决于请求来源。"""
    if request.headers.get("HX-Request"):
        # HTMX 不会跟随 303，得用它自己的跳转头
        return Response(status_code=401, headers={"HX-Redirect": "/login"})
    if request.url.path.startswith("/api"):
        return JSONResponse({"detail": "未登录"}, status_code=401)
    return RedirectResponse("/login", status_code=303)


app.include_router(pages.router)
app.include_router(records.router)
app.include_router(calendar.router)
app.include_router(events.router)
app.include_router(anniversaries.router)
app.include_router(stats.router)
app.include_router(reminders.router)
app.include_router(images.router)
app.include_router(kisses.router)
app.include_router(cron.router)


@app.get("/healthz", include_in_schema=False)
def healthz():
    """托管平台的健康检查端点。不碰数据库，纯探活。"""
    return {"status": "ok"}
