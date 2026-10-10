"""图片的上传、读取、删除。"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.auth import require_user
from app.db import get_db
from app.models import User
from app.services.events import get_event
from app.services.images import (
    KIND_AVATAR,
    ImageValidationError,
    add_event_images,
    delete_image,
    get_image,
    save_avatar,
)

router = APIRouter(include_in_schema=False)


def _redirect(path: str, message: str | None = None, error: str | None = None):
    query = ""
    if message:
        query = f"?message={quote(message)}"
    elif error:
        query = f"?error={quote(error)}"
    return RedirectResponse(f"{path}{query}", status_code=303)


@router.get("/images/{image_id}")
def serve_image(
    image_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """图片是私密的，要登录才能看。

    内容不可变（同一个 id 的字节永远不变），所以可以放心长缓存；
    用 private 是因为这些照片不该被任何中间代理缓存。
    """
    image = get_image(db, image_id)
    if image is None:
        raise HTTPException(status_code=404, detail="图片不存在")

    return Response(
        content=image.data,
        media_type=image.content_type,
        headers={
            "Cache-Control": "private, max-age=31536000, immutable",
            "Content-Disposition": "inline",
            # 入库的都是我们自己重编码过的 JPEG，但仍然禁止浏览器嗅探类型
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/settings/avatar")
def upload_avatar(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    try:
        save_avatar(db, user, file)
    except ImageValidationError as exc:
        return _redirect("/settings", error=str(exc))
    return _redirect("/settings", message="头像已更新")


@router.post("/events/{event_id}/images")
def upload_event_images(
    event_id: int,
    files: list[UploadFile | str] = File(default=[]),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    if get_event(db, event_id) is None:
        return _redirect("/events", error="事件不存在")

    try:
        saved = add_event_images(db, user, event_id, files)
    except ImageValidationError as exc:
        return _redirect("/events", error=str(exc))

    if not saved:
        return _redirect("/events", error="没有选择图片")
    return _redirect("/events", message=f"已上传 {len(saved)} 张图")


@router.post("/images/{image_id}/delete")
def remove_image(
    image_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    image = get_image(db, image_id)
    if image is None:
        # 重复提交删除不该报错
        return _redirect("/events", message="图片已删除")

    back = "/settings" if image.kind == KIND_AVATAR else "/events"
    delete_image(db, image)
    return _redirect(back, message="图片已删除")
