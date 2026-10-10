# 我们的日历

两人共享的打卡 + 日历应用。女生记每日**睡眠时长**，男生记每日**锻炼时长**，
各自设定达标值，系统算出当日「距离达标还差多少 / 超出多少」并存档。

## 功能

| 页面 | 内容 |
|---|---|
| **今日** | 自己打卡、对方今日状态、双方达标程度对比、**亲亲账本与加亲亲申请审批**、累计偏差与连续达标、站内提醒横幅 |
| **日历** | FullCalendar 月视图（手机自动切列表视图），打卡用 ✓/✗ 和颜色标记，叠加事件 |
| **事件** | 事件增删改，支持全天 / 定时、配色、备注、**图片**。共享可见，两人都能改 |
| **纪念日** | 倒数与「已经第 N 天」，支持每年 / 每月 / 仅一次，可配提前几天提醒 |
| **统计** | 每日偏差折线、累计偏差面积图、亲亲余额走势、结算明细、达标率与连续达标 |
| **设置** | **头像**、昵称、达标值、**亲亲兑换规则**、推送渠道、提醒规则、改密码 |

部署上线：**阿里云 ECS** 看 [deploy/ALIYUN.md](deploy/ALIYUN.md)，托管平台（Railway / Render）看 [DEPLOY.md](DEPLOY.md)。

## 快速开始

```bash
# 1. 装依赖
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. 配置（SESSION_SECRET / CRON_SECRET 必填）
cp .env.example .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # 生成密钥

# 3. 建表
alembic upgrade head

# 4. 建两个账号（没有注册入口，账号在这里建）
python scripts/create_users.py --username her --display-name 小美 --role female --target 8:00
python scripts/create_users.py --username him --display-name 小强 --role male   --target 1:00

# 5. 启动
uvicorn app.main:app --reload
# 打开 http://127.0.0.1:8000
```

想看日历颜色和趋势图的效果，可以灌点假数据：

```bash
python scripts/seed_demo.py --days 45
```

## 核心概念：达标值是「快照」的

每条打卡会同时存三个值：**实际时长**、**当时的达标值**、**当时算出的偏差**。

这是刻意的冗余存储。如果偏差值靠「读当前达标值实时计算」，那么你哪天把目标
从 8 小时调到 7 小时，过去一年的历史偏差会被静默改写——存档就失去意义了。

具体规则（见 `app/services/records.py:resolve_target_minutes`）：

| 操作 | 用哪个达标值 |
|---|---|
| 新建记录 | 快照当前设置 |
| 改**今天**的记录 | 重新快照（今天还是「活的」，刚调完目标就该生效） |
| 改**历史**记录 | 保留它原本的达标值，不受当前设置影响 |
| 在设置页改达标值 | 只重算今天那条，历史一行不动 |

这条性质由 `tests/test_records.py::TestSnapshot` 守着。

## 亲亲账本

每天两人都填完后**自动结算**：按「达标程度之差」把领先的分钟数换成亲亲。

```
pair_diff = 女生偏差 - 男生偏差

男生领先（pair_diff < 0）→ 女生欠的亲亲 增加
女生领先（pair_diff > 0）→ 两种模式二选一：
    deduct  抵扣女生欠的亲亲
    custom  亲亲不变，改成累积自定义奖励（名称和比率都可配）
```

比率在设置页配，比如 `3 分钟 : 1 个亲亲`。余额可以为负 —— 那就显示成「男生欠女生 N 个」。

**比率也是快照的**，和达标值同一个原则：改 3:1 为 6:1 只会重算今天，
历史结算保留各自当时的比率。否则「欠了多少」会在改一次设置后全部变样，
再也对不上账。由 `tests/test_kisses.py::TestRatioSnapshot` 守着。

结算的触发点有三处，都会落到同一个 `settle_day()`：

- 任一方的打卡被写入或修改 → 重算那天
- 达标值被修改 → 偏差变了 → 重算今天
- 设置页「补算历史」→ 给还没结算过的日期补上（功能上线后的一次性回填）

亲亲以「百分之一个」为单位用整数存（`kiss_delta_centi`），避开浮点误差，
也避开 Decimal 在 SQLite 和 Postgres 上的方言差异。

当天双方结算完成后，男生可以申请增加亲亲（最多 100 个，可附说明）；女生在
今日页审批。只有通过的申请会增加账本余额，并单独保留申请、审批状态和时间，
不会被修改打卡或重算每日结算覆盖。

> **调参提示**：睡眠的波动幅度（±70 分钟）天然比锻炼大（±30 分钟），
> 所以如果两边达标值都设得宽松，女生会长期「领先」，余额会一路往一个方向跑。
> 想让账本有来有回，要么把睡眠目标调高一点，要么用 `custom` 模式让
> 女生领先时换成别的奖励而不是无限抵扣。

## 图片

事件可以配图（每个最多 9 张），头像一人一张。

**存在数据库里**，不是文件系统。因为托管平台的容器磁盘每次部署都会重置——
存本地等于每发一次版照片全丢，和 SQLite 是同一个坑。

入库前一律用 Pillow 处理：

1. **按 EXIF 方向转正** —— 不做这步手机竖拍的照片会躺着
2. **限制尺寸** —— 事件图最长边 1600px，头像居中裁成 512×512
3. **重新编码成 JPEG** —— 这既是压缩也是最强的安全措施：
   顺手剥掉 EXIF（含 GPS 拍摄位置）、干掉伪装成图片的多格式文件

类型校验不看浏览器声明的 Content-Type（随便就能伪造），而是看 Pillow 能不能把它当图片打开。

单张原图上限 10MB，处理后通常只剩一两百 KB。设置页会显示图片总占用，
真到了库撑不住的规模（比如超过 1GB），再换对象存储——只需要改
`app/services/images.py` 的存取函数。

> **HEIC**：iOS Safari 通过文件选择器上传时会自动把 HEIC 转成 JPEG，
> 所以一般不用管。万一碰到转不了的，装 `pillow-heif` 即可，它有预编译 wheel。

## 提醒是怎么跑的

**不把定时器写在应用进程里。** 托管平台会休眠、会重启，进程内的 APScheduler
不可靠。应用只暴露一个幂等入口，由外部按时来打：

```bash
# HTTP 入口（给外部 cron 服务用）
curl -X POST http://127.0.0.1:8000/internal/cron/tick -H "X-Cron-Secret: ..."

# CLI 入口（给平台 cron 用，不走网络）
python scripts/tick.py --dry-run     # 只看会发什么
python scripts/tick.py               # 真的发
```

两个入口调同一个函数，共用同一套幂等保证，同时配着也不会重复推送。

幂等靠 `reminder_logs` 的 `UNIQUE(reminder_id, user_id, sent_date)`：
**先抢占当天的名额，抢到了才真的推送**。重复触发必然只有一个抢得到。

两条刻意的取舍：

- **推送失败当天不重试** —— 重试要面对「请求超时但其实发成功了」，那会导致
  一天响好几次。宁可漏一条，也不要重复打扰。失败会记在 `reminder_logs` 里。
- **服务停机后会补发** —— 规则是「今天的触发时间已过且今天还没发过」，
  所以早上 8 点的提醒即使服务到晚上才恢复，也还是会发。晚发好过不发。

推送渠道（Bark / Server酱）在设置页各自配，不配也能用——站内提醒横幅始终有效。

## 常用命令

```bash
pytest -v                                  # 跑测试
alembic revision --autogenerate -m "说明"   # 改了 models.py 后生成迁移
alembic upgrade head                       # 应用迁移
alembic downgrade -1                       # 回退一步
uvicorn app.main:app --reload              # 开发服务器
```

## 项目结构

```
app/
  main.py              FastAPI 入口、中间件、未登录异常处理
  config.py            环境变量配置 + 连接串规整 + 生产自检
  db.py                引擎与会话
  models.py            6 张表的 ORM 定义
  auth.py              argon2 哈希、会话、current_user 依赖
  templating.py        Jinja2 环境与中文格式化过滤器
  services/
    scoring.py         ★ 偏差计算（改公式只动这个文件）
    records.py         打卡写入 + 达标值快照规则
    dashboard.py       今日面板视图模型
    clock.py           时区与「今天是哪天」
    events.py          事件 CRUD 与校验
    anniversary.py     纪念日推算（闰年 / 月末边界）
    calendar.py        组装 FullCalendar 数据源
    stats.py           图表时间序列
    reminder.py        ★ 提醒筛选与幂等发送
    notifier.py        Bark / Server酱 推送适配
    kisses.py          ★ 亲亲兑换与每日结算（改规则只动这个文件）
    images.py          图片校验、压缩、重编码、存取
  routers/
    pages.py           登录、今日、设置
    records.py         打卡提交（HTMX 片段）+ /api/records
    calendar.py        日历页 + /api/calendar
    events.py          事件页与增删改
    anniversaries.py   纪念日页与增删改
    stats.py           统计页 + /api/stats
    reminders.py       推送配置与提醒规则
    kisses.py          亲亲兑换规则配置
    images.py          图片上传 / 读取 / 删除
    cron.py            /internal/cron/tick
  templates/           Jinja2 + HTMX
scripts/
  create_users.py      建/改账号
  seed_demo.py         灌演示数据
  tick.py              发送到期提醒（平台 cron 入口）
```

## 几个设计取舍

**只有两个用户**，所以刻意不做：注册流程、邮箱验证、找回密码、第三方登录、
多租户、权限系统。账号用脚本建，密码忘了用脚本重置。

**不做前后端分离**。Jinja2 + HTMX，一个服务搞定，省掉 CORS、独立构建、
二次部署。两个用户的应用从 SPA 架构里得不到任何收益。

**时区按用户算**，不用服务器时间。托管平台跑 UTC，不处理的话中国时间
凌晨 0:00–8:00 的打卡会被记到前一天。见 `app/services/clock.py`。

**生产环境必须用 PostgreSQL**。托管平台容器的文件系统每次部署都会重置，
SQLite 放在容器里等于每发一次版数据清零。本地开发用 SQLite 没问题。

## 注意

- `.env` 不要提交（已在 `.gitignore` 里）
- 用 `curl -d` 测试中文备注会看到乱码，那是 curl 不做 percent-encoding 导致的，
  不是应用的问题。要测就用 `curl --data-urlencode`，浏览器本来就是这么发的。
