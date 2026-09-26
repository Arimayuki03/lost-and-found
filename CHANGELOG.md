# 更新日志

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，
版本号遵循[语义化版本](https://semver.org/lang-zh-CN/)。

## [1.0.1] - 2026-09-26

2026-09-26 全量代码审查（8 个审查维度：认证安全、业务端点、聊天/管理端、匹配调度、数据库层、管理端视图模块）后集中修复。

### Fixed（修复）

**安全类**

- **高危**：Socket.IO 四处认证路径（connect / authenticate / 事件参数 token / URL token）原先只调 `decode_token` 不触发令牌撤销检查——已登出（jti 拉黑）或被重置密码（iat 早于变更时间）的 access token 在实时通道上仍可收发私信。撤销检查抽为 `token_revocation.is_token_revoked` 公共函数（HTTP blocklist 回调与 Socket.IO 认证共用同一实现），四条认证路径收敛到统一的 `_authenticate_session_token`（顺带封住"已删除用户旧令牌继续收发私信"，并修复仅 authenticate 路径加入 `user:<id>` 个人房间导致其他路径认证的连接在首页收不到实时推送/未读角标的问题）（`app/user/chat.py`、`app/utils/token_revocation.py`、`app/__init__.py`）。
- **高危**：账号锁定与失败计数的 Redis 键用原始学号/用户名构造，而 MySQL 按大小写不敏感排序规则匹配同一账号——攻击者用 `Admin`/`ADMIN` 变体即可分散失败计数绕过 15 分钟锁定。键构造统一做 strip + casefold 归一化（`app/utils/account_lock.py`）。
- **高危**：Redis 客户端未设置任何 socket 超时，Redis 挂起（网络黑洞/进程暂停，非拒绝连接）时每个已认证请求在撤销检查处无限阻塞，全部 fail-open 降级失效。补 `socket_connect_timeout=3, socket_timeout=3, health_check_interval=30`（`app/utils/redis_client.py`）。
- **高危**：演示数据 `测试数据.sql` 全部 40 个账号（含 10 个管理员）为明文密码 `123456`，配合登录层明文兼容回退可直接登录管理端。全部替换为独立随机盐的 scrypt 哈希，并标注"仅限本地演示，禁止导入生产环境"。
- 改绑邮箱无 step-up 认证：被盗 15 分钟 access token 可先换绑邮箱再走自助重置密码实现永久接管。`POST /user/email` 补当前密码校验（与改密路径对齐；先验密码避免白白消耗一次性验证码）（`app/user/users.py`）。
- 邮箱验证码相关 Redis 键未归一化：`A@x.com`/`a@x.com` 大小写变体可绕过 60 秒重发锁与每日 10 次上限构成邮件轰炸。发送入口统一 `strip().lower()`（`app/common/email.py`）。
- `POST /user/email` 是唯一未挂 IP 限流的验证码消费端点，可被无速率作废任意邮箱验证码（定向 DoS 找回密码流程）。补 `@ip_rate_limit('user_email_change', 10, 60)`；`GET /user/profile/<id>` 同步补公开端点限流（`app/user/users.py`）。
- `X-Forwarded-For` 取最左段（客户端可伪造），在 nginx 追加式配置下全部 IP 限流可被随机 XFF 绕过；改取最右段（自家反代写入的真实 IP）（`app/utils/ratelimit.py`）。
- 登录"用户不存在"路径跳过哈希校验，响应时间差可枚举学号；两登录面（用户端/管理端）在用户不存在时执行同等代价的哑哈希校验（`app/utils/password.py`、`app/user/users.py`、`app/admin/admins.py`）。
- `socket` 版私聊发送事件补 `receiver_id`/`message` 类型防护（与 HTTP 端点对齐，非数字 ID/非字符串消息原先落入 500）（`app/user/chat.py`）。

**缺陷类**

- 匹配任务异常处理缺 `db.session.rollback()`：commit 失败（锁超时后唯一约束冲突等）后 scoped session 残留 PendingRollbackError，APScheduler 复用同一线程 session，此后每轮任务首条查询即失败，匹配功能永久瘫痪直至重启。两处 except 补回滚（`app/utils/matching_service.py`）。
- 匹配预筛选用原始名称做 quick_ratio，与归一化（去标点转小写）后的正式计算口径不一致，名称标点占比高的真实匹配被直接跳过永不进入匹配。归一化提为 `_normalize_text` 公共函数，预筛与正式计算共用（`app/utils/matching_service.py`）。
- 物品更新用 `len(data)==1` 判定"仅状态更新"：body 多带任意未知字段即误判为内容修改，已审核物品被无改动打回审核队列且响应 200（公开列表即时消失）。改用"是否携带内容字段"判定（`app/user/lost_items.py`、`found_items.py`）。
- `fromisoformat` 接受带时区时间（`Z`/`+08:00`），PyMySQL 落库静默丢弃偏移，UTC+8 用户的丢失时间被存偏 8 小时并带偏匹配算法。新增 `parse_local_datetime` 统一归一化为 naive 钟面时间，sift 时间参数同步改为"校验后转 datetime 对象再过滤"（消除 MySQL 不认的字符串导致的 500），sift 的 user_id 补 int 校验（`app/utils/page.py`、`app/user/*`、`app/common/*`）。
- `/admin/stats` 匹配成功率分子用匹配行数×2，同一物品与多条拾物匹配时重复计数，成功率可超 100% 且与 `/admin/matching/stats` 口径矛盾。改 distinct 物品数口径（`app/admin/stats.py`）。
- 统计接口 `n` 参数无下限，`n=-1` 生成负数 LIMIT 触发 500；统一夹取 1-50（`app/admin/stats.py`）。
- `query.paginate` 默认 `error_out=True`，页码越界时内部 `abort(404)` 被 `except Exception` 吞成 500（正常翻页到底即触发）；补 `error_out=False`（管理端 3 处），sift 响应回显钳制后的实际 page/size 而非原始入参（`app/admin/lost_items.py`、`found_items.py`、`admins.py`）。
- 超管"不能删除自己"防护拿 User.id 与 SuperAdmin.id 比对，两表自增撞号时删除同号普通用户被永久误拒；删除该比对（超管在 user 表无行，自删场景不存在，防误删管理员保护保留）（`app/sadmin/superadmin.py`）。
- 公告 content 无长度上限，超长触发 DataError 落入 500；创建/更新两处补 5000 上限 400（`app/admin/announcement.py`）。
- 分页排序命中白名单时缺唯一 tiebreaker，低基数列（is_completed 等）排序下翻页重复/丢行；统一追加主键次级排序（`app/utils/page.py`）。
- 页码无上限，`?page=999999999` 生成巨型 OFFSET；按 total 钳制实际上限（`app/utils/page.py`）。
- INCR 与 EXPIRE 两步非原子，故障瞬间可残留永不过期计数键（验证码尝试计数键最严重：邮箱验证功能对该地址永久损坏）；统一改为 incr 后无条件重设 TTL（自愈残留键）（`app/utils/code.py`、`ratelimit.py`、`account_lock.py`）。
- 断线（关页面/断网）不向已加入的私聊房间广播 offline，对方界面永久停留在"在线"；disconnect 时按连接房间登记补广播。已读回执推送的 read_at 改用 DB 存储值，消除 DB 会话时区与应用 UTC 不一致时的 8 小时跳变（`app/user/chat.py`）。
- 搜索接口双 LIKE 查询用 UNION 去重迫使 MySQL 建临时表+filesort，且 count/分页重复执行整个 UNION；改 OR 合并单查询（`app/common/search.py`）。
- MinIO 图片清理任务 `list_objects` 缺 `recursive=True`，avatars/ 子目录对象以目录伪条目出现，头像孤儿文件永不清理（`app/utils/scheduler.py`）。
- Socket.IO 事件认证后 User 存在性未校验（已删除用户旧令牌可继续收发私信）——随统一认证函数一并修复（`app/user/chat.py`）。

### Changed（变更）

- SQLAlchemy 模型与 `lost_and_found.sql` 对齐，消除 schema 漂移：User 补 `updated_at`、各 URL/密码列长度对齐 varchar(255)、ChatMessage.message 对齐 varchar(500)、外键显式声明 ondelete（物品 CASCADE、聊天/反馈/匹配 RESTRICT）、布尔列补 server_default（`app/models.py`）。
- `lost_and_found.sql` 索引修正：found_item 补 category/is_under_review 索引与 lost_item 对称，两表补 (is_under_review, created_at) 复合索引覆盖公开列表默认路径，chat_message 补 (receiver_id, is_read) 与 (sender_id, receiver_id, timestamp) 复合索引；删除 user.idx_student_id（与唯一键完全重叠）与 super_admins 的冗余 UNIQUE id。
- `docker-compose.yml` 加固：Redis 默认启用 requirepass + AOF；MinIO 凭据改为环境变量可覆盖；MySQL 8 纳入编排（utf8mb4/UTC/回环绑定/建库脚本自动导入）。
- 匹配服务异常处理补 rollback、预筛口径统一（详见 Fixed）。

### Known Issues（暂不修复，已记录）

- 公开列表/详情端点输出 contact 与 user_id（失物招领业务需要公开联系方式触达失主，视为设计决策；已有 IP 限流缓解批量抓取，后续可考虑脱敏展示）。
- 匹配通知邮件逐封串行新建 SMTP 连接，积压大量匹配时总耗时可超锁 TTL 引发重复发信窗口（当前规模可接受，后续可改单连接复用 + 发送去重键）。
- 匹配任务全表加载 + O(n×m) 两两比较，数千条物品后单轮耗时显著增长（校园规模可接受）。
- 测试覆盖：`tests/test_smoke.py` 以源码字符串 grep 与关键路径断言为主，匹配算法/邮件通知/清理任务缺行为级测试（本轮修复已保持 18/18 通过，行为测试列为后续工作）。

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
