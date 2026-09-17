import hmac

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
        count = redis_client.incr(attempt_key)
        if count == 1:
            redis_client.expire(attempt_key, ATTEMPT_WINDOW_SECONDS)
        return False, "验证码无效"

    # 验证成功后删除验证码与尝试计数
    redis_client.delete(f"email_verification:{email}")
    redis_client.delete(attempt_key)
    return True, "邮箱验证成功"
