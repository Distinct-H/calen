"""共享的 Jinja2 环境与展示用过滤器。

路由只传数据，中文措辞和格式统一在这里处理，避免散落在各个模板里。
"""

from datetime import date
from pathlib import Path

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def fmt_minutes(total: int | None) -> str:
    """分钟数转「7 小时 30 分」。符号由调用方决定，这里只管绝对值。"""
    if total is None:
        return "—"
    hours, minutes = divmod(abs(int(total)), 60)
    if hours and minutes:
        return f"{hours} 小时 {minutes} 分"
    if hours:
        return f"{hours} 小时"
    return f"{minutes} 分"


def fmt_deviation(total: int | None) -> str:
    """偏差值的人话版本。"""
    if total is None:
        return "未填写"
    if total == 0:
        return "刚好达标"
    prefix = "超出 " if total > 0 else "还差 "
    return prefix + fmt_minutes(total)


def fmt_signed_minutes(total: int | None) -> str:
    """带符号的紧凑写法，用于累计值这类需要看正负的场合。"""
    if total is None:
        return "—"
    sign = "+" if total > 0 else ("-" if total < 0 else "±")
    return f"{sign}{fmt_minutes(total)}"


def fmt_date(value: date | None) -> str:
    if value is None:
        return "—"
    return f"{value.month} 月 {value.day} 日 {WEEKDAYS[value.weekday()]}"


def fmt_percent(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.0f}%"


templates.env.filters["minutes"] = fmt_minutes
templates.env.filters["deviation"] = fmt_deviation
templates.env.filters["signed"] = fmt_signed_minutes
templates.env.filters["cn_date"] = fmt_date
templates.env.filters["percent"] = fmt_percent
