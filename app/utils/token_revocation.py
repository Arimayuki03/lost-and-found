import time

from flask import current_app

from app.utils import redis_client

# 密码变更撤销标记的 TTL：需覆盖 refresh token 的 30 天有效期，取 31 天
PWD_CHANGED_TTL_SECONDS = 31 * 86400


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
