"""认证。

只有两个用户，所以刻意不做：注册、邮箱验证、找回密码、第三方登录。
账号由 scripts/create_users.py 创建，会话用签名 Cookie 保存。
"""

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User

_hasher = PasswordHasher()

SESSION_USER_KEY = "user_id"


class NotAuthenticatedError(Exception):
    """未登录。由 main.py 的异常处理器翻译成跳转或 401。"""


def hash_password(raw_password: str) -> str:
    return _hasher.hash(raw_password)


def verify_password(raw_password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, raw_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """argon2 参数升级后，下次登录成功时顺手把旧哈希换掉。"""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def authenticate(db: Session, username: str, raw_password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        # 用户名不存在时也做一次哈希运算，避免用响应时间探测账号是否存在
        _hasher.hash(raw_password)
        return None
    if not verify_password(raw_password, user.password_hash):
        return None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(raw_password)
        db.commit()
    return user


def login_session(request: Request, user: User) -> None:
    request.session[SESSION_USER_KEY] = user.id


def logout_session(request: Request) -> None:
    request.session.clear()


def get_optional_user(
    request: Request, db: Session = Depends(get_db)
) -> User | None:
    user_id = request.session.get(SESSION_USER_KEY)
    if not user_id:
        return None
    user = db.get(User, user_id)
    if user is None:
        # 账号被删了但 Cookie 还在，清掉避免反复查库
        request.session.clear()
    return user


def require_user(user: User | None = Depends(get_optional_user)) -> User:
    if user is None:
        raise NotAuthenticatedError
    return user


def get_partner(db: Session, user: User) -> User | None:
    """另一半。两人应用里就是「除自己之外的那条记录」。"""
    return db.scalar(select(User).where(User.id != user.id).order_by(User.id))
