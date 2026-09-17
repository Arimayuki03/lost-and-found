import io
import json
import os
import uuid
from urllib.parse import urlparse
from . import common
from PIL import Image
from flask import request, jsonify, current_app
from flask_jwt_extended import jwt_required
from minio import Minio
from minio.error import S3Error
from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.tiia.v20190529 import tiia_client, models
from app.utils import redis_client
from app.utils.ratelimit import ip_rate_limit

# 付费图片检测的防刷凭证：上传成功的图片在 Redis 登记 object_name（30 分钟有效），
# 匿名可调用的 /images/inappropriate-content 只接受"刚上传的图片"且凭证一次性消耗。
# 攻击者的调用量因此被上传接口自身的限流（10 次/分/IP）钳制，
# 也无法拿同一张已上传图片反复调用腾讯云 TIIA 计费接口。
IMG_CHECK_TOKEN_PREFIX = "imgcheck:"
IMG_CHECK_TOKEN_TTL_SECONDS = 1800

# 解压炸弹防护：超过 2000 万像素的图片直接拒绝（配合下方异常捕获）
Image.MAX_IMAGE_PIXELS = 20_000_000

# SSRF 防护
def _validate_internal_image_url(image_url):
    """SSRF 防护：仅允许本系统 MinIO 的图片地址（scheme=http、host 与 MINIO_ENDPOINT 一致、路径在桶内）"""
    parsed = urlparse(image_url)
    if parsed.scheme != 'http':
        raise ValueError("仅支持系统内图片地址")
    endpoint = (MINIO_ENDPOINT or '').strip()
    if not endpoint or parsed.netloc != endpoint:
        raise ValueError("仅支持系统内图片地址")
    if not MINIO_BUCKET_NAME or not parsed.path.startswith(f"/{MINIO_BUCKET_NAME}/"):
        raise ValueError("仅支持系统内图片地址")

# 腾讯云服务器无法访问本机/内网的 MinIO 地址（如 http://127.0.0.1:9000），
# 因此统一由后端自行下载图片后以 ImageBase64 提交，而非 ImageUrl 让腾讯回源下载
def _tiia_image_payload(image_url):
    """下载图片并返回腾讯云 TIIA 请求参数（ImageBase64 形式）。

    下载失败或内容超过 8MB 时抛 ValueError（由调用方映射 4xx/5xx）。
    """
    import base64

    import requests as requests_lib

    # SSRF 防护：先校验地址是否为本系统 MinIO 内的图片地址
    _validate_internal_image_url(image_url)

    # with 语句确保各分支（含超限提前 raise）退出时都关闭响应，不泄漏连接句柄
    try:
        with requests_lib.get(image_url, timeout=10, stream=True, allow_redirects=False) as resp:
            resp.raise_for_status()

            declared_length = resp.headers.get('Content-Length')
            if declared_length and declared_length.isdigit() and int(declared_length) > 8 * 1024 * 1024:
                raise ValueError("图片过大，无法识别")
            content = resp.raw.read(8 * 1024 * 1024 + 1)  # 流式限量读取，最多 8MB+1 字节
            if len(content) > 8 * 1024 * 1024:
                raise ValueError("图片过大，无法识别")
    except ValueError:
        # 超限错误原样上抛给调用方映射 400；with 已关闭响应
        raise
    except Exception as e:
        current_app.logger.error(f"下载待识别图片失败: {image_url} - {str(e)}")
        raise ValueError("图片下载失败，无法识别")

    return {"ImageBase64": base64.b64encode(content).decode('utf-8')}

# 从环境变量中获取腾讯云 API 密钥
TENCENT_CLOUD_API_KEY = os.getenv('TENCENT_CLOUD_API_KEY')
TENCENT_CLOUD_API_SECRET = os.getenv('TENCENT_CLOUD_API_SECRET')
TENCENT_CLOUD_API_URL = 'https://tiia.tencentcloudapi.com'
TENCENT_CLOUD_API_VERSION = '2019-05-29'
TENCENT_CLOUD_API_ACTION = 'DetectLabelPro'
TENCENT_CLOUD_SERVICE = 'tiia'

# 从环境变量中获取 MinIO 配置
MINIO_ENDPOINT = os.getenv('MINIO_ENDPOINT')
MINIO_ACCESS_KEY = os.getenv('MINIO_ACCESS_KEY')
MINIO_SECRET_KEY = os.getenv('MINIO_SECRET_KEY')
MINIO_BUCKET_NAME = os.getenv('MINIO_BUCKET_NAME')

# 初始化 MinIO 客户端
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False
)


# 图片打标签接口（调用腾讯云付费 API；需登录 + 按 IP 限流防刷）
@common.route('/images/labels', methods=['POST'])
@jwt_required()
@ip_rate_limit('images_labels', max_requests=20, window_seconds=60)
def recognize_image():
    # 从请求中获取JSON数据
    data = request.get_json(silent=True) or {}
    # 获取图片URL
    image_url = data.get('image_url')
    if not image_url:
        current_app.logger.warning("图片URL是必需的。")
        return jsonify({"error": "图片URL是必需的。"}), 400
    if not isinstance(image_url, str):
        return jsonify({"error": "图片URL需为字符串"}), 400

    try:
        # 创建腾讯云API客户端
        cred = credential.Credential(TENCENT_CLOUD_API_KEY, TENCENT_CLOUD_API_SECRET)
        httpProfile = HttpProfile()
        httpProfile.endpoint = "tiia.tencentcloudapi.com"

        clientProfile = ClientProfile()
        clientProfile.httpProfile = httpProfile

        client = tiia_client.TiiaClient(cred, "ap-guangzhou", clientProfile)

        # 创建请求对象
        req = models.DetectLabelProRequest()
        params = _tiia_image_payload(image_url)
        req.from_json_string(json.dumps(params))

        # 发送请求并获取响应
        resp = client.DetectLabelPro(req)
        labels = json.loads(resp.to_json_string()).get('Labels', [])

        if not labels:
            current_app.logger.info("未找到标签")
            return jsonify({"message": "未找到标签"}), 200

        # 统计FirstCategory和SecondCategory出现次数
        from collections import Counter
        category_counter = Counter((label['FirstCategory'], label['SecondCategory']) for label in labels)
        most_common_categories = category_counter.most_common()

        # 找到出现次数最多的类别
        max_count = most_common_categories[0][1]
        candidates = [cat for cat, count in most_common_categories if count == max_count]

        # 如果有多个候选，选择置信度最高的
        if len(candidates) > 1:
            highest_confidence_label = max(
                (label for label in labels if (label['FirstCategory'], label['SecondCategory']) in candidates),
                key=lambda x: x['Confidence']
            )
            current_app.logger.info("返回置信度最高的标签")
            return jsonify({
                "FirstCategory": highest_confidence_label['FirstCategory'],
                "SecondCategory": highest_confidence_label['SecondCategory']
            }), 200

        # 返回出现次数最多的类别
        current_app.logger.info("返回出现次数最多的类别")
        return jsonify({
            "FirstCategory": candidates[0][0],
            "SecondCategory": candidates[0][1]
        }), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"识别图片失败: {str(e)}")
        return jsonify({"error": "识别图片失败"}), 500


# 不良内容检测核心逻辑，供本模块接口与其他模块（注册/换头像）直接调用
def detect_misbehavior_result(image_url):
    """调用腾讯云图像分析 DetectMisbehavior，返回包含 Type/Score 等字段的检测结果"""
    cred = credential.Credential(TENCENT_CLOUD_API_KEY, TENCENT_CLOUD_API_SECRET)
    httpProfile = HttpProfile()
    httpProfile.endpoint = "tiia.tencentcloudapi.com"

    clientProfile = ClientProfile()
    clientProfile.httpProfile = httpProfile

    client = tiia_client.TiiaClient(cred, "ap-guangzhou", clientProfile)

    req = models.DetectMisbehaviorRequest()
    params = _tiia_image_payload(image_url)
    req.from_json_string(json.dumps(params))

    resp = client.DetectMisbehavior(req)
    return json.loads(resp.to_json_string())


# 不良行为识别接口（调用腾讯云付费 API；注册前无登录态，故以
# "本会话刚上传的图片 + 一次性凭证 + IP 限流" 防配额刷取，见 IMG_CHECK_TOKEN 注释）
@common.route('/images/inappropriate-content', methods=['POST'])
@ip_rate_limit('images_misbehavior', max_requests=10, window_seconds=60)
def recognize_inappropriate():
    # 从请求中获取JSON数据
    data = request.get_json(silent=True) or {}
    # 获取图片URL
    image_url = data.get('image_url')
    if not image_url:
        current_app.logger.warning("图片URL是必需的。")
        return jsonify({"error": "图片URL是必需的。"}), 400
    if not isinstance(image_url, str):
        return jsonify({"error": "图片URL需为字符串"}), 400

    # 消耗一次性上传凭证：对象必须来自近 30 分钟内的上传，且只允许检测一次。
    # delete 返回 0 表示凭证不存在/已使用；后续 SSRF 白名单仍会二次校验地址归属。
    # object_name 需还原为"桶名/"前缀之后的完整相对路径（头像有 avatars/ 目录前缀），
    # 与 _validate_and_store_image 登记凭证时使用的 filename 保持一致
    path = urlparse(image_url).path.lstrip('/')
    bucket_prefix = f"{MINIO_BUCKET_NAME}/" if MINIO_BUCKET_NAME else ''
    object_name = path[len(bucket_prefix):] if path.startswith(bucket_prefix) else path
    if not object_name or not redis_client.delete(f"{IMG_CHECK_TOKEN_PREFIX}{object_name}"):
        current_app.logger.warning(f"图片检测凭证无效或已使用: {object_name}")
        return jsonify({"error": "仅支持检测本次会话新上传的图片，请重新上传后再试"}), 403

    try:
        result = detect_misbehavior_result(image_url)
        current_app.logger.info("成功识别不良内容")
        return jsonify(result), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        current_app.logger.error(f"识别不良内容失败: {str(e)}")
        return jsonify({"error": "识别不良内容失败"}), 500


# 上传文件接口（任意已登录用户：用户端发图/头像与管理后台共用）

# 允许上传的图片扩展名白名单
ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp'}

def _validate_and_store_image(file, prefix=''):
    """校验并压缩上传的图片，存入 MinIO，返回可访问 URL。

    仅接受图片文件；PNG 统一转 JPEG；超过 1MB 时逐级降低质量压缩。
    file 缺失/格式无效抛 ValueError（由调用方映射 400），
    MinIO/处理错误抛 S3Error/IOError（映射 500）。
    """
    if file is None or file.filename == '':
        raise ValueError("未选择文件")
    if '.' not in file.filename:
        raise ValueError("无效的文件格式")

    # 使用UUID生成唯一文件名
    file_extension = file.filename.rsplit('.', 1)[1].lower()
    if file_extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("不支持的图片格式")
    # 下方统一重编码为 JPEG 存储，扩展名与实际内容保持一致（避免 .bmp 文件名挂 image/jpeg）
    filename = f"{prefix}{uuid.uuid4()}.jpeg"

    # 使用Pillow压缩图像
    try:
        image = Image.open(file)
    except Image.DecompressionBombError:
        raise ValueError("图片尺寸过大")
    except OSError:
        raise ValueError("无效的图片文件")

    # PIL 只在像素数 > 2×MAX_IMAGE_PIXELS 时才抛 DecompressionBombError，
    # 超过 1× 仅告警；按 2000 万像素的防护意图做显式校验
    if image.width * image.height > 20_000_000:
        raise ValueError("图片尺寸过大")

    # JPEG 仅支持 RGB/L/CMYK 模式：PNG/WebP/GIF 的透明通道、调色板、黑白等模式
    # 直存会抛 OSError，统一先转 RGB（覆盖原 PNG 分支的场景）
    if image.mode not in ('RGB', 'L', 'CMYK'):
        image = image.convert('RGB')  # 转换为RGB模式

    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format='JPEG', quality=90)  # 质量90
    img_byte_arr.seek(0)

    # 检查文件大小并调整质量
    if img_byte_arr.getbuffer().nbytes > 1 * 1024 * 1024:  # 阈值1MB
        quality = 85
        min_quality = 60
        while img_byte_arr.getbuffer().nbytes > 1 * 1024 * 1024 and quality > min_quality:
            quality -= 5  # 减小步长从10到5
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format='JPEG', quality=quality)  # 降低质量
            img_byte_arr.seek(0)

    # 上传文件到MinIO
    minio_client.put_object(
        MINIO_BUCKET_NAME,
        filename,
        img_byte_arr,
        length=img_byte_arr.getbuffer().nbytes,
        part_size=10 * 1024 * 1024,
        content_type='image/jpeg'
    )

    # 登记一次性付费检测凭证（见 IMG_CHECK_TOKEN_PREFIX 注释；Redis 异常不阻断上传）
    try:
        redis_client.setex(f"{IMG_CHECK_TOKEN_PREFIX}{filename}",
                           IMG_CHECK_TOKEN_TTL_SECONDS, "1")
    except Exception as e:
        current_app.logger.error(f"图片检测凭证登记失败: {str(e)}")

    # 直接返回文件URL
    return f"http://{MINIO_ENDPOINT}/{MINIO_BUCKET_NAME}/{filename}"


@common.route('/images/upload', methods=['POST'])
@jwt_required()
def upload_file():
    try:
        file_url = _validate_and_store_image(request.files.get('file'))
    except ValueError as e:
        current_app.logger.warning(f"上传参数无效: {str(e)}")
        return jsonify({"error": str(e)}), 400
    except S3Error as e:
        current_app.logger.error(f"文件上传失败: {str(e)}")
        return jsonify({"error": "文件上传失败"}), 500
    except IOError as e:
        current_app.logger.error(f"文件处理错误: {str(e)}")
        return jsonify({"error": "文件处理错误"}), 500

    current_app.logger.info("文件上传成功")
    return jsonify({"message": "文件上传成功", "file_url": file_url}), 200


# 注册前头像上传（此时尚无登录态，故不走 @jwt_required；
# 以 IP 限流 + 仅图片 + 压缩限形防滥用，注册提交时服务端仍会复核头像内容）
@common.route('/images/upload-avatar', methods=['POST'])
@ip_rate_limit('images_upload_avatar', max_requests=10, window_seconds=60)
def upload_avatar_anonymous():
    try:
        file_url = _validate_and_store_image(request.files.get('file'), prefix='avatars/')
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except S3Error as e:
        current_app.logger.error(f"头像上传失败: {str(e)}")
        return jsonify({"error": "文件上传失败"}), 500
    except IOError as e:
        current_app.logger.error(f"头像处理错误: {str(e)}")
        return jsonify({"error": "文件处理错误"}), 500

    return jsonify({"message": "头像上传成功", "file_url": file_url}), 200
