# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [1.0.0] - 2026-09-21

首个正式开源版本。以下为自初始提交以来包含的全部内容：

### Added（新增）

- 初始开源版本：校园失物招领平台后端服务。
- 用户端：注册登录（邮箱验证码）、个人信息与头像管理、失物/拾物发布管理、实时私信（Socket.IO）、意见反馈。
- 管理端：物品先审后展、用户管理、手动触发匹配、平台数据统计、公告与轮播图管理。
- 超管端：独立登录入口、管理员增删查、用户管理与统计。
- 自动匹配：APScheduler 定时执行多维度加权相似度匹配，匹配成功邮件通知双方；支持手动触发。
- 内容安全：腾讯云 TIIA 图像打标签与不良内容检测；图片上传压缩。
- 安全加固：JWT 双令牌、密码修改后旧令牌撤销、登录失败账号锁定、接口限流、日志敏感参数脱敏、密码哈希存储。
- 配套：Docker Compose 本地开发环境（MinIO + Redis）、建库脚本与演示数据、MIT License 开源协议。

### Fixed（修复，2026-09-20 安全审查后集中修复）

- **高危**：用户端 22 个 HTTP 端点原先只挂裸 `@jwt_required()`，超管令牌可穿越为同 ID 普通用户；新增 `user_required` 装饰器（拒绝超管 role claim + 校验 User 存在）并全部替换（`app/utils/decorators.py`、`app/user/*`）。
- **高危配套**：`POST /common/logout` 新增服务端登出撤销（jti 拉黑，超管令牌同样生效），与时间戳撤销机制并存（`app/utils/token_revocation.py`、`app/__init__.py`）。
- 管理端登录补齐 `student_id`/`password` 的类型与长度校验，非字符串入参返回 400（原先抛 `AttributeError` 致 500），与另两个登录面对齐（`app/admin/admins.py`）。
- `PUT /user/avatar` 补 IP 限流（10 次/分钟），并增加"头像 URL 未变跳过付费内容检测"防重入，与超管版逻辑对齐（`app/user/users.py`）。
- `leave_private_chat` Socket 事件不再调用 `disconnect()` 掐断整条连接，仅离开房间并通知对方；前端每次离房不再被强制断线（`app/user/chat.py`）。
- 月度统计分桶由 `now − timedelta(days=i*30)` 改为日历月算法，消除日期不落整月边界时的重复月份覆盖（`app/admin/stats.py`，新增 `build_calendar_month_buckets` 纯函数）。
- 匹配任务不再硬编码过滤 `is_completed == False`，`is_completed` 为 NULL 的拾物记录也参与匹配（`app/utils/matching_service.py`）。
- 管理端"待审核（/unreviewed）"与"高级筛选（/sift）"端点补齐 `keyword` 查询参数，支持与普通列表一致的关键词搜索（`app/admin/lost_items.py`、`found_items.py`）。
- `/common` 公开匿名端点（列表/详情/搜索/公告/轮播图）补齐基于 Redis 的 IP 限流，与登录/检查接口的限流策略一致（`app/common/*`）。
- 超管 `delete_user` 补双重保护：禁止删除管理员账号、禁止删除自己（`app/sadmin/superadmin.py`）。
- MinIO 配置缺失时应用可正常启动：客户端改为惰性初始化，未配置时存储相关功能返回 503 / 清理任务安全跳过，不再在导入阶段抛 `TypeError`（`app/utils/scheduler.py`、`app/common/photo.py`）。
- 收敛 PII 日志：失物/拾物更新接口不再将整个请求体写入日志（`app/user/lost_items.py`、`found_items.py`）。
- 删除死代码 `send_password_reset_email`（全项目 0 调用，`app/utils/email_service.py`）。
- 新增后端冒烟测试 `tests/test_smoke.py`（SQLite 内存库 + Redis fail-open，18 项断言覆盖上述修复的回归）。

### Changed（变更）

- 令牌撤销检查顺序调整：`check_if_token_revoked` 先查 jti 拉黑集合再做超管 role 跳过，超管登出后令牌同样立即失效（`app/__init__.py`）。
