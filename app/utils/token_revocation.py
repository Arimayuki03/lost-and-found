import time

from flask import current_app

from app.utils import redis_client

# 密码变更撤销标记的 TTL：需覆盖 refresh token 的 30 天有效期，取 31 天
PWD_CHANGED_TTL_SECONDS = 31 * 86400

# jti 拉黑标记 TTL 的兜底值：令牌缺少 exp 时使用，避免拉黑键永不过期堆积
REVOKED_JTI_FALLBACK_TTL_SECONDS = 86400


def mark_user_tokens_revoked(user_id):
    """记录用户密码变更时间戳；签发时间早于该时刻的令牌会在 blocklist 检查中被拒绝。

    返回是否写入成功：Redis 异常时仅记录 error 日志不向上抛出，由调用方决定密码变更是否
    继续落地（调用方应先写标记再 commit，失败则回滚，保证"密码变更与撤销标记要么都成功要么都不做"）。
    """
    try:
        redis_client.setex(f"pwd_changed_at:user:{user_id}", PWD_CHANGED_TTL_SECONDS, int(time.time()))
        return True
    except Exception as e:
        # 调度器等请求上下文之外调用时 current_app 不可用，退化为直接输出，保证本函数自身不抛异常
        try:
            current_app.logger.error(f"写入令牌撤销标记失败（user_id={user_id}）: {str(e)}")
        except RuntimeError:
            print(f"写入令牌撤销标记失败（user_id={user_id}）: {str(e)}")
        return False


def _revoke_jti(claims):
    """按 claims 中的 jti 写入拉黑标记，TTL 到令牌自然过期为止（多留 60 秒余量覆盖时钟偏差）。

    返回是否写入成功：Redis 异常时仅记录 error 日志不向上抛出（fail-open，
    与时间戳撤销的可用性优先策略一致），登出响应照常返回。
    """
    try:
        jti = claims.get('jti')
        if not jti:
            return False
        exp = claims.get('exp')
        if exp:
            ttl = int(float(exp) - time.time())
            if ttl <= 0:
                # 令牌已自然过期，blocklist 检查不再命中，无需写入
                return True
            ttl += 60
        else:
            ttl = REVOKED_JTI_FALLBACK_TTL_SECONDS
        redis_client.setex(f"revoked_jti:{jti}", ttl, 1)
        return True
    except Exception as e:
        try:
            current_app.logger.error(f"写入令牌 jti 拉黑标记失败: {str(e)}")
        except RuntimeError:
            print(f"写入令牌 jti 拉黑标记失败: {str(e)}")
        return False


def revoke_token():
    """登出撤销：将当前请求已验证的 access token 的 jti 加入拉黑集合。

    与时间戳撤销（mark_user_tokens_revoked）互补：时间戳撤销面向"该用户全部旧令牌"，
    本函数面向"单个令牌"，且对超管令牌同样生效（blocklist 检查中先查 jti 拉黑集合）。
    """
    try:
        from flask_jwt_extended import get_jwt
        claims = get_jwt()
    except Exception as e:
        try:
            current_app.logger.error(f"读取当前令牌 claims 失败，跳过登出撤销: {str(e)}")
        except RuntimeError:
            print(f"读取当前令牌 claims 失败，跳过登出撤销: {str(e)}")
        return False
    return _revoke_jti(claims)


def revoke_refresh_token(raw_refresh_token):
    """登出时可选撤销 refresh token：解码客户端随请求体传入的令牌并拉黑其 jti。

    令牌缺失、格式非法或已过期时记 warning 并返回 False，不影响登出响应。
    """
    if not raw_refresh_token or not isinstance(raw_refresh_token, str):
        return False
    try:
        from flask_jwt_extended import decode_token
        claims = decode_token(raw_refresh_token)
    except Exception as e:
        try:
            current_app.logger.warning(f"refresh token 解码失败，跳过撤销: {str(e)}")
        except RuntimeError:
            print(f"refresh token 解码失败，跳过撤销: {str(e)}")
        return False
    return _revoke_jti(claims)
