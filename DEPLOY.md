# 部署上线

以 **Railway** 为主线（本机没装 Docker，托管平台最省事）。Render 的差异在最后一节。

---

## 一、推上 GitHub

```bash
cd couple-calendar
git remote add origin https://github.com/你的账号/couple-calendar.git
git push -u origin main
```

仓库建成 **private**。虽然 `.env` 已被 gitignore，但这是你们俩的私人数据应用，没必要公开。

---

## 二、Railway 建服务

1. [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo** → 选这个仓库
2. 平台会读 `railway.json`，自动用 Nixpacks 构建，启动命令已配好（先跑迁移再起服务）
3. 首次部署会失败 —— 正常，因为还没有数据库

### 加 PostgreSQL

项目面板 → **New** → **Database** → **Add PostgreSQL**

> ⚠️ **必须用 Postgres，不能用 SQLite。** 容器文件系统每次部署都会重置，
> SQLite 放在容器里等于每发一次版数据清零。

Railway 会自动给 Web 服务注入 `DATABASE_URL`。代码里的
`normalize_database_url()` 会把它规整成 psycopg3 能用的形式，你不用管。

### 配环境变量

Web 服务 → **Variables**，加这三个：

| 变量 | 值 |
|---|---|
| `SESSION_SECRET` | 下面命令生成 |
| `CRON_SECRET` | 下面命令生成（和上面用不同的值） |
| `DEBUG` | `false` |

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

> `DEBUG=false` 时应用启动会自检：这两个密钥没设或还是占位值就拒绝启动。
> 宁可起不来，也不要带着默认密钥对外提供服务。

`DEFAULT_TIMEZONE` 默认已是 `Asia/Shanghai`，不用配。

### 生成域名

Settings → **Networking** → **Generate Domain**，拿到 `xxx.up.railway.app`。
Railway 自动配 HTTPS，不用自己折腾证书。

想绑自己的域名也在这里加 —— 注意用 Railway 这类海外节点**不需要 ICP 备案**；
如果以后迁到国内云服务器 + 自有域名，备案是强制的，周期 1–3 周。

---

## 三、建账号

Railway 的服务容器里没有交互式终端能跑脚本，用本地连生产库最方便：

```bash
# 1. 从 Railway 的 Postgres → Variables 复制 DATABASE_PUBLIC_URL
export DATABASE_URL='postgresql://...'   # 用公网连接串，不是内网的

# 2. 本地直连生产库建账号
source .venv/bin/activate
python scripts/create_users.py --username her --display-name 小美 --role female --target 8:00
python scripts/create_users.py --username him --display-name 小强 --role male   --target 1:00

# 3. 用完立刻清掉，别让它留在 shell 历史里
unset DATABASE_URL
```

> 密码不要用 `--password` 传（会进 shell history），让脚本交互式提示你输入。

---

## 四、配定时提醒

提醒不靠应用进程里的定时器 —— 平台可能休眠、重启，进程内调度不可靠。
应用暴露的是一个**幂等触发入口**，由外部按时来打。

两种方式选一个（配两个也不会重复推送，幂等由数据库唯一约束保证）：

### 方式 A：Railway Cron（推荐）

项目面板 → **New** → **Empty Service** → 连同一个仓库：

- **Start Command**：`python scripts/tick.py --quiet`
- **Settings → Cron Schedule**：`*/10 * * * *`（每 10 分钟查一次）
- **Variables**：加上 `DATABASE_URL`（引用 Postgres 服务的变量）

每 10 分钟检查一次是为了容错：某次 cron 失败了，10 分钟后会补上，
而同一条提醒当天仍然只发一次。

### 方式 B：外部 cron

[cron-job.org](https://cron-job.org) 免费注册，加一个任务：

- URL：`https://你的域名/internal/cron/tick`
- Method：**POST**
- Header：`X-Cron-Secret: <你的 CRON_SECRET>`
- 频率：每 10 分钟

Render 免费版必须用这个方式 —— 它闲置会休眠，外部请求能同时起到唤醒作用。

### 验证

```bash
# 先 dry-run 看会发什么，不会真的推送也不占当天名额
curl -X POST 'https://你的域名/internal/cron/tick?dry_run=true' \
  -H "X-Cron-Secret: $CRON_SECRET"

# 真的触发
curl -X POST https://你的域名/internal/cron/tick \
  -H "X-Cron-Secret: $CRON_SECRET"

# 再打一次 —— sent 应该是 0，这就是幂等生效了
curl -X POST https://你的域名/internal/cron/tick \
  -H "X-Cron-Secret: $CRON_SECRET"
```

推送渠道在应用的**设置页**里配，两人各配自己的：

- **Bark**（iOS）：App Store 装 Bark → 复制 device key → 粘到设置页
- **Server酱**（推到微信）：[sct.ftqq.com](https://sct.ftqq.com) 微信扫码 → 复制 SendKey

配完点「发送测试推送」，手机收到才算通。

---

## 五、上线检查清单

- [ ] `DEBUG=false`，错误页不泄露堆栈
- [ ] `SESSION_SECRET` / `CRON_SECRET` 是随机生成的，不是占位值
- [ ] 两个账号密码都 ≥ 8 位，不是弱密码
- [ ] `https://域名` 能登录，HTTP 自动跳 HTTPS
- [ ] `/api/docs` 返回 404（生产环境应该关掉）
- [ ] **填一条数据 → 手动触发一次重新部署 → 数据还在**
      （这是验证 Postgres 真的生效的唯一可靠方法，别跳过）
- [ ] 改一次达标值 → 历史记录的偏差值没变
- [ ] cron 连打两次，第二次 `sent: 0`
- [ ] 两人手机都收到过测试推送

---

## 六、图片会占数据库空间

图片的字节直接存在 Postgres 里（容器磁盘每次部署会重置，存本地等于每发一次版照片全丢）。

上传时会压到最长边 1600px 的 JPEG，单张通常一两百 KB，所以：

| 图片数 | 大致占用 |
|---|---|
| 100 张 | ~20 MB |
| 500 张 | ~100 MB |
| 2000 张 | ~400 MB |

Railway 的 Postgres 装得下，但要注意 `pg_dump` 的备份文件会跟着变大。
设置页底部会显示当前图片总占用，超过 1GB 再考虑换对象存储
（只需要改 `app/services/images.py` 的存取函数）。

---

## 七、备份

**没验证过恢复的备份等于没有备份。**

```bash
# 导出（DATABASE_URL 用 Railway 的公网连接串）
pg_dump "$DATABASE_URL" | gzip > backup_$(date +%Y%m%d).sql.gz

# 恢复演练：先在本地建个空库，把备份灌进去，确认能起来
createdb couple_restore_test
gunzip -c backup_20261009.sql.gz | psql couple_restore_test
```

两个人的数据量很小，每月手动导一次就够。要自动化就在 Railway 再加一个
cron 服务跑 `pg_dump`，把结果传到对象存储。

---

## 八、日常维护

```bash
# 改了 models.py 之后
alembic revision --autogenerate -m "说明"
alembic upgrade head        # 本地先验证
pytest                      # 测试过了再推
git push                    # Railway 自动部署，启动时会跑 alembic upgrade head
```

**回滚**：Railway 的 Deployments 列表里选上一个成功的部署 → **Redeploy**。
注意数据库迁移不会自动回滚，涉及删字段的迁移要先手动 `alembic downgrade -1`。

---

## Render 的差异

用 `render.yaml` 蓝图部署（Dashboard → **Blueprints** → 连仓库）。两个必须知道的限制：

1. **免费 Web Service 闲置 15 分钟会休眠。** 冷启动要十几秒，而且进程内的
   定时器不会触发 → 定时提醒必须用上面的**方式 B**（外部 cron），
   它顺便还能把服务唤醒。
2. **免费 Postgres 有有效期，到期会被直接删除。** 一定要配好定期导出备份，
   或者直接上付费计划。

长期跑建议 Railway Hobby（约 5 美元/月，含 Postgres，不休眠）。
