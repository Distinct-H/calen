"""图片上传：校验、压缩、重编码、存取。

**一律用 Pillow 重新编码成 JPEG**，这既是压缩也是最强的安全措施：
手机原图动不动 3~5MB，重编码后通常只剩一两百 KB；同时顺手
剥掉 EXIF（含 GPS 位置）、干掉伪装成图片的多格式文件。

不靠浏览器声明的 Content-Type 判断类型——那个随便就能伪造。
真正的校验是「Pillow 能不能把它当图片打开」。
"""

import io
from collections.abc import Sequence
from dataclasses import dataclass

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

# ⚠️ 运行时的 isinstance 必须用 Starlette 的基类。
# fastapi.UploadFile 是 starlette.datastructures.UploadFile 的**子类**，
# 而 multipart 解析器造出来的是 starlette 的实例，
# 所以 isinstance(obj, fastapi.UploadFile) 会是 False——方向反了。
from starlette.datastructures import UploadFile as AnyUploadFile

from app.models import ImageAsset, User

# 解压炸弹防护：一张 1000x1000 的 PNG 可以解压成几十 GB
Image.MAX_IMAGE_PIXELS = 50_000_000

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 原图上限 10MB
MAX_EVENT_IMAGES = 9  # 每个事件最多 9 张

AVATAR_EDGE = 512  # 头像裁成正方形
EVENT_MAX_EDGE = 1600  # 事件图最长边
JPEG_QUALITY = 82

KIND_AVATAR = "avatar"
KIND_EVENT = "event"

OUTPUT_CONTENT_TYPE = "image/jpeg"

# iOS Safari 上传时会自动把 HEIC 转成 JPEG，所以通常不用管 HEIC。
# 万一碰到转不了的格式，这行文案告诉用户该怎么办。
SUPPORTED_HINT = "支持 JPG / PNG / WebP / GIF / BMP"


class ImageValidationError(ValueError):
    """上传的东西有问题。路由把它翻译成给用户看的提示。"""


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    content_type: str
    width: int
    height: int

    @property
    def byte_size(self) -> int:
        return len(self.data)


def read_capped(upload: UploadFile) -> bytes:
    """读取上传内容，超限立即拒绝。

    多读 1 字节用来判断「是不是正好等于上限」——只读 MAX 个字节的话
    没法区分「刚好 10MB」和「超过 10MB 被截断」。
    """
    data = upload.file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise ImageValidationError("没有选择文件，或者文件是空的")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageValidationError(
            f"图片太大，单张上限 {MAX_UPLOAD_BYTES // 1024 // 1024} MB"
        )
    return data


def process(raw: bytes, *, max_edge: int = EVENT_MAX_EDGE, square: bool = False) -> ProcessedImage:
    """校验 + 缩放 + 重编码成 JPEG。"""
    try:
        source = Image.open(io.BytesIO(raw))
    except Image.DecompressionBombError as exc:
        raise ImageValidationError("图片尺寸异常大，拒绝处理") from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageValidationError(f"这个文件不像图片。{SUPPORTED_HINT}") from exc

    try:
        with source:
            # 必须先按 EXIF 方向转正，否则手机竖拍的照片会躺着
            oriented = ImageOps.exif_transpose(source) or source
            # 转 RGB 顺带压掉 alpha 通道，JPEG 不支持透明
            rgb = oriented.convert("RGB")

            if square:
                # 居中裁切成正方形，适合头像
                rgb = ImageOps.fit(rgb, (AVATAR_EDGE, AVATAR_EDGE), method=Image.LANCZOS)
            else:
                # thumbnail 只缩不放，小图保持原样
                rgb.thumbnail((max_edge, max_edge), Image.LANCZOS)

            buffer = io.BytesIO()
            rgb.save(
                buffer,
                format="JPEG",
                quality=JPEG_QUALITY,
                optimize=True,
                progressive=True,
            )
            return ProcessedImage(
                data=buffer.getvalue(),
                content_type=OUTPUT_CONTENT_TYPE,
                width=rgb.width,
                height=rgb.height,
            )
    except Image.DecompressionBombError as exc:
        raise ImageValidationError("图片尺寸异常大，拒绝处理") from exc
    except OSError as exc:
        raise ImageValidationError(f"图片处理失败：{exc}") from exc


# ── 存取 ────────────────────────────────────────────────────────


def get_image(db: Session, image_id: int) -> ImageAsset | None:
    return db.get(ImageAsset, image_id)


def get_avatar(db: Session, user: User) -> ImageAsset | None:
    """用户当前头像。替换头像时旧的会被删，所以最多只有一条。"""
    return db.scalar(
        select(ImageAsset)
        .where(ImageAsset.owner_id == user.id, ImageAsset.kind == KIND_AVATAR)
        .order_by(ImageAsset.id.desc())
    )


def list_event_images(db: Session, event_id: int) -> list[ImageAsset]:
    return list(
        db.scalars(
            select(ImageAsset)
            .where(ImageAsset.kind == KIND_EVENT, ImageAsset.event_id == event_id)
            .order_by(ImageAsset.id)
        )
    )


def count_event_images(db: Session, event_id: int) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(ImageAsset)
            .where(ImageAsset.kind == KIND_EVENT, ImageAsset.event_id == event_id)
        )
        or 0
    )


def save_avatar(db: Session, user: User, upload: UploadFile) -> ImageAsset:
    """存头像。一人只保留一张，旧的直接删掉，不然库里会堆满历史头像。"""
    processed = process(read_capped(upload), square=True)

    for old in db.scalars(
        select(ImageAsset).where(
            ImageAsset.owner_id == user.id, ImageAsset.kind == KIND_AVATAR
        )
    ):
        db.delete(old)

    image = ImageAsset(
        owner_id=user.id,
        kind=KIND_AVATAR,
        event_id=None,
        content_type=processed.content_type,
        width=processed.width,
        height=processed.height,
        byte_size=processed.byte_size,
        data=processed.data,
    )
    db.add(image)
    db.commit()
    db.refresh(image)
    return image


def pick_real_uploads(uploads: Sequence[object]) -> list[UploadFile]:
    """挑出真正带内容的文件，忽略空的文件输入框。

    空 input 会以两种形状出现，都得兜住：
    - 浏览器发 ``filename=""``（参数在、值为空）→ 是 UploadFile，但文件名为空
    - 某些客户端（含 httpx）直接**省略** filename 参数 → Starlette 当成普通字符串字段

    第二种如果不过滤，``list[UploadFile]`` 会让整个请求 422，错误信息还看不懂。
    """
    return [
        u
        for u in uploads
        if isinstance(u, AnyUploadFile) and (u.filename or "").strip()
    ]


def add_event_images(
    db: Session, user: User, event_id: int, uploads: Sequence[object]
) -> list[ImageAsset]:
    """给事件加图。"""
    real = pick_real_uploads(uploads)
    if not real:
        return []

    already = count_event_images(db, event_id)
    if already + len(real) > MAX_EVENT_IMAGES:
        raise ImageValidationError(
            f"每个事件最多 {MAX_EVENT_IMAGES} 张图，现在已有 {already} 张"
        )

    saved: list[ImageAsset] = []
    for upload in real:
        processed = process(read_capped(upload), max_edge=EVENT_MAX_EDGE)
        image = ImageAsset(
            owner_id=user.id,
            kind=KIND_EVENT,
            event_id=event_id,
            content_type=processed.content_type,
            width=processed.width,
            height=processed.height,
            byte_size=processed.byte_size,
            data=processed.data,
        )
        db.add(image)
        saved.append(image)

    db.commit()
    for image in saved:
        db.refresh(image)
    return saved


def delete_image(db: Session, image: ImageAsset) -> None:
    db.delete(image)
    db.commit()


def total_bytes(db: Session) -> int:
    """图片总占用。设置页展示一下，好让人知道什么时候该考虑换对象存储。"""
    return int(
        db.scalar(select(func.coalesce(func.sum(ImageAsset.byte_size), 0))) or 0
    )
