"""推送适配。

两种都是「一个 URL + 一个密钥」就能用的服务，不需要 OAuth 也不需要备案：

- **Bark**（iOS）：装 App 拿到 device key，推送直接进 iOS 通知中心
- **Server酱**（微信）：扫码绑定拿到 SendKey，推送进微信服务号

接口统一成 ``Notifier.send(title, body)``，加新渠道只要再写一个类。
"""

from typing import Protocol

import httpx

from app.models import User

TIMEOUT_SECONDS = 10.0

PROVIDER_BARK = "bark"
PROVIDER_SERVERCHAN = "serverchan"

PROVIDER_LABELS = {
    PROVIDER_BARK: "Bark（iOS 通知）",
    PROVIDER_SERVERCHAN: "Server酱（推到微信）",
}


class NotifyError(RuntimeError):
    """推送失败。调用方负责记日志，不要让它冒到请求层。"""


class Notifier(Protocol):
    def send(self, title: str, body: str) -> None: ...


class BarkNotifier:
    """https://api.day.app —— 官方文档的 POST /push 形式，body 走 JSON，
    中文不用自己处理 URL 编码。"""

    ENDPOINT = "https://api.day.app/push"

    def __init__(self, device_key: str) -> None:
        self.device_key = device_key

    def send(self, title: str, body: str) -> None:
        try:
            response = httpx.post(
                self.ENDPOINT,
                json={"device_key": self.device_key, "title": title, "body": body},
                timeout=TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise NotifyError(f"Bark 请求失败：{exc}") from exc

        if response.status_code != 200:
            raise NotifyError(f"Bark 返回 HTTP {response.status_code}：{response.text[:200]}")

        # Bark 即使参数有问题也可能回 200，code 字段才是真结果
        payload = _safe_json(response)
        if payload.get("code") not in (200, None):
            raise NotifyError(f"Bark 返回 code={payload.get('code')} {payload.get('message', '')}")


class ServerChanNotifier:
    """Server酱 Turbo —— POST https://sctapi.ftqq.com/<SendKey>.send"""

    def __init__(self, send_key: str) -> None:
        self.send_key = send_key

    def send(self, title: str, body: str) -> None:
        try:
            response = httpx.post(
                f"https://sctapi.ftqq.com/{self.send_key}.send",
                data={"title": title, "desp": body},
                timeout=TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise NotifyError(f"Server酱 请求失败：{exc}") from exc

        if response.status_code != 200:
            raise NotifyError(
                f"Server酱 返回 HTTP {response.status_code}：{response.text[:200]}"
            )

        payload = _safe_json(response)
        if payload.get("code") not in (0, None):
            raise NotifyError(
                f"Server酱 返回 code={payload.get('code')} {payload.get('message', '')}"
            )


def _safe_json(response: httpx.Response) -> dict:
    """响应不是 JSON 时不要连带把推送判成失败。"""
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def build_notifier(user: User) -> Notifier | None:
    """按用户配置造推送器。没配就返回 None（站内提醒照常工作）。"""
    if not user.push_provider or not user.push_token:
        return None
    if user.push_provider == PROVIDER_BARK:
        return BarkNotifier(user.push_token)
    if user.push_provider == PROVIDER_SERVERCHAN:
        return ServerChanNotifier(user.push_token)
    return None
