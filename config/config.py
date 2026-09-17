import os
from datetime import timedelta


class Config:
    SECRET_KEY = os.getenv('SECRET_KEY')

    # 限制单次请求体大小（图片上传经压缩后约 1MB，16MB 为宽松上限）
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024

    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=15)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)

    MINIO_ENDPOINT = os.getenv('MINIO_ENDPOINT')
    MINIO_ACCESS_KEY = os.getenv('MINIO_ACCESS_KEY')
    MINIO_SECRET_KEY = os.getenv('MINIO_SECRET_KEY')
    MINIO_BUCKET_NAME = os.getenv('MINIO_BUCKET_NAME')

    SMTP_SERVER = os.getenv('SMTP_SERVER')
    SMTP_PORT = int(os.getenv('SMTP_PORT') or 465)
    EMAIL_ADDRESS = os.getenv('EMAIL_ADDRESS')
    EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')

    TENCENT_CLOUD_API_KEY = os.getenv('TENCENT_CLOUD_API_KEY')
    TENCENT_CLOUD_API_SECRET = os.getenv('TENCENT_CLOUD_API_SECRET')

    REDIS_HOST = os.getenv('REDIS_HOST', 'localhost')
    REDIS_PORT = int(os.getenv('REDIS_PORT', 6379))
    REDIS_DB = int(os.getenv('REDIS_DB', 0))
    REDIS_PASSWORD = os.getenv('REDIS_PASSWORD', None) 

