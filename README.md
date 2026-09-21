<div align="center">

# 🎒 校园失物招领平台 · 后端

**基于 Flask 3 的校园失物招领平台后端服务**

失物/拾物发布 · 智能匹配与邮件通知 · 实时私信 · 审核工作流 · 完善的安全加固

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.1-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![MySQL](https://img.shields.io/badge/MySQL-8.0-4479A1?logo=mysql&logoColor=white)](https://www.mysql.com/)
[![Redis](https://img.shields.io/badge/Redis-DC382D?logo=redis&logoColor=white)](https://redis.io/)
[![MinIO](https://img.shields.io/badge/MinIO-C72E49?logo=minio&logoColor=white)](https://min.io/)
[![Socket.IO](https://img.shields.io/badge/Socket.IO-010101?logo=socketdotio&logoColor=white)](https://flask-socketio.readthedocs.io/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Release](https://img.shields.io/github/v/release/Arimayuki03/lost_and_found?label=Release)](../../releases)

</div>

---

## 📖 简介

用户可以发布失物（丢失物品）和拾物（捡到的物品）信息，系统通过相似度算法自动匹配置物与失主，并通过邮件通知双方；同时提供实时私信、物品审核、公告轮播图管理、数据统计等完整功能。

## 📦 相关仓库

| 仓库 | 说明 | 默认端口 |
| --- | --- | --- |
| [lost-and-found](https://github.com/Arimayuki03/lost_and_found) | **本项目**：Flask 后端（API、Socket.IO、匹配算法、邮件通知） | 5000 |
| [lost-and-found-user](https://github.com/Arimayuki03/lost_and_found_user) | 用户端前端（uni-app Vue3，H5 / 微信小程序 / App） | 5173（CLI H5） |
| [lost-and-found-admin](https://github.com/Arimayuki03/lost_and_found_admin) | 管理后台前端（Vue 3 + Element Plus） | 8001 |

## ✨ 功能特性

- 📝 **失物/拾物发布与管理**：发布、修改、删除、查询自己的失物与拾物信息，支持图片上传（自动压缩）；
- 🤝 **自动匹配与邮件通知**：定时任务周期性对失物与拾物做多维度加权相似度匹配，匹配成功自动发送邮件通知双方；
- 🛡️ **先审核后展示**：新发布物品进入待审核状态，管理员审核通过后才在公共列表展示并参与匹配；
- 💬 **实时私信**：基于 Flask-SocketIO 的点对点私聊，支持未读计数、已读回执、在线状态；
- 👥 **三类角色权限体系**：普通用户 / 管理员 / 超级管理员，独立的登录入口与权限装饰器；
- 🧷 **内容安全**：接入腾讯云 TIIA 进行图像打标签与不良内容检测（注册头像、物品图片）；
- 🔐 **安全加固**：JWT 双令牌认证、密码修改后旧令牌自动撤销、登录失败账号锁定、IP 限流、日志敏感参数脱敏；
- 🏢 **运营支撑**：公告、首页轮播图、意见反馈、平台数据统计。

## 🧰 技术栈

| 类别 | 技术 |
| --- | --- |
| Web 框架 | Flask 3.1.0 + Flask-SocketIO 5.3.6（实时聊天） |
| 数据库 | MySQL（SQLAlchemy 2.0.38 + Flask-SQLAlchemy 3.1.1 + Flask-Migrate 4.0.7 / Alembic 1.14.1，驱动 PyMySQL 1.1.1） |
| 缓存 | Redis（redis-py 5.2.1，邮箱验证码存储、限流、账号锁定、令牌撤销） |
| 对象存储 | MinIO（minio-py 7.2.15，物品图片、头像、轮播图） |
| 认证 | Flask-JWT-Extended 4.6.0（access token 15 分钟 / refresh token 30 天） |
| 定时任务 | APScheduler 3.11.0 |
| 第三方服务 | 腾讯云 TIIA（tencentcloud-sdk-python 3.0.1300，图像打标签、不良内容检测）、SMTP 邮件服务 |
| 图像处理 | Pillow 12.3.0（上传压缩，PNG 转 JPEG，质量自适应降到 1MB 以内） |
| 其他 | Flask-Cors 4.0.1、python-dotenv 1.0.1、requests 2.32.3、Werkzeug 3.1.3 |

## 🚀 快速开始

### 环境要求

- Python 3.10+
- MySQL 8.0（本地服务或远程实例）
- Docker（用于一键启动 MinIO 与 Redis）

### 1. 安装依赖

```bash
# 克隆仓库
git clone https://github.com/Arimayuki03/lost_and_found.git
cd lost-and-found

# 创建虚拟环境
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env` 并填入实际值：

```bash
cp .env.example .env
```

各变量含义见下方[环境变量说明](#️-环境变量说明)。`.env` 已被 `.gitignore` 忽略，切勿提交真实密钥。

### 3. 启动 MinIO 与 Redis

```bash
docker compose up -d
```

将启动 MinIO（9000/9001 端口，仅绑定 127.0.0.1）与 Redis（6379 端口），数据持久化在 Docker 卷中。MySQL 可复用本机服务。

### 4. 初始化数据库

创建数据库后导入建库脚本（也可选导入 `测试数据.sql` 获得一批演示数据）：

```sql
CREATE DATABASE lost_and_found DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
```

```bash
mysql -u root -p lost_and_found < lost_and_found.sql
mysql -u root -p lost_and_found < 测试数据.sql   # 可选：演示数据
```

### 5. 启动

```bash
python run.py
```

服务运行在 `http://0.0.0.0:5000`，Socket.IO 与 HTTP 共用端口。启动时会自动：

- 初始化日志目录 `logs/`（非 debug 模式写入 `logs/app.log`，10MB 轮转）；
- 启动 APScheduler 定时任务；
- 根据环境变量自动创建超级管理员账号（已存在则跳过）。

### 6. 运行测试

```bash
.venv\Scripts\python.exe tests/test_smoke.py   # Windows
python tests/test_smoke.py                       # Linux / macOS
```

冒烟测试使用 SQLite 内存库与 Redis fail-open 降级，无需真实 MySQL/Redis/MinIO 即可运行，覆盖鉴权穿越、登录类型校验、登出撤销、统计分桶、匹配过滤、限流装饰器等关键回归（18 项断言）。

## 🏗️ 项目结构

```text
lost_and_found/
├── run.py                    # 启动入口（socketio.run，端口 5000）
├── config/
│   └── config.py             # 全局配置（读取环境变量）
├── app/
│   ├── __init__.py           # 应用工厂 create_app、蓝图注册、超管初始化、令牌撤销检查
│   ├── models.py             # 全部数据模型
│   ├── user/                 # 用户端接口（/user）
│   │   ├── users.py          #   注册、登录、个人信息、头像、邮箱、重置密码
│   │   ├── lost_items.py     #   失物发布/修改/删除/我的列表/详情
│   │   ├── found_items.py    #   拾物发布/修改/删除/我的列表/详情
│   │   ├── chat.py           #   私信（HTTP + Socket.IO）
│   │   └── feedback.py       #   意见反馈
│   ├── admin/                # 管理端接口（/admin）
│   │   ├── admins.py         #   管理员登录、用户管理
│   │   ├── lost_items.py     #   失物审核/筛选/删除
│   │   ├── found_items.py    #   拾物审核/筛选/删除
│   │   ├── matching.py       #   手动触发匹配、匹配统计
│   │   ├── stats.py          #   数据统计
│   │   ├── feedback.py       #   反馈查看/删除
│   │   ├── announcement.py   #   公告管理
│   │   └── carousel_image.py #   轮播图管理
│   ├── sadmin/               # 超级管理员接口（/sadmin）
│   │   └── superadmin.py     #   登录、管理员增删查、用户管理、用户统计
│   ├── common/               # 公共接口（/common）
│   │   ├── lost_items.py     #   已审核失物公开列表/筛选/详情
│   │   ├── found_items.py    #   已审核拾物公开列表/筛选/详情
│   │   ├── search.py         #   关键词搜索（名称+描述）
│   │   ├── announcement.py   #   公告查询
│   │   ├── carousel_image.py #   轮播图查询
│   │   ├── check_user.py     #   邮箱/学号占用检查
│   │   ├── email.py          #   发送邮箱验证码
│   │   ├── token.py          #   刷新 access token
│   │   └── photo.py          #   图片上传、图像打标签、不良内容检测
│   └── utils/                # 工具与服务
│       ├── matching_service.py   # 失物-拾物匹配算法 + 匹配邮件通知
│       ├── scheduler.py          # APScheduler 定时任务、MinIO 失效图片清理
│       ├── email_service.py      # 验证码邮件
│       ├── code.py               # 验证码校验逻辑（Redis）
│       ├── redis_client.py       # Redis 客户端
│       ├── decorators.py         # admin_required / user_required / super_admin_required
│       ├── page.py               # 通用分页/排序
│       ├── ratelimit.py          # 基于 Redis 的接口限流
│       ├── account_lock.py       # 登录失败账号锁定（按登录面独立计数）
│       ├── token_revocation.py   # 旧令牌撤销（密码变更时间戳 + 登出 jti 拉黑）
│       ├── log_sanitize.py       # 日志敏感参数（SQL 绑定参数）脱敏
│       └── password.py           # 密码哈希
├── lost_and_found.sql        # 建库脚本
├── 测试数据.sql               # 演示数据脚本
├── docker-compose.yml        # MinIO + Redis 本地开发环境
└── requirements.txt          # Python 依赖
```

## 🎭 角色与权限

系统有三类角色，通过两个权限装饰器控制访问（`app/utils/decorators.py`）：

| 角色 | 说明 | 登录方式 |
| --- | --- | --- |
| 普通用户 | 发布/管理自己的失物拾物、私聊、反馈 | 学号 + 密码，`/user/login` |
| 管理员 | `user` 表中 `is_admin=True` 的用户，审核物品、管理用户与内容 | 学号 + 密码，`/admin/login` |
| 超级管理员 | 独立 `super_admins` 表，启动时按环境变量自动创建，可添加管理员 | 用户名 + 密码，`/sadmin/login` |

物品采用**先审核后展示**的流程：新发布的物品 `is_under_review=True`，管理员审核通过（`review`）后才出现在公共列表、参与自动匹配；`is_completed` 标记物品是否已完成（找回/归还）。

## 🌐 API 概览

API 按蓝图划分为四个模块（注册见 `app/__init__.py`）：

| 模块 | 路由前缀 | 说明 | 鉴权 |
| --- | --- | --- | --- |
| 公共接口 | `/common` | 物品公开列表/筛选/详情、搜索、公告、轮播图、邮箱/学号检查、验证码、图片上传与内容安全、令牌刷新 | 无需登录 |
| 用户端 | `/user` | 注册登录、个人信息、失物/拾物管理、实时私信、意见反馈 | JWT |
| 管理端 | `/admin` | 物品审核、用户管理、匹配触发、统计、公告/轮播图/反馈管理 | 管理员 JWT |
| 超管端 | `/sadmin` | 超管登录、管理员增删查、用户管理、用户统计 | 超管 JWT |

### 公共接口 `/common`（无需登录）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/common/lost-items` · `/sift` · `/<id>` | 已审核失物列表（分页）/ 筛选 / 详情 |
| GET | `/common/found-items` · `/sift` · `/<id>` | 已审核拾物列表 / 筛选 / 详情 |
| GET | `/common/search?query=&type=lost 或 found` | 按关键词搜索（名称 + 描述） |
| GET | `/common/announcements` · `/<id>` | 公告列表 / 详情 |
| GET | `/common/carousel-images` · `/<id>` | 轮播图列表 / 详情 |
| POST | `/common/emails` · `/student-ids` | 检查邮箱 / 学号是否已被注册 |
| POST | `/common/emails/verification` | 发送邮箱验证码（Redis 90 秒有效） |
| POST | `/common/refresh` | 刷新 access token |
| POST | `/common/logout` | 登出并撤销当前令牌（可选携带 refresh_token 一并撤销） |
| POST | `/common/images/upload` · `/images/upload-avatar` | 上传图片 / 头像（压缩后存入 MinIO，返回 URL） |
| POST | `/common/images/labels` | 腾讯云图像打标签（返回一二级类别） |
| POST | `/common/images/inappropriate-content` | 不良内容检测（注册/换头像时调用） |

### 用户端 `/user`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/user/register` | 注册（需邮箱验证码；头像会做不良内容检测） |
| POST | `/user/login` | 登录，返回 access/refresh token 与用户信息 |
| GET / PUT | `/user/profile` | 获取 / 修改个人信息（JWT） |
| GET | `/user/profile/<user_id>` | 查看他人公开信息（昵称、头像） |
| PUT | `/user/avatar` | 修改头像（含不良内容检测；URL 未变跳过检测，IP 限流 10 次/分钟） |
| POST | `/user/email` · `/user/password` | 修改邮箱（需新邮箱验证码）/ 重置密码（邮箱验证码） |
| POST / PUT / DELETE | `/user/lost-items[/<id>]` | 发布 / 修改 / 删除失物 |
| GET | `/user/lost-items` · `/<id>/detail` | 我的失物列表 / 详情 |
| POST / PUT / DELETE | `/user/found-items[/<id>]` | 发布 / 修改 / 删除拾物 |
| GET | `/user/found-items` · `/<id>/detail` | 我的拾物列表 / 详情 |
| POST | `/user/chat/message` | HTTP 方式发送私信 |
| GET | `/user/chat/history/<receiver_id>` | 与某人的聊天记录（分页） |
| POST | `/user/chat/mark/<message_id>` · `/user/chat/read/<partner_id>` | 标记消息已读 / 会话已读 |
| GET | `/user/chat/unread-count` · `/user/chat/contacts` | 未读消息统计 / 联系人列表 |
| POST / GET | `/user/feedback` | 提交 / 查看我的反馈 |

### 管理端 `/admin`（`admin_required`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/admin/login` | 管理员登录 |
| GET | `/admin/users` · `/<id>` | 用户列表（分页排序）/ 详情 |
| PUT / DELETE | `/admin/users/<id>` | 修改 / 删除用户（不可删除管理员） |
| POST | `/admin/users/<id>/reset-password` | 重置用户密码 |
| GET | `/admin/lost-items` · `/unreviewed` · `/sift` | 失物列表 / 待审核 / 筛选 |
| PUT | `/admin/lost-items/<id>/review` · `/cancel-review` | 审核通过 / 撤销审核 |
| DELETE | `/admin/lost-items/<id>` | 删除失物 |
| GET | `/admin/found-items` 等同上 | 拾物管理（同失物） |
| POST | `/admin/run` | 手动触发一次失物匹配（后台线程执行） |
| GET | `/admin/stats` · `/lost-items/stats` · `/found-items/stats` · `/matching/stats` | 平台总体与分类维度统计 |
| GET / DELETE | `/admin/feedbacks[/<id>]` | 反馈列表 / 删除 |
| GET / POST / PUT / DELETE | `/admin/announcements[/<id>]` | 公告管理 |
| GET / POST / PUT / DELETE | `/admin/carousel-images[/<id>]` | 轮播图管理 |

### 超级管理员 `/sadmin`（`super_admin_required`）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/sadmin/login` | 超管登录 |
| POST / GET | `/sadmin/admins` | 添加 / 查询管理员 |
| GET | `/sadmin/users` · `/sadmin/users/stats` | 用户列表（分页）/ 用户统计 |
| PUT / DELETE | `/sadmin/users/<id>` | 修改 / 删除用户 |

## 💬 实时私信（Socket.IO）

连接地址 `ws://<host>:5000`，支持三种认证方式：连接时 URL 参数 `?token=<access_token>`、`authenticate` 事件、或在事件数据中携带 `token` / `authorization` 字段。私聊房间命名格式为 `chat:<小ID>-<大ID>`（双方用户 ID 排序拼接）。

| 客户端发出事件 | 说明 |
| --- | --- |
| `authenticate` | 携带 token 完成认证 |
| `join_private_chat` | 加入私聊房间（校验房间成员身份） |
| `leave_private_chat` | 离开房间并广播下线状态 |
| `send_private_message` | 发送私信（落库 + 房间内广播，限 500 字） |
| `notify_message_read_private` | 通知对方消息已读 |

| 服务端下发事件 | 说明 |
| --- | --- |
| `receive_private_message` | 房间内收到新消息 |
| `message_sent` | 发送成功回执（含临时消息 ID 匹配） |
| `private_message_read` | 对方已读通知 |
| `user_status_change` | 房间成员上线/下线 |
| `join_private_chat_result` / `authenticate_result` / `error` | 各类操作结果与错误 |

## ⏰ 定时任务（APScheduler）

| 任务 | 周期 | 说明 |
| --- | --- | --- |
| 失物匹配 | 每 5 分钟 | 对所有已审核、未完成的失物与拾物两两计算相似度，达标则写入 `item_match` 并发邮件通知双方 |
| 失效图片清理 | 每 1 小时 | 对比 MinIO 桶内文件与数据库中引用的图片 URL，删除无引用的孤立文件 |

管理员也可通过 `POST /admin/run` 手动触发一次匹配。

## 🎯 匹配算法

`app/utils/matching_service.py` 基于 `difflib.SequenceMatcher` 实现多维度加权相似度匹配，只处理**已审核且未完成**的物品，并跳过已有匹配记录的对：

| 维度 | 权重 | 阈值 |
| --- | --- | --- |
| 名称相似度 | 0.7 | 0.4 |
| 类别相似度 | 0.1 | 0.2 |
| 地点相似度 | 0.1 | 0.1 |
| 时间相似度 | 0.1 | 0.2（7 天内线性衰减） |

任一维度低于阈值即提前剪枝跳过；总体相似度 = 各维度加权和，达到 **0.5** 即判定匹配成功。时间相似度按 `1 - 相差天数/7` 计算，超过 7 天为 0。

匹配成功后向失物用户发送「您的失物可能已被找到」、向拾物用户发送「您拾到的物品可能已找到失主」的 HTML 邮件，包含双方物品信息、各维度相似度百分比与联系方式，并将匹配记录标记为已通知。

## ⚙️ 环境变量说明

与 `.env.example` 保持一致，复制后填入实际值：

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `FLASK_DEBUG` | 否 | 调试开关；生产必须为 `0`，仅本地开发设 `1` |
| `SUPER_ADMIN_NAME` | 是 | 超级管理员账号（首次启动自动创建，仅缺失时生效） |
| `SUPER_ADMIN_PASSWORD` | 是 | 超级管理员初始密码 |
| `SECRET_KEY` | 是 | Flask 会话签名密钥，生产环境用 `openssl rand -hex 32` 生成 |
| `JWT_SECRET_KEY` | 是 | JWT 签名密钥，须与 `SECRET_KEY` 使用不同的随机值 |
| `DATABASE_URL` | 是 | 数据库连接串，如 `mysql+pymysql://用户名:密码@主机:3306/库名?charset=utf8mb4` |
| `MINIO_ENDPOINT` | 是 | MinIO 服务地址，如 `127.0.0.1:9000` |
| `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | 是 | MinIO 访问凭证 |
| `MINIO_BUCKET_NAME` | 是 | MinIO 存储桶名 |
| `SMTP_SERVER` / `SMTP_PORT` | 是 | SMTP 邮件服务地址与端口（发送邮箱验证码） |
| `EMAIL_ADDRESS` / `EMAIL_PASSWORD` | 是 | 发件邮箱与授权码 |
| `TENCENT_CLOUD_API_KEY` / `TENCENT_CLOUD_API_SECRET` | 是 | 腾讯云内容安全（头像/图片审核接口）凭证 |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_DB` | 否 | Redis 连接信息，默认 `localhost:6379`，DB `0` |
| `REDIS_PASSWORD` | 否 | Redis 密码（生产环境建议开启） |
| `TRUST_PROXY_HEADERS` | 否 | 仅当部署在可信反向代理之后设为 `1`，限流取真实 IP |
| `CORS_ORIGINS` | 否 | CORS 白名单，逗号分隔；留空或 `*` 回退为 `*`，仅限本地开发，生产必须收敛为实际前端域名 |

## 🔒 安全与注意事项

- 密码使用 werkzeug 哈希存储（详见 `app/utils/password.py`）；数据库中的历史明文密码会在该用户下次登录成功时自动升级为哈希。
- 登录安全：连续失败 5 次锁定账号 15 分钟（用户端/管理端/超管端独立计数，见 `app/utils/account_lock.py`），并配有基于 Redis 的 IP 限流（`app/utils/ratelimit.py`）。
- 令牌安全：修改密码后签发时间早于变更时刻的旧令牌自动失效；登出时当前令牌按 jti 拉黑立即失效，超管令牌同样受登出撤销约束（见 `app/utils/token_revocation.py`）；用户端接口按 `user_required` 校验 role claim，拒绝超管令牌穿越；日志中的 SQL 绑定参数已统一脱敏（`app/utils/log_sanitize.py`）。
- Werkzeug 调试器默认关闭（安全考虑，`0.0.0.0` 上开启等同于远程代码执行入口）；本机临时调试时以 `FLASK_DEBUG=1` 启动。
- 本地开发可用 `docker compose up -d` 一键启动 MinIO（9000/9001）与 Redis（6379）；MinIO/Redis 端口仅绑定 `127.0.0.1`，生产部署请按需调整并配置 `REDIS_PASSWORD`。
- 日志写入 `logs/` 目录（10MB 轮转）；`logs/`、`migrations`、`.env` 均已在 `.gitignore` 中忽略。

## 🤝 贡献

欢迎提交 Issue 与 Pull Request！贡献流程与规范请参阅 [CONTRIBUTING.md](CONTRIBUTING.md)。安全漏洞请勿公开提交，参见 [SECURITY.md](SECURITY.md)。

## 📄 License

[MIT](LICENSE) © 2026-Present Arimayuki03
