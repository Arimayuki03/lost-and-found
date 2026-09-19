import os
import smtplib
import secrets
from email.mime.text import MIMEText
from email.utils import formataddr

from flask import current_app
from app.utils.redis_client import redis_client

# 从环境变量中获取配置
SMTP_SERVER = os.getenv('SMTP_SERVER')
SMTP_PORT = int(os.getenv('SMTP_PORT') or 465)
EMAIL_ADDRESS = os.getenv('EMAIL_ADDRESS')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')


# 生成验证码
def generate_verification_code():
    # random 的 Mersenne Twister 可被预测，验证码必须用 secrets 保证密码学安全
    return str(secrets.randbelow(900000) + 100000)


def _send_code_email(to_email, subject, body):
    """发送验证码邮件，返回是否成功（失败由调用方决定如何向客户端呈现）"""
    try:
        msg = MIMEText(body, 'plain', 'utf-8')
        msg['From'] = formataddr(["失物招领小程序", EMAIL_ADDRESS])
        msg['To'] = to_email
        msg['Subject'] = subject

        # with 语句确保 login/sendmail 抛异常时连接仍会被关闭，不泄漏 SMTP 资源
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, [to_email], msg.as_string())
        current_app.logger.info(f"验证码邮件发送成功至 {to_email}")
        return True
    except Exception as e:
        current_app.logger.error(f"发送验证码邮件失败: {str(e)}")
        return False


# 发送验证码邮件，返回是否成功
def send_verification_email(to_email):
    # 生成验证码，先落 Redis 再发送（SMTP 失败时验证码保留，供测试/重试场景使用）
    code = generate_verification_code()
    redis_client.setex(f"email_verification:{to_email}", 90, code)
    return _send_code_email(
        to_email,
        "邮箱验证",
        f'您的验证码是: {code}，验证码90秒内有效。'
    )
