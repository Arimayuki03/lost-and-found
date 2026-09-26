import time

from flask import current_app

from app.utils import redis_client

# 连续失败 N 次后锁定账号（IP 限流之外的第二道防线：校园网大量用户共享 NAT 出口 IP，
# 仅按 IP 限流会误伤正常用户，也无法阻止攻击者对单个账号的低速爆破）
MAX_LOGIN_FAILURES = 5
# 锁定时长（秒）
LOCK_SECONDS = 900  # 15 分钟
# 失败计数窗口（秒）：窗口内不重置计数，窗口自然过期后从 0 重新计
FAILURE_WINDOW_SECONDS = 900

# 登录面（surface）常量：三个登录入口各自独立计数与锁定。
# 必须区分，否则用户端与超管端共享同一 Redis 键（如超管 name 与某学号撞名）会互相影响；
# 更严重的是 users 表中管理员同时也是用户（role=admin、学号相同），
# 若用户端与管理端共用键，攻击者对某学号在 /user/login 打满失败次数，
# 即可把管理员在 /admin/login 的入口锁死 15 分钟（900 秒窗口内可循环续锁），构成跨登录面 DoS。
SURFACE_USER = 'user'      # 用户端 /user/login（标识为 student_id）
SURFACE_ADMIN = 'admin'    # 管理端 /admin/login（标识为 student_id）
SURFACE_SUPER = 'super'    # 超管端 /sadmin/login（标识为 name）

# 各登录面的 Redis 键前缀：锁键 login_lock:<surface>:<标识>、失败计数键 login_failures:<surface>:<标识>
_SURFACE_PREFIXES = {
    SURFACE_USER: 'user',
    SURFACE_ADMIN: 'admin',
    SURFACE_SUPER: 'super',
}

_DEFAULT_SURFACE = SURFACE_USER  # 兼容旧签名：未显式传 surface 时按用户端处理


def _surface_prefix(surface):
    """返回登录面对应的键前缀；未知 surface 回退到默认前缀，避免拼出无前缀的裸键。"""
    return _SURFACE_PREFIXES.get(surface, _SURFACE_PREFIXES[_DEFAULT_SURFACE])


def _normalize_identifier(identifier):
    """归一化登录标识（去首尾空白 + casefold）。

    与 MySQL utf8mb4_0900_ai_ci 大小写不敏感排序规则对齐，防止大小写变体绕过锁定：
    数据库查询不区分大小写，而 Redis 键区分，不归一化时攻击者可用 Admin/ADMIN 等变体
    分散失败计数、绕过账号锁定。
    """
    if not isinstance(identifier, str):
        identifier = str(identifier)
    return identifier.strip().casefold()


def _lock_key(identifier, surface=_DEFAULT_SURFACE):
    return f"login_lock:{_surface_prefix(surface)}:{_normalize_identifier(identifier)}"


def _fail_key(identifier, surface=_DEFAULT_SURFACE):
    return f"login_failures:{_surface_prefix(surface)}:{_normalize_identifier(identifier)}"


def is_locked(identifier, surface=_DEFAULT_SURFACE):
    """账号在指定登录面是否处于锁定状态。identifier 用学号/用户名等登录主键。

    策略说明（适用于全部三个登录面）：
    - "用户不存在也计入失败"：无论账号是否真实存在，只要凭证校验失败就调用 record_failure。
      理由：(1) 若不存在的账号不计失败，攻击者可用任意不存在的学号无限低速试探而不触发
      任何锁定（每次请求换一个学号即可绕过账号锁）；(2) 统一计失败可避免通过响应时间/
      锁定行为差异进行账号枚举。
    - fail-open：Redis 异常（连接抖动、超时等）时放行并记录 error 日志，不让登录口 500。
      与 app/__init__.py 中令牌撤销检查 fail-open 的既定权衡一致：可用性优先于严格性，
      Redis 故障期间降级为仅依赖 IP 限流。
    """
    try:
        return redis_client.get(_lock_key(identifier, surface)) is not None
    except Exception as e:
        current_app.logger.error(
            f"查询账号锁定状态失败（fail-open 放行，surface={surface}, identifier={identifier}）: {str(e)}")
        return False


def record_failure(identifier, max_failures=MAX_LOGIN_FAILURES, surface=_DEFAULT_SURFACE):
    """记录指定登录面的一次登录失败；达到阈值后锁定账号。返回当前失败次数。

    异常时 fail-open：记录 error 日志并返回 0（本次不锁定），
    避免 Redis 抖动把三个登录口全部打成 500。
    """
    try:
        fail_key = _fail_key(identifier, surface)
        count = redis_client.incr(fail_key)
        # 无条件重设过期时间：INCR 与 EXPIRE 两步非原子，两步之间异常中断会残留
        # 永不过期的计数键（失败窗口形同虚设）；每次失败重设窗口可自愈历史残留键
        redis_client.expire(fail_key, FAILURE_WINDOW_SECONDS)
        if count >= max_failures:
            redis_client.setex(_lock_key(identifier, surface), LOCK_SECONDS, int(time.time()))
        return count
    except Exception as e:
        current_app.logger.error(
            f"记录登录失败失败（fail-open 不锁定，surface={surface}, identifier={identifier}）: {str(e)}")
        return 0


def clear_failures(identifier, surface=_DEFAULT_SURFACE):
    """登录成功后清除该登录面的失败计数（锁定键不主动清：短时锁定继续生效，防止已知密码的攻击者洗白计数）。

    异常时仅记录日志不清计数：下次登录失败会继续累计，不影响本次已成功的登录。
    """
    try:
        redis_client.delete(_fail_key(identifier, surface))
    except Exception as e:
        current_app.logger.error(
            f"清除登录失败计数失败（surface={surface}, identifier={identifier}）: {str(e)}")
