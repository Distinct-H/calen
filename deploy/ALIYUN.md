# 部署到阿里云 ECS

从一台刚买的空服务器到能用，按顺序走一遍。预计 40–60 分钟（不含备案）。

> **为什么用 Docker 而不是裸装**：本项目用了 `datetime.UTC`，需要 Python 3.11+。
> 而阿里云镜像自带的是 Ubuntu 22.04 → 3.10、Alibaba Cloud Linux 3 → 3.6，都不够。
> 裸装就得自己编译 Python 或加第三方源，不如直接用官方镜像省事。

---

## 第 0 步：先确认三件事

### ① 节点在哪里 → 决定要不要备案

| 节点 | 域名访问 80/443 | 说明 |
|---|---|---|
| **国内**（杭州、北京、上海…） | **必须 ICP 备案** | 周期通常 1–3 周，阿里云控制台可提交 |
| **香港 / 海外**（新加坡、东京…） | 不需要 | 但国内访问速度不如国内节点 |

**备案没下来也能先用**：直接 `http://服务器IP` 访问，不绑域名就不受备案限制。
这份指南就是按「先 IP 跑起来 → 备案后再绑域名和 HTTPS」的顺序安排的。

### ② 安全组必须在控制台开 —— 最容易漏的一步

阿里云的防火墙有**两层**，服务器里的 `ufw` 只是其中一层：

- **ECS**：控制台 → 实例 → 安全组 → 配置规则 → 入方向
- **轻量应用服务器**：控制台 → 服务器 → 安全 → 防火墙

先只放通这三个端口：

| 端口 | 用途 |
|---|---|
| 22 | SSH |
| 80 | HTTP |
| 443 | HTTPS（备案后配证书用） |

> **不要开 5432、8000**。数据库和应用都只在本机回环上监听，开了反而是风险。

### ③ 配置够不够

两个人用，**2 核 2G 够了**。1 核 1G 也能跑，但建议先加 2G swap（见文末「常见问题」）。

---

## 第 1 步：服务器初始化与加固

```bash
# 首次用 root 登录（密码在阿里云控制台重置过的那个）
ssh root@你的服务器IP

# 更新系统
apt update && apt upgrade -y            # Ubuntu / Debian
# dnf update -y                         # Alibaba Cloud Linux / CentOS

# 建个非 root 用户，别一直用 root 跑服务
adduser deploy
usermod -aG sudo deploy                 # Ubuntu
# usermod -aG wheel deploy              # Alibaba Cloud Linux
```

在**你自己的 Mac** 上把公钥传过去：

```bash
# 没有密钥先生成
ssh-keygen -t ed25519 -C "couple-calendar"

# 传公钥（会让你输 deploy 的密码）
ssh-copy-id deploy@你的服务器IP

# 验证能免密登录
ssh deploy@你的服务器IP
```

**确认密钥登录成功之后**，再关掉密码登录和 root 登录：

```bash
sudo sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart sshd

# 挡暴力破解
sudo apt install -y fail2ban
sudo systemctl enable --now fail2ban
```

> 顺序很重要：先验证密钥能登，再禁密码。反了就把自己锁在外面了。

---

## 第 2 步：装 Docker（含国内加速）

```bash
# 阿里云的安装脚本，比官方 get.docker.com 快
curl -fsSL https://get.docker.com | sudo sh -s -- --mirror Aliyun

# 免 sudo 用 docker
sudo usermod -aG docker "$USER"
newgrp docker

# 开机自启
sudo systemctl enable --now docker

docker --version && docker compose version
```

**配镜像加速器** —— 不配的话拉 `postgres:16-alpine` 会很慢甚至超时：

```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json > /dev/null <<'EOF'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://dockerproxy.com",
    "https://docker.nju.edu.cn"
  ],
  "log-driver": "json-file",
  "log-opts": { "max-size": "50m", "max-file": "5" }
}
EOF

sudo systemctl restart docker
docker info | grep -A5 "Registry Mirrors"
```

> 阿里云自己的容器镜像服务也提供专属加速地址（控制台 → 容器镜像服务 →
> 镜像加速器），有的话优先用那个，比公共镜像稳定。
> 公共镜像站时好时坏，哪个不通就换下一个。

验证能拉镜像：

```bash
docker run --rm hello-world
```

---

## 第 3 步：把代码放到服务器

### 方式 A：rsync 直传（最省事，不用配 git 认证）

在**你的 Mac** 上：

```bash
cd /Users/miaodehua/PycharmProjects/couple-calendar

# 注意排除本地的 .env、SQLite 库和虚拟环境
rsync -avz --delete \
  --exclude '.git' --exclude '.venv' --exclude '__pycache__' \
  --exclude '.env' --exclude '.env.prod' --exclude 'data/' \
  --exclude '.pytest_cache' --exclude '.DS_Store' \
  ./ deploy@你的服务器IP:/opt/couple-calendar/
```

第一次会因为目录不存在失败，先在服务器上建好：

```bash
sudo mkdir -p /opt/couple-calendar
sudo chown deploy:deploy /opt/couple-calendar
```

### 方式 B：git（后续更新更方便，`deploy.sh` 也依赖它）

先把仓库推到远端。**国内服务器建议用 Gitee**，拉 GitHub 经常超时：

```bash
# Mac 上
git remote add gitee https://gitee.com/你的账号/couple-calendar.git
git push gitee main
```

服务器上：

```bash
sudo apt install -y git
sudo mkdir -p /opt/couple-calendar && sudo chown deploy:deploy /opt/couple-calendar
git clone https://gitee.com/你的账号/couple-calendar.git /opt/couple-calendar
```

> 仓库设为**私有**。虽然 `.env` 已被 gitignore，但这是你们俩的私人数据应用。
> 私有仓库在服务器上拉取需要配 deploy key 或访问令牌。

---

## 第 4 步：配置环境变量

```bash
cd /opt/couple-calendar
cp .env.prod.example .env.prod
```

先生成三个密钥（服务器上没 python3 也能用 openssl）：

```bash
for name in POSTGRES_PASSWORD SESSION_SECRET CRON_SECRET; do
  echo "$name=$(openssl rand -base64 48 | tr -d '/+=' | cut -c1-44)"
done
```

把输出的三行填进 `.env.prod`：

```bash
nano .env.prod
```

```bash
POSTGRES_DB=couple
POSTGRES_USER=couple
POSTGRES_PASSWORD=<上面生成的第 1 个>
SESSION_SECRET=<上面生成的第 2 个>
CRON_SECRET=<上面生成的第 3 个>
APP_PORT=8000
PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
```

```bash
# 这个文件里全是密钥，收紧权限
chmod 600 .env.prod
```

> `DEBUG` 不用配，compose 里已经写死成 `false`。应用启动时会自检：
> 密钥没设或还是占位值就直接拒绝启动，不会带着默认密钥对外服务。

---

## 第 5 步：启动

```bash
cd /opt/couple-calendar

docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

首次构建要装依赖，大概 2–5 分钟。然后：

```bash
# 两个服务都该是 Up / healthy
docker compose -f docker-compose.prod.yml --env-file .env.prod ps

# 看日志确认迁移跑过了、没报错
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f app
```

日志里应该能看到 `Running upgrade -> ...` 两条迁移，然后 `Uvicorn running on http://0.0.0.0:8000`。

命令太长，设个别名：

```bash
echo "alias dc='docker compose -f /opt/couple-calendar/docker-compose.prod.yml --env-file /opt/couple-calendar/.env.prod'" >> ~/.bashrc
source ~/.bashrc

dc ps        # 以后就这么用
dc logs -f app
```

在服务器本机验证（此时还没配 Nginx）：

```bash
curl -i http://127.0.0.1:8000/healthz
# 应该返回 {"status":"ok"}
```

---

## 第 6 步：Nginx 反向代理

```bash
sudo apt install -y nginx

sudo cp /opt/couple-calendar/deploy/nginx.conf /etc/nginx/conf.d/couple-calendar.conf

# 去掉默认站点，否则它会抢走 80 端口的默认 server
sudo rm -f /etc/nginx/sites-enabled/default

# 测语法，必须先过
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
```

开服务器内部防火墙：

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80,443/tcp
sudo ufw --force enable
sudo ufw status
```

> **提醒**：`ufw` 管不住 Docker 发布的端口（Docker 直接写 iptables 的 DOCKER 链）。
> 本项目的 compose 把应用绑在 `127.0.0.1:8000`、数据库完全不发布端口，
> 所以从根上避开了这个坑。**不要**把 compose 里的 `127.0.0.1:` 前缀去掉。

---

## 第 7 步：用 IP 访问验证

浏览器打开 `http://你的服务器IP`，应该看到登录页。

```bash
# 命令行验证
curl -I http://你的服务器IP
curl -s http://你的服务器IP/healthz
```

打不开的排查顺序（**九成是第 1 条**）：

1. **阿里云控制台的安全组放通 80 了吗**（和服务器里的 ufw 是两层，都要开）
2. `sudo ufw status` 里有 80 吗
3. `sudo systemctl status nginx` 在跑吗
4. `dc ps` 两个容器都 healthy 吗
5. `curl http://127.0.0.1:8000/healthz` 在服务器本机通吗
   - 通 → 问题在 Nginx 或防火墙
   - 不通 → 看 `dc logs app`

---

## 第 8 步：建账号

容器里没有交互式终端方便跑脚本，直接 `exec` 进去：

```bash
dc exec app python scripts/create_users.py --username her --display-name 小美 --role female --target 8:00
dc exec app python scripts/create_users.py --username him --display-name 水牛 --role male --target 1:00
```

脚本会交互提示输密码（不显示）。**不要用 `--password` 传**，那样密码会留在 shell 历史里。

> `dc exec` 需要 TTY，如果报 "the input device is not a TTY"，用
> `dc exec -it app python scripts/create_users.py ...`

建完登录试一下，两边各填一天数据，确认亲亲账本开始结算。

---

## 第 9 步：定时提醒

服务器上有 crontab，比 Railway 那套外部 cron 简单得多 —— 直接在本机调脚本，
不走 HTTP，也不需要 `CRON_SECRET`：

```bash
crontab -e
```

加这两行：

```cron
# 每 10 分钟检查一次到期提醒（同一条提醒当天只会发一次，重复触发安全）
*/7 * * * * cd /opt/couple-calendar && docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T app python scripts/tick.py --quiet >> /var/log/couple-tick.log 2>&1

# 每天凌晨备份数据库
17 3 * * * /opt/couple-calendar/deploy/backup.sh >> /var/log/couple-backup.log 2>&1
```

```bash
# 日志文件先建好并给权限，不然 cron 写不进去
sudo touch /var/log/couple-tick.log /var/log/couple-backup.log
sudo chown "$USER" /var/log/couple-tick.log /var/log/couple-backup.log
```

> `exec -T` 的 `-T` 不能省：cron 环境没有 TTY，不加会报
> "the input device is not a TTY" 然后每次都失败。

验证：

```bash
# 先 dry-run，只报告不真的推送、也不占用当天名额
dc exec -T app python scripts/tick.py --dry-run

# 真的跑一次
dc exec -T app python scripts/tick.py

# 再跑一次 —— sent 应该是 0，这就是幂等生效了
dc exec -T app python scripts/tick.py --quiet
```

推送渠道在应用的**设置页**配，两人各配自己的：

- **Bark**（iOS）：App Store 装 Bark → 复制 device key → 粘到设置页
- **Server酱**（推到微信）：[sct.ftqq.com](https://sct.ftqq.com) 微信扫码 → 复制 SendKey

配完点「发送测试推送」，手机真收到才算通。

---

## 第 10 步：备份与恢复演练

```bash
# 手动跑一次，确认能生成文件
/opt/couple-calendar/deploy/backup.sh
ls -lh /opt/couple-backups/
```

**没验证过恢复的备份等于没有备份。** 做一次恢复演练：

```bash
# 在服务器上建个临时库，把备份灌进去
dc exec -T db createdb -U couple restore_test
gunzip -c /opt/couple-backups/couple_20261010_031700.sql.gz \
  | dc exec -T db psql -U couple -d restore_test

# 确认表和数据都在
dc exec -T db psql -U couple -d restore_test -c "\dt"
dc exec -T db psql -U couple -d restore_test -c "SELECT count(*) FROM daily_records;"

# 演练完删掉
dc exec -T db dropdb -U couple restore_test
```

> **本地备份只防「误删数据」，不防「服务器整台挂掉」。** 想防后者，
> 配 rclone 同步到阿里云 OSS（`backup.sh` 末尾有注释好的那行，取消注释即可）。

图片的字节也存在数据库里，所以这一个 dump 就包含全部数据，不用单独备份文件。

---

## 第 11 步：备案通过后 —— 绑域名 + HTTPS

备案下来之前跳过这节，用 IP 访问完全够用。

### 域名解析

阿里云 → 域名 → 解析设置 → 添加记录：

```
类型 A    主机记录 @      记录值 你的服务器IP
类型 A    主机记录 www    记录值 你的服务器IP
```

```bash
# 验证解析生效（可能要等几分钟到几小时）
dig +short 你的域名
```

### 改 Nginx 的 server_name

```bash
sudo nano /etc/nginx/conf.d/couple-calendar.conf
# 把 server_name _;  改成  server_name 你的域名 www.你的域名;

sudo nginx -t && sudo systemctl reload nginx
```

### 申请证书

```bash
sudo apt install -y certbot python3-certbot-nginx

# 自动申请并改写 Nginx 配置（会自动加 80 → 443 跳转）
sudo certbot --nginx -d 你的域名 -d www.你的域名

# 验证自动续期（Let's Encrypt 证书 90 天有效）
sudo certbot renew --dry-run
sudo systemctl list-timers | grep certbot
```

打开 `https://你的域名`，应该看到锁图标。

### ⚠️ 最后一步：打开 Secure Cookie

证书配好之后，把 `.env.prod` 里的 `SECURE_COOKIES` 改成 `true` 并重启：

```bash
sed -i 's/^SECURE_COOKIES=.*/SECURE_COOKIES=true/' /opt/couple-calendar/.env.prod
dc up -d
```

这会给会话 Cookie 加上 `Secure` 标记，浏览器就只在 HTTPS 下发送它，
中间人拿不到。**在配好 HTTPS 之前不要开**——浏览器拒绝在 `http://` 上
保存 Secure Cookie，开了会导致登录「提交后跳回登录页」而且不报任何错。

> 阿里云也提供免费 SSL 证书（控制台 → 数字证书管理服务），但要手动续期，
> 用 certbot 自动续更省心。

---

## 上线检查清单

- [ ] 阿里云安全组只放通 22 / 80 / 443
- [ ] SSH 已禁密码登录、禁 root 登录
- [ ] `.env.prod` 权限 600，三个密钥都是随机生成的
- [ ] 两个账号密码 ≥ 8 位（本地开发用的 `LocalTest1234` **绝对不要**用在线上）
- [ ] `curl http://你的域名/api/docs` 返回 404（生产应关闭接口文档）
- [ ] 数据库端口没对公网开放 —— 在**别的机器**上验证：
      `nc -zv 你的服务器IP 5432` 应该连不上
- [ ] **填一条数据 → `dc restart app` → 数据还在**（验证数据卷真的生效）
- [ ] 改一次达标值 → 历史记录的偏差值没变
- [ ] 改一次亲亲比率 → 历史结算的比率没变
- [ ] `tick.py` 连跑两次，第二次 `sent=0`
- [ ] 两人手机都收到过测试推送
- [ ] 备份跑通，且做过一次恢复演练
- [ ] 上传一张大图（>5MB）成功 —— 验证 Nginx 的 `client_max_body_size` 生效
- [ ] 国内节点 + 域名访问：ICP 备案已通过
- [ ] **配好 HTTPS 之后**，`.env.prod` 里的 `SECURE_COOKIES` 改成了 `true`
      （HTTPS 之前必须是 `false`，否则登录会静默失败）

---

## 日常运维

```bash
# 在 Mac 本地完成改动后提交并推送
git add .
git commit -m "说明这次改动"
git push origin main       # GitHub 主仓库
git push ecs main          # 推送到 ECS 上的 Git 镜像

# 再触发服务器备份、拉取和部署
ssh root@你的服务器IP 'cd /opt/couple-calendar && ./deploy/deploy.sh'

# 看状态和日志
cd /opt/couple-calendar && dc ps
dc logs -f --tail=100 app
```

本部署使用 GitHub 作为主仓库；如果 ECS 无法直接连接 GitHub，`ecs` 是服务器上的
裸仓库镜像（`/opt/git/couple-calendar.git`）。它便于服务器通过 `git pull` 更新，
但与应用同机，不能代替 GitHub 和异地数据库备份。

```bash
# 也可以直接通过 rsync 更新（不纳入 Git 版本流程）
cd /opt/couple-calendar && dc up -d --build

# 重启
dc restart app

# 每周巡检一条命令
ssh deploy@你的服务器IP '
  echo "=== 磁盘 ==="; df -h | grep -vE "tmpfs|udev"
  echo "=== 内存 ==="; free -h
  echo "=== 容器 ==="; docker compose -f /opt/couple-calendar/docker-compose.prod.yml --env-file /opt/couple-calendar/.env.prod ps
  echo "=== 最近错误 ==="; docker compose -f /opt/couple-calendar/docker-compose.prod.yml --env-file /opt/couple-calendar/.env.prod logs --since 7d app 2>&1 | grep -iE "error|traceback" | tail -20
  echo "=== 备份 ==="; ls -lht /opt/couple-backups | head -5
  echo "=== 提醒日志 ==="; tail -5 /var/log/couple-tick.log
'
```

**回滚**：

```bash
cd /opt/couple-calendar
git log --oneline -5
git reset --hard <上一个好的提交>
./deploy/deploy.sh
```

> 数据库迁移**不会**自动回滚。涉及删字段的迁移要先
> `dc exec app alembic downgrade -1`，再回滚代码。所以 `deploy.sh` 每次更新前都会先备份。

---

## 常见问题

| 现象 | 原因 | 解决 |
|---|---|---|
| 浏览器打不开，但服务器本机 curl 通 | 阿里云**安全组**没放通 80 | 控制台改安全组规则（不是服务器里的 ufw） |
| `docker pull` 超时 / 很慢 | 没配镜像加速器 | 见第 2 步，或换另一个镜像站 |
| `pip install` 很慢 | 没用国内源 | 确认 `.env.prod` 里有 `PIP_INDEX_URL` |
| 上传大图 **413 Request Entity Too Large** | Nginx 默认只给 1MB | `client_max_body_size 100M`（配置里已有，确认生效后 reload） |
| cron 里的 tick 一直失败 | `exec` 缺 `-T`，cron 没有 TTY | 命令里加 `-T` |
| 容器反复重启 | 启动就崩，多半是迁移或密钥问题 | `dc logs --tail=200 app` 看真实原因 |
| 应用起不来，日志说必须设置 SESSION_SECRET | `.env.prod` 没填或还是占位值 | 填上随机密钥，`dc up -d` |
| 时间差 8 小时 | 时区没配 | compose 里已设 `TZ=Asia/Shanghai`，确认宿主机也对：`sudo timedatectl set-timezone Asia/Shanghai` |
| 磁盘满了 | 日志 / 旧镜像 / 备份堆积 | `docker system prune -a`；`du -sh /* \| sort -h` 找大文件 |
| 内存不足被 OOM kill | 1G 小机器扛不住 | 加 swap（下方） |

**加 2G swap**（1 核 1G 的机器建议做）：

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h
```

**Pillow 报找不到 libjpeg**（理论上不会，manylinux wheel 自带）：
在 `Dockerfile` 的 `pip install` 之前加一行

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
      libjpeg62-turbo zlib1g libwebp7 && rm -rf /var/lib/apt/lists/*
```
