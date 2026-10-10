"""图片上传：校验、压缩、重编码、存取。"""

import io
from datetime import date

import pytest
from PIL import Image

from app.models import Event, ImageAsset
from app.services.events import create_event
from app.services.images import (
    AVATAR_EDGE,
    EVENT_MAX_EDGE,
    MAX_EVENT_IMAGES,
    MAX_UPLOAD_BYTES,
    ImageValidationError,
    process,
)
from tests.conftest import PASSWORD


def make_image(width=800, height=600, fmt="JPEG", mode="RGB", color=(200, 100, 100)):
    image = Image.new(mode, (width, height), color)
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def open_result(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


class TestProcess:
    def test_output_is_always_jpeg(self):
        result = process(make_image(fmt="PNG"))
        assert result.content_type == "image/jpeg"
        assert open_result(result.data).format == "JPEG"

    def test_large_image_is_scaled_down(self):
        result = process(make_image(4000, 3000))
        assert max(result.width, result.height) == EVENT_MAX_EDGE
        # 保持宽高比
        assert result.width / result.height == pytest.approx(4 / 3, rel=0.01)

    def test_small_image_is_not_upscaled(self):
        result = process(make_image(320, 240))
        assert (result.width, result.height) == (320, 240)

    def test_compression_actually_shrinks_phone_sized_photos(self):
        original = make_image(3000, 2000)
        result = process(original)
        assert result.byte_size < len(original)

    def test_alpha_channel_is_flattened(self):
        """JPEG 不支持透明，必须先压到 RGB，否则 save 会直接报错。"""
        result = process(make_image(fmt="PNG", mode="RGBA", color=(10, 20, 30, 128)))
        assert open_result(result.data).mode == "RGB"

    def test_exif_is_stripped(self):
        """重编码顺手把 EXIF（含 GPS 位置）剥掉。"""
        result = process(make_image())
        assert "exif" not in open_result(result.data).info

    def test_square_mode_produces_a_square(self):
        result = process(make_image(1200, 400), square=True)
        assert (result.width, result.height) == (AVATAR_EDGE, AVATAR_EDGE)

    def test_webp_input_is_accepted(self):
        result = process(make_image(fmt="WEBP"))
        assert result.content_type == "image/jpeg"

    def test_non_image_is_rejected(self):
        with pytest.raises(ImageValidationError, match="不像图片"):
            process("这其实是一段文本，不是图片".encode() * 50)

    def test_empty_payload_is_rejected(self):
        with pytest.raises(ImageValidationError):
            process(b"")

    def test_truncated_image_is_rejected(self):
        with pytest.raises(ImageValidationError):
            process(make_image()[:40])


class TestUploadRoutes:
    def _login(self, client, username="her"):
        client.post("/login", data={"username": username, "password": PASSWORD})

    def test_avatar_upload_and_serve(self, client, her):
        self._login(client)
        response = client.post(
            "/settings/avatar",
            files={"file": ("me.jpg", make_image(1000, 800), "image/jpeg")},
        )
        assert response.status_code == 200
        assert "头像已更新" in response.text

        # 页面上应该出现头像的 img 标签
        assert '<img src="/images/' in client.get("/settings").text

    def test_served_image_is_jpeg_and_cacheable(self, client, db, her):
        self._login(client)
        client.post(
            "/settings/avatar",
            files={"file": ("me.png", make_image(fmt="PNG"), "image/png")},
        )
        image = db.query(ImageAsset).one()

        response = client.get(f"/images/{image.id}")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert "immutable" in response.headers["cache-control"]
        assert response.headers["x-content-type-options"] == "nosniff"

    def test_avatar_replaces_the_old_one(self, client, db, her):
        self._login(client)
        for _ in range(3):
            client.post(
                "/settings/avatar",
                files={"file": ("me.jpg", make_image(), "image/jpeg")},
            )
        # 只保留最新一张，否则库里会堆满历史头像
        assert db.query(ImageAsset).count() == 1

    def test_images_require_login(self, client, db, her):
        self._login(client)
        client.post(
            "/settings/avatar", files={"file": ("me.jpg", make_image(), "image/jpeg")}
        )
        image_id = db.query(ImageAsset).one().id

        client.post("/logout")
        assert client.get(f"/images/{image_id}", follow_redirects=False).status_code == 303

    def test_missing_image_is_404(self, client, her):
        self._login(client)
        assert client.get("/images/99999").status_code == 404

    def test_garbage_upload_shows_a_friendly_error(self, client, her):
        self._login(client)
        response = client.post(
            "/settings/avatar",
            files={"file": ("fake.jpg", b"not an image at all", "image/jpeg")},
        )
        assert "不像图片" in response.text

    def test_content_type_lie_is_caught(self, client, her):
        """声明的 Content-Type 不可信，真正的校验是 Pillow 能不能打开。"""
        self._login(client)
        response = client.post(
            "/settings/avatar",
            files={"file": ("payload.jpg", b"#!/bin/sh\necho hi\n", "image/jpeg")},
        )
        assert "不像图片" in response.text

    def test_oversized_upload_is_rejected(self, client, her):
        self._login(client)
        # 用不可压缩的随机字节凑出超限大小
        import os

        oversized = os.urandom(MAX_UPLOAD_BYTES + 1024)
        response = client.post(
            "/settings/avatar",
            files={"file": ("big.jpg", oversized, "image/jpeg")},
        )
        assert "太大" in response.text


class TestEventImages:
    def _login(self, client):
        client.post("/login", data={"username": "her", "password": PASSWORD})

    def test_create_event_with_images(self, client, db, her):
        self._login(client)
        response = client.post(
            "/events",
            data={"title": "出游", "event_date": "2026-10-10", "color": "rose"},
            files=[
                ("files", ("a.jpg", make_image(), "image/jpeg")),
                ("files", ("b.jpg", make_image(), "image/jpeg")),
            ],
        )
        assert response.status_code == 200
        assert "附了 2 张图" in response.text
        assert db.query(ImageAsset).count() == 2

    def test_add_images_to_existing_event(self, client, db, her):
        self._login(client)
        event = create_event(db, her, title="旧事件", event_date=date(2026, 10, 10))

        response = client.post(
            f"/events/{event.id}/images",
            files=[("files", ("a.jpg", make_image(), "image/jpeg"))],
        )
        assert "已上传 1 张图" in response.text

    def test_empty_file_input_is_ignored(self, client, db, her):
        """浏览器对空的 file input 也会提交一个 part，不能当成错误。"""
        self._login(client)
        response = client.post(
            "/events",
            data={"title": "没图", "event_date": "2026-10-10"},
            files=[("files", ("", b"", "application/octet-stream"))],
        )
        assert response.status_code == 200
        assert "事件已添加" in response.text
        assert db.query(ImageAsset).count() == 0

    def test_per_event_limit_is_enforced(self, client, db, her):
        self._login(client)
        event = create_event(db, her, title="太多图", event_date=date(2026, 10, 10))

        response = client.post(
            f"/events/{event.id}/images",
            files=[
                ("files", (f"{i}.jpg", make_image(200, 200), "image/jpeg"))
                for i in range(MAX_EVENT_IMAGES + 1)
            ],
        )
        assert f"最多 {MAX_EVENT_IMAGES} 张" in response.text
        assert db.query(ImageAsset).count() == 0

    def test_deleting_event_removes_its_images(self, client, db, her):
        self._login(client)
        client.post(
            "/events",
            data={"title": "连图一起删", "event_date": "2026-10-10"},
            files=[("files", ("a.jpg", make_image(), "image/jpeg"))],
        )
        event = db.query(Event).one()
        assert db.query(ImageAsset).count() == 1

        client.post(f"/events/{event.id}/delete")
        # 靠数据库的 ON DELETE CASCADE（SQLite 需要 foreign_keys 这个 pragma）
        assert db.query(ImageAsset).count() == 0

    def test_delete_single_image(self, client, db, her):
        self._login(client)
        client.post(
            "/events",
            data={"title": "x", "event_date": "2026-10-10"},
            files=[("files", ("a.jpg", make_image(), "image/jpeg"))],
        )
        image_id = db.query(ImageAsset).one().id

        assert client.post(f"/images/{image_id}/delete").status_code == 200
        assert db.query(ImageAsset).count() == 0

    def test_delete_twice_is_harmless(self, client, db, her):
        self._login(client)
        assert client.post("/images/99999/delete").status_code == 200

    def test_calendar_feed_marks_events_with_photos(self, client, db, her):
        self._login(client)
        client.post(
            "/events",
            data={"title": "有图", "event_date": "2026-10-10"},
            files=[("files", ("a.jpg", make_image(), "image/jpeg"))],
        )

        feed = client.get("/api/calendar?start=2026-10-01&end=2026-10-31").json()
        item = next(i for i in feed if i["extendedProps"]["kind"] == "event")
        assert item["extendedProps"]["image_count"] == 1
        assert "📷1" in item["title"]
