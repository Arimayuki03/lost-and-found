from flask import request, jsonify, current_app

from app.utils import redis_client
from app.utils.email_service import send_verification_email
from app.utils.ratelimit import ip_rate_limit
from . import common

# 同一邮箱每日验证码发送上限（60 秒重发锁之外的第二道限制，防止被用作邮件轰炸源）
DAILY_SEND_LIMIT = 10
DAY_SECONDS = 86400


# 发送邮箱验证码接口
@common.route('/emails/verification', methods=['POST'])
# 每邮箱的锁/日上限挡不住"轮询海量邮箱地址"的轰炸与 SMTP 配额消耗，
# 这里补按 IP 维度的限流（正常注册/找回密码流程每分钟远达不到 10 次）
@ip_rate_limit('email_verification_send', 10, 60)
def send_verification_email_endpoint():
    # 从请求中获取JSON数据（silent=True 避免无 body 时 get_json 返回 None 崩溃）
    data = request.get_json(silent=True) or {}
    # 获取邮箱地址
    email = data.get('email')

    # 检查邮箱是否为空
    if not email:
        current_app.logger.warning("邮箱地址是必需的。")
        return jsonify({"error": "邮箱地址是必需的。"}), 400
    # 类型/长度防护：非字符串邮箱会污染 Redis 键并在下游产生 500
    if not isinstance(email, str) or len(email) > 100 or '@' not in email:
        return jsonify({"error": "邮箱格式不正确。"}), 400

    # 检查是否在60秒内重发
    if redis_client.get(f"email_verification_lock:{email}"):
        current_app.logger.warning("请稍后再请求新的验证码。")
        return jsonify({"error": "请稍后再请求新的验证码。"}), 400

    # 检查该邮箱今日发送次数是否已达上限
    daily_key = f"email_verification_daily:{email}"
    sent_today = redis_client.get(daily_key)
    if sent_today is not None and int(sent_today) >= DAILY_SEND_LIMIT:
        return jsonify({"error": "该邮箱今日验证码发送次数已达上限，请明日再试。"}), 429

    try:
        # 发送新的验证码（SMTP 失败时如实返回错误，不向客户端谎报成功）
        if not send_verification_email(email):
            return jsonify({"error": "发送验证码邮件失败，请稍后再试。"}), 500

        # 设置60秒锁，防止频繁请求
        redis_client.setex(f"email_verification_lock:{email}", 60, "locked")

        # 累计当日发送次数
        count = redis_client.incr(daily_key)
        if count == 1:
            redis_client.expire(daily_key, DAY_SECONDS)

        current_app.logger.info("验证码邮件发送成功。")
        return jsonify({"message": "验证码邮件发送成功。"}), 200
    except Exception as e:
        current_app.logger.error(f"发送验证码邮件时发生错误: {str(e)}")
        return jsonify({"error": "发送验证码邮件时发生错误"}), 500
