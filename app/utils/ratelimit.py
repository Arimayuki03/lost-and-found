import os

from functools import wraps

from flask import jsonify, request, current_app

from app.utils import redis_client

# 仅当部署在可信反向代理之后（nginx 等）才设 TRUST_PROXY_HEADERS=1，
# 此时 X-Forwarded-For 才可信；直连场景下信任该头等于限流可被任意伪造绕过
_TRUST_PROXY_HEADERS = os.getenv('TRUST_PROXY_HEADERS', '').strip().lower() in ('1', 'true', 'yes')


def _get_client_ip():
    if _TRUST_PROXY_HEADERS:
        # 取最右段：nginx 的 $proxy_add_x_forwarded_for 是"追加"语义，最右段由自家可信反代写入
        # （真实客户端 IP 或上一跳），最左段是客户端自带的可伪造头；单层反代部署下最右段即真实 IP。
        # 多层代理部署需按可信代理层数从右往左回退相应跳数（TRUSTED_PROXY_HOPS，暂未支持）。
        forwarded = request.headers.get('X-Forwarded-For', '')
        if forwarded:
            return forwarded.split(',')[-1].strip()
    return request.remote_addr or 'unknown'


def ip_rate_limit(prefix, max_requests, window_seconds):
    """
    基于 Redis 的客户端 IP 限流装饰器。
    prefix 用于区分接口；同一 IP 在 window_seconds 窗口内超过 max_requests 次返回 429。
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            ip = _get_client_ip()
            key = f"ratelimit:{prefix}:{ip}"

            try:
                current = redis_client.incr(key)
                # 无条件重设过期时间：INCR 与 EXPIRE 两步非原子，两步之间异常中断会残留
                # 永不过期的计数键（限流窗口形同虚设）；每次请求重设窗口可自愈历史残留键
                redis_client.expire(key, window_seconds)
            except Exception as e:
                # fail-open：Redis 异常时放行并记录 error 日志，不让被装饰的登录口直接 500，
                # 与 account_lock / 令牌撤销的 fail-open 权衡一致（可用性优先，降级为无限流）
                current_app.logger.error(f"IP 限流器 Redis 异常（fail-open 放行，key={key}）: {str(e)}")
                return fn(*args, **kwargs)

            if current > max_requests:
                return jsonify({"error": "请求过于频繁，请稍后再试"}), 429

            return fn(*args, **kwargs)
        return wrapper
    return decorator
