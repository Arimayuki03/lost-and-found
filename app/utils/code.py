import hmac

from flask import current_app

from app.utils import redis_client

# 同一验证码最多允许的校验尝试次数，超过后验证码作废（防 6 位数字码被爆破）
MAX_VERIFY_ATTEMPTS = 5
# 尝试计数窗口（秒），需覆盖验证码 90 秒有效期
ATTEMPT_WINDOW_SECONDS = 300


# 验证邮箱验证码逻辑
def verify_email_logic(email, code):
    attempt_key = f"email_verification_attempts:{email}"

    # 尝试次数超限后直接作废验证码
    attempts = redis_client.get(attempt_key)
    if attempts is not None and int(attempts) >= MAX_VERIFY_ATTEMPTS:
        redis_client.delete(f"email_verification:{email}")
        redis_client.delete(attempt_key)
        return False, "尝试次数过多，验证码已失效，请重新获取"

    # 从 Redis 中获取存储的验证码
    stored_code = redis_client.get(f"email_verification:{email}")

    # 检查验证码是否存在
    if stored_code is None:
        return False, "验证码已过期或未找到"

    # 检查验证码是否匹配（常量时间比较，避免时序侧信道）
    if not hmac.compare_digest(str(stored_code), str(code)):
        try:
            redis_client.incr(attempt_key)
            # 无条件重设过期时间：INCR 与 EXPIRE 两步非原子，两步之间异常中断会残留
            # 永不过期的计数键（5 次尝试上限形同虚设）；每次尝试重设窗口可自愈历史残留键
            redis_client.expire(attempt_key, ATTEMPT_WINDOW_SECONDS)
        except Exception as e:
            # fail-closed：无法记录尝试次数时不能放行（否则可无限爆破），记日志后按验证失败处理，
            # 但保留"验证码无效"之外的独立提示便于区分服务异常
            current_app.logger.error(f"记录验证码尝试次数失败: {str(e)}")
            return False, "验证服务异常，请稍后再试"
        return False, "验证码无效"

    # 验证成功后删除验证码与尝试计数
    redis_client.delete(f"email_verification:{email}")
    redis_client.delete(attempt_key)
    return True, "邮箱验证成功"
