from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from flask import current_app
import atexit
import traceback
from datetime import datetime, timedelta, timezone
from minio import Minio
from minio.error import S3Error
from app.models import LostItem, FoundItem, CarouselImage, User
from urllib.parse import urlparse
import os

from app.utils.matching_service import match_items

# 创建调度器
scheduler = BackgroundScheduler()
flask_app = None

# MinIO配置
MINIO_ENDPOINT = os.getenv('MINIO_ENDPOINT')
MINIO_ACCESS_KEY = os.getenv('MINIO_ACCESS_KEY')
MINIO_SECRET_KEY = os.getenv('MINIO_SECRET_KEY')
MINIO_BUCKET_NAME = os.getenv('MINIO_BUCKET_NAME')


def _get_minio_client():
    """惰性获取 MinIO 客户端：MINIO_ENDPOINT 未配置时返回 None（应用仍可启动，仅清理任务不可用）"""
    if not MINIO_ENDPOINT:
        current_app.logger.warning("MINIO_ENDPOINT 未配置，MinIO 功能不可用")
        return None
    return Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False
    )


# 初始化调度器
def init_scheduler(app):
    global flask_app
    flask_app = app

    try:
        with app.app_context():
            current_app.logger.info("初始化调度器...")

            # 添加每5分钟运行一次的匹配任务
            scheduler.add_job(
                func=run_matching_task,
                trigger=IntervalTrigger(minutes=5),
                id='matching_task',
                name='匹配任务（每5分钟）',
                replace_existing=True
            )

            # 添加每小时运行一次的删除失效图片任务
            scheduler.add_job(
                func=delete_expired_images,
                trigger=IntervalTrigger(hours=1),
                id='delete_expired_images_task',
                name='删除失效图片任务（每小时）',
                replace_existing=True
            )

            # 启动调度器
            if not scheduler.running:
                scheduler.start()
                current_app.logger.info("调度器已启动，匹配任务将每5分钟运行一次，删除失效图片任务（每1小时）运行一次")

            # 确保应用退出时关闭调度器
            atexit.register(lambda: scheduler.shutdown())

    except Exception as e:
        with app.app_context():
            current_app.logger.error(f"初始化调度器时出错: {str(e)}")
            current_app.logger.error(traceback.format_exc())


# 运行匹配任务
def run_matching_task():
    if not flask_app:
        print("错误: Flask应用实例未初始化")
        return

    # 创建应用上下文
    with flask_app.app_context():
        try:
            current_app.logger.info("开始运行匹配任务...")

            # 运行匹配过程
            match_count = match_items()

            current_app.logger.info(f"匹配任务完成，找到 {match_count} 个匹配项")

        except Exception as e:
            current_app.logger.error(f"运行匹配任务时出错: {str(e)}")
            current_app.logger.error(traceback.format_exc())


# 把存储的图片 URL 转成 MinIO 的 object_name（去掉 scheme/host 与桶名前缀）
def _url_to_object_name(url):
    """把存储的完整图片 URL 转成 MinIO 的 object_name（去掉 scheme/host 与桶名前缀）。

    头像 URL 带 avatars/ 目录前缀，若只取文件名最后一段会与 object_name 永不匹配，
    导致定时清理任务把正在使用中的头像当垃圾文件删除。
    """
    if not url:
        return None
    path = urlparse(url).path.lstrip('/')  # bucket/avatars/xxx.jpeg
    bucket_prefix = f"{MINIO_BUCKET_NAME}/" if MINIO_BUCKET_NAME else ''
    if bucket_prefix and path.startswith(bucket_prefix):
        return path[len(bucket_prefix):]
    return path


# 删除失效图片
def delete_expired_images():
    with flask_app.app_context():  # 添加应用上下文
        try:
            # MinIO 未配置时客户端不可用：跳过本次清理，不影响应用其他功能
            client = _get_minio_client()
            if client is None:
                return

            # 获取数据库中所有图片的 URL（转成 MinIO object_name 再比对）
            lost_item_images = {_url_to_object_name(item.image_url) for item in LostItem.query.all() if
                                item.image_url}
            found_item_images = {_url_to_object_name(item.image_url) for item in FoundItem.query.all() if
                                 item.image_url}
            carousel_image_urls = {_url_to_object_name(image.image_url) for image in CarouselImage.query.all()
                                   if image.image_url}
            user_avatar_urls = {_url_to_object_name(user.avatar_url) for user in User.query.all() if
                                user.avatar_url}

            # 合并所有 URL（_url_to_object_name 对空值返回 None，需剔除避免误匹配）
            all_images = lost_item_images.union(found_item_images).union(carousel_image_urls).union(user_avatar_urls)
            all_images.discard(None)

            # 列出MinIO桶中的所有文件
            # 24小时保护期：刚上传、尚未写入数据库的图片（上传与发布之间存在时间窗）不能删
            protection_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            # 必须递归列举，否则 avatars/ 等子目录对象以目录伪条目出现，头像孤儿永不清理
            objects = client.list_objects(MINIO_BUCKET_NAME, recursive=True)
            for obj in objects:
                # 检查文件名是否在数据库中
                if obj.object_name not in all_images:
                    if obj.last_modified is None or obj.last_modified > protection_cutoff:
                        current_app.logger.info(f"跳过 {obj.object_name}（未被引用但处于24小时保护期内）")
                        continue
                    current_app.logger.info(f"准备删除文件: {obj.object_name}，因为它不在数据库中")
                    # 如果不在数据库中，则删除该文件
                    client.remove_object(MINIO_BUCKET_NAME, obj.object_name)
                    current_app.logger.info(f"已删除失效图片: {obj.object_name}")

        except S3Error as e:
            current_app.logger.error(f"MinIO操作失败: {str(e)}")
        except Exception as e:
            current_app.logger.error(f"删除失效图片时出错: {str(e)}")
