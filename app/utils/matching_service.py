import os
import smtplib
import time
import html
import uuid
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import current_app
from sqlalchemy import or_
import difflib
import re
import traceback
from app import db
from app.utils import redis_client
from app.models import LostItem, FoundItem, User, ItemMatch
from email.utils import formataddr

# 从环境变量中获取邮件服务配置
SMTP_SERVER = os.getenv('SMTP_SERVER')
SMTP_PORT = int(os.getenv('SMTP_PORT') or 465)
EMAIL_ADDRESS = os.getenv('EMAIL_ADDRESS')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')

# 匹配任务互斥锁：调度器每 5 分钟一轮 + /admin/run 可手动随时触发，
# 两条路径并发时会生成重复匹配并给用户重发通知邮件。用 Redis SETNX 保证
# 同一时刻只有一个匹配任务在跑；TTL 需大于任务最坏耗时，防止进程崩溃留下死锁
MATCHING_LOCK_KEY = "matching_lock"
MATCHING_LOCK_TTL_SECONDS = 600

# 匹配通知补发保护（匹配表无重试相关字段，状态存 Redis，均带 TTL 兜底清理）：
# - match_notified:<匹配ID>:<lost|found>：该侧邮件已成功发出，补发时不再向该侧发送
# - match_retry:<匹配ID>：累计发送失败轮数，超过 MATCH_RETRY_MAX 后停止补发
MATCH_NOTIFIED_PREFIX = "match_notified:"
MATCH_RETRY_PREFIX = "match_retry:"
MATCH_RETRY_MAX = 10
MATCH_NOTIFY_STATE_TTL_SECONDS = 7 * 86400

# 匹配阈值设置
NAME_SIMILARITY_THRESHOLD = 0.4  # 名称相似度阈值
CATEGORY_SIMILARITY_THRESHOLD = 0.2  # 类别相似度阈值
LOCATION_SIMILARITY_THRESHOLD = 0.1  # 地点相似度阈值
TIME_SIMILARITY_THRESHOLD = 0.2  # 时间相似度阈值
OVERALL_SIMILARITY_THRESHOLD = 0.5  # 总体相似度阈值

# 相似度权重设置
NAME_WEIGHT = 0.7  # 名称权重
CATEGORY_WEIGHT = 0.1  # 类别权重
LOCATION_WEIGHT = 0.1  # 地点权重
TIME_WEIGHT = 0.1  # 时间权重


def calculate_text_similarity(text1, text2):
    """
    计算两个文本的相似度
    """
    if not text1 or not text2:
        return 0.0

    # 将文本转换为小写并移除特殊字符
    text1 = re.sub(r'[^\w\s]', '', text1.lower())
    text2 = re.sub(r'[^\w\s]', '', text2.lower())

    # 使用difflib计算相似度
    return difflib.SequenceMatcher(None, text1, text2).ratio()


def calculate_time_similarity(time1, time2, max_days_diff=7):
    """
    计算两个时间的相似度
    """
    if not time1 or not time2:
        return 0.0

    # 计算时间差异（以天为单位）
    time_diff = abs((time1 - time2).total_seconds()) / (24 * 3600)

    # 如果时间差异超过最大天数，则相似度为0
    if time_diff > max_days_diff:
        return 0.0

    # 计算相似度：1 - (时间差异 / 最大天数差异)
    return 1.0 - (time_diff / max_days_diff)


def match_items():
    """
    匹配失物和拾物（优化版本）。
    同一时刻仅允许一个实例运行（调度器与手动触发共享 Redis 锁），
    抢锁失败直接返回 0，由下一轮任务自然补齐
    """
    start_time = time.time()
    # 锁值用唯一 token 标识持有者：任务超 TTL 后另一实例抢到新锁，
    # 先完成者释放锁时不能误删后获锁者的锁，故只在值匹配时才删除
    lock_token = uuid.uuid4().hex
    if not redis_client.set(MATCHING_LOCK_KEY, lock_token,
                            nx=True, ex=MATCHING_LOCK_TTL_SECONDS):
        current_app.logger.info("跳过本轮匹配：另一匹配任务正在进行")
        return 0
    try:
        current_app.logger.info("开始匹配失物和拾物...")

        # 获取所有已审核未完成的物品。
        # lost_item.is_completed 为 NOT NULL，is_(False) 与原等值比较行为一致；
        # found_item.is_completed 允许 NULL（DDL：tinyint DEFAULT NULL，表示未定），
        # 仅做等值 False 比较会把 NULL 行一并排除，导致未完结的拾物永远不进入匹配，故需 or_ 补上 NULL
        lost_items = LostItem.query.filter(LostItem.is_completed.is_(False),
                                           LostItem.is_under_review.is_(False)).all()
        found_items = FoundItem.query.filter(or_(FoundItem.is_completed.is_(False),
                                                 FoundItem.is_completed.is_(None)),
                                             FoundItem.is_under_review.is_(False)).all()

        if not lost_items or not found_items:
            current_app.logger.info(f"没有可匹配的物品。失物：{len(lost_items)}，拾物：{len(found_items)}")
            return 0

        # 获取已有的匹配记录：已通知过的对跳过，未通知过的（上次邮件发送失败）重发通知
        # 只存正向键 (lost_item_id, found_item_id)：两张表 ID 空间重叠时，
        # 反向键会把完全不同的 (lost, found) 对误判为"已存在"而永久漏匹配
        existing_matches = {}
        for match in ItemMatch.query.all():
            existing_matches[(match.lost_item_id, match.found_item_id)] = match

        # 预处理物品数据
        processed_lost_items = []
        for item in lost_items:
            processed_lost_items.append({
                'id': item.id,
                'name': item.name if item.name else "",
                'category': item.category if item.category else "",
                'location': item.location,
                'time': item.lost_time,
                'original': item
            })

        processed_found_items = []
        for item in found_items:
            processed_found_items.append({
                'id': item.id,
                'name': item.name if item.name else "",
                'category': item.category if item.category else "",
                'location': item.location,
                'time': item.found_time,
                'original': item
            })

        # 批量匹配处理
        new_matches = []
        retry_matches = set()
        match_count = 0

        for lost in processed_lost_items:
            for found in processed_found_items:
                existing = existing_matches.get((lost['id'], found['id']))
                if existing is not None:
                    # 已通知过的对跳过；未通知过的（此前邮件发送失败）收集起来重发。
                    # 两侧物品都来自上方"未完结且不在审核中"的过滤结果，
                    # 物品已完结/审核中的匹配天然不会进入重试，避免对已结束的物品无限补发
                    if existing.notified:
                        continue
                    retry_matches.add(existing)
                    continue

                # 快速预筛选
                if difflib.SequenceMatcher(None, lost['name'],
                                           found['name']).quick_ratio() < NAME_SIMILARITY_THRESHOLD * 0.7:
                    continue

                # 使用calculate_text_similarity计算名称相似度
                name_similarity = calculate_text_similarity(lost['name'], found['name'])

                # 提前过滤：如果名称相似度不满足要求，直接跳过其他计算
                if name_similarity < NAME_SIMILARITY_THRESHOLD:
                    continue

                # 使用calculate_text_similarity计算类别相似度
                category_similarity = calculate_text_similarity(lost['category'], found['category'])

                # 继续提前过滤
                if category_similarity < CATEGORY_SIMILARITY_THRESHOLD:
                    continue

                # 使用calculate_text_similarity计算地点相似度
                location_similarity = 0.0
                if lost['location'] and found['location']:
                    location_similarity = calculate_text_similarity(lost['location'], found['location'])

                # 继续提前过滤
                if location_similarity < LOCATION_SIMILARITY_THRESHOLD:
                    continue

                # 使用calculate_time_similarity计算时间相似度
                time_similarity = 0.0
                if lost['time'] and found['time']:
                    time_similarity = calculate_time_similarity(lost['time'], found['time'])

                # 继续提前过滤
                if time_similarity < TIME_SIMILARITY_THRESHOLD:
                    continue

                # 计算总体相似度
                overall_similarity = (
                        name_similarity * NAME_WEIGHT +
                        category_similarity * CATEGORY_WEIGHT +
                        location_similarity * LOCATION_WEIGHT +
                        time_similarity * TIME_WEIGHT
                )

                # 最终检查是否达到总体相似度阈值
                if overall_similarity >= OVERALL_SIMILARITY_THRESHOLD:
                    # 创建匹配记录对象
                    match = ItemMatch(
                        lost_item_id=lost['id'],
                        found_item_id=found['id'],
                        similarity_score=overall_similarity,
                        name_similarity=name_similarity,
                        category_similarity=category_similarity,
                        location_similarity=location_similarity,
                        time_similarity=time_similarity
                    )

                    new_matches.append(match)
                    match_count += 1

                    # 每找到10个匹配项记录一次进度
                    if match_count % 10 == 0:
                        current_app.logger.info(f"已找到 {match_count} 个匹配")

        # 批量保存匹配记录
        if new_matches:
            db.session.add_all(new_matches)
            db.session.commit()

            # 发送匹配通知
            for match in new_matches:
                send_match_notification(match)

        # 重发此前发送失败的匹配通知：send_match_notification 内部只向未成功的一方补发，
        # 重试轮数由 Redis 计数封顶，防止邮件服务长期故障时每 5 分钟无限重发
        for match in retry_matches:
            try:
                retries = int(redis_client.get(f"{MATCH_RETRY_PREFIX}{match.id}") or 0)
            except Exception:
                # Redis 异常时按未超限处理（fail-open），与限流器/账号锁的权衡一致
                retries = 0
            if retries > MATCH_RETRY_MAX:
                continue
            send_match_notification(match)

        end_time = time.time()
        elapsed_time = end_time - start_time
        current_app.logger.info(f"匹配完成，耗时 {elapsed_time:.2f} 秒，共找到 {match_count} 个匹配项")
        return match_count

    except Exception as e:
        current_app.logger.error(f"匹配失物和拾物时出错: {str(e)}")
        return 0
    finally:
        # 主动释放，下一轮任务/手动触发可立即抢锁；即便此处失败，TTL 也会兜底过期。
        # 仅当锁仍归本实例（值匹配）才删除，防止误删超 TTL 后其他实例持有的新锁
        try:
            redis_client.eval(
                "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('del',KEYS[1]) end",
                1, MATCHING_LOCK_KEY, lock_token)
        except Exception:
            pass


def send_match_notification(match):
    """
    发送匹配通知（只向邮件尚未成功送达的一方发送）。
    各侧发送状态记录在 Redis（match_notified:<匹配ID>:<lost|found>，带 TTL），
    双方都已送达才将 match.notified 置 True；任何一侧发送失败都会累积
    match_retry:<匹配ID> 计数，供重试上限判断。
    """
    retry_key = f"{MATCH_RETRY_PREFIX}{match.id}"
    lost_notified_key = f"{MATCH_NOTIFIED_PREFIX}{match.id}:lost"
    found_notified_key = f"{MATCH_NOTIFIED_PREFIX}{match.id}:found"
    try:
        # 获取失物和拾物信息
        lost_item = LostItem.query.get(match.lost_item_id)
        found_item = FoundItem.query.get(match.found_item_id)

        if not lost_item or not found_item:
            current_app.logger.error("发送匹配通知时出错: 找不到失物或拾物记录")
            return

        # 获取用户信息
        lost_item_user = User.query.get(lost_item.user_id)
        found_item_user = User.query.get(found_item.user_id)

        if not lost_item_user or not found_item_user:
            current_app.logger.error("发送匹配通知时出错: 找不到用户记录")
            return

        def _mark_notified(key):
            """登记该侧邮件已成功送达；Redis 异常不阻断主流程（最坏情况是该侧重收一封邮件）"""
            try:
                redis_client.setex(key, MATCH_NOTIFY_STATE_TTL_SECONDS, "1")
            except Exception as e:
                current_app.logger.error(f"登记匹配通知状态失败（key={key}）: {str(e)}")

        try:
            lost_notified = redis_client.get(lost_notified_key) is not None
            found_notified = redis_client.get(found_notified_key) is not None
        except Exception as e:
            # Redis 异常时视为两侧均未发送（fail-open），与限流器/账号锁的权衡一致
            current_app.logger.error(f"查询匹配通知状态失败（匹配ID={match.id}）: {str(e)}")
            lost_notified = found_notified = False

        # 只向未成功送达的一方发送，成功一方不再重复收信
        lost_ok = True
        found_ok = True
        if not lost_notified:
            lost_ok = send_email_to_lost_item_user(lost_item_user, lost_item, found_item, match)
            if lost_ok:
                _mark_notified(lost_notified_key)
        if not found_notified:
            found_ok = send_email_to_found_item_user(found_item_user, lost_item, found_item, match)
            if found_ok:
                _mark_notified(found_notified_key)

        # 两侧都已送达才标记已通知，停止后续补发
        both_notified = (lost_notified or lost_ok) and (found_notified or found_ok)
        if both_notified:
            match.notified = True
            db.session.commit()
            current_app.logger.info(f"已发送匹配通知: 匹配ID={match.id}")
            try:
                redis_client.delete(retry_key)
            except Exception:
                pass
        else:
            # 有侧发送失败：累积重试计数（带 TTL 兜底），供本轮重试上限判断
            match.notified = False
            db.session.commit()
            try:
                count = redis_client.incr(retry_key)
                redis_client.expire(retry_key, MATCH_NOTIFY_STATE_TTL_SECONDS)
                current_app.logger.warning(
                    f"匹配通知发送失败，等待下次补发: 匹配ID={match.id}，失败轮数={count}")
            except Exception as e:
                current_app.logger.error(f"记录匹配通知重试计数失败（匹配ID={match.id}）: {str(e)}")

    except Exception as e:
        current_app.logger.error(f"发送匹配通知时出错: {str(e)}")
        current_app.logger.error(traceback.format_exc())


def send_email_to_lost_item_user(user, lost_item, found_item, match):
    """
    发送邮件给失物用户
    """
    subject = "【失物招领系统】您的失物可能已被找到"

    # 构建邮件内容
    html_content = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background-color: #4CAF50; color: white; padding: 10px; text-align: center; }}
            .content {{ padding: 20px; border: 1px solid #ddd; }}
            .item-details {{ margin-bottom: 20px; }}
            .similarity {{ background-color: #f9f9f9; padding: 10px; margin-top: 20px; }}
            .footer {{ text-align: center; margin-top: 20px; font-size: 12px; color: #777; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>失物招领系统 - 匹配通知</h2>
            </div>
            <div class="content">
                <p>尊敬的 {html.escape(user.name)}（用户ID: {user.id}）：</p>
                <p>我们的系统发现有人拾到了可能是您丢失的物品。详情如下：</p>

                <div class="item-details">
                    <h3>您的失物信息：</h3>
                    <p><strong>物品名称：</strong>{html.escape(lost_item.name)}</p>
                    <p><strong>物品类别：</strong>{html.escape(lost_item.category)}</p>
                    <p><strong>丢失地点：</strong>{html.escape(lost_item.location)}</p>
                    <p><strong>丢失时间：</strong>{lost_item.lost_time.strftime('%Y-%m-%d %H:%M')}</p>
                </div>

                <div class="item-details">
                    <h3>匹配的拾物信息：</h3>
                    <p><strong>物品名称：</strong>{html.escape(found_item.name)}</p>
                    <p><strong>物品类别：</strong>{html.escape(found_item.category)}</p>
                    <p><strong>拾取地点：</strong>{html.escape(found_item.location)}</p>
                    <p><strong>拾取时间：</strong>{found_item.found_time.strftime('%Y-%m-%d %H:%M')}</p>
                </div>

                <div class="similarity">
                    <h3>匹配相似度：</h3>
                    <p><strong>总体相似度：</strong>{match.similarity_score:.2%}</p>
                    <p><strong>名称相似度：</strong>{match.name_similarity:.2%}</p>
                    <p><strong>类别相似度：</strong>{match.category_similarity:.2%}</p>
                    <p><strong>地点相似度：</strong>{match.location_similarity:.2%}</p>
                    <p><strong>时间相似度：</strong>{match.time_similarity:.2%}</p>
                </div>

                <p>拾物者联系方式（用户ID: {found_item.user_id}）：{html.escape(found_item.contact)}</p>
                <p>如果您认为这可能是您丢失的物品，请登录失物招领系统与拾物者联系。</p>
            </div>
            <div class="footer">
                <p>此邮件由系统自动发送，请勿直接回复。</p>
                <p>© 2025 失物招领系统</p>
            </div>
        </div>
    </body>
    </html>
    """

    # 发送邮件
    return send_email(user.email, subject, html_content)


def send_email_to_found_item_user(user, lost_item, found_item, match):
    """
    发送邮件给拾物用户
    """
    subject = "【失物招领系统】您拾到的物品可能已找到失主"

    # 构建邮件内容
    html_content = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background-color: #2196F3; color: white; padding: 10px; text-align: center; }}
            .content {{ padding: 20px; border: 1px solid #ddd; }}
            .item-details {{ margin-bottom: 20px; }}
            .similarity {{ background-color: #f9f9f9; padding: 10px; margin-top: 20px; }}
            .footer {{ text-align: center; margin-top: 20px; font-size: 12px; color: #777; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h2>失物招领系统 - 匹配通知</h2>
            </div>
            <div class="content">
                <p>尊敬的 {html.escape(user.name)}（用户ID: {user.id}）：</p>
                <p>我们的系统发现您拾到的物品可能已找到失主。详情如下：</p>

                <div class="item-details">
                    <h3>您拾到的物品信息：</h3>
                    <p><strong>物品名称：</strong>{html.escape(found_item.name)}</p>
                    <p><strong>物品类别：</strong>{html.escape(found_item.category)}</p>
                    <p><strong>拾取地点：</strong>{html.escape(found_item.location)}</p>
                    <p><strong>拾取时间：</strong>{found_item.found_time.strftime('%Y-%m-%d %H:%M')}</p>
                </div>

                <div class="item-details">
                    <h3>匹配的失物信息：</h3>
                    <p><strong>物品名称：</strong>{html.escape(lost_item.name)}</p>
                    <p><strong>物品类别：</strong>{html.escape(lost_item.category)}</p>
                    <p><strong>丢失地点：</strong>{html.escape(lost_item.location)}</p>
                    <p><strong>丢失时间：</strong>{lost_item.lost_time.strftime('%Y-%m-%d %H:%M')}</p>
                </div>

                <div class="similarity">
                    <h3>匹配相似度：</h3>
                    <p><strong>总体相似度：</strong>{match.similarity_score:.2%}</p>
                    <p><strong>名称相似度：</strong>{match.name_similarity:.2%}</p>
                    <p><strong>类别相似度：</strong>{match.category_similarity:.2%}</p>
                    <p><strong>地点相似度：</strong>{match.location_similarity:.2%}</p>
                    <p><strong>时间相似度：</strong>{match.time_similarity:.2%}</p>
                </div>

                <p>失主联系方式（用户ID: {lost_item.user_id}）：{html.escape(lost_item.contact)}</p>
                <p>如果您认为这可能是失主的物品，请登录失物招领系统与失主联系。</p>
            </div>
            <div class="footer">
                <p>此邮件由系统自动发送，请勿直接回复。</p>
                <p>© 2025 失物招领系统</p>
            </div>
        </div>
    </body>
    </html>
    """

    # 发送邮件
    return send_email(user.email, subject, html_content)


def send_email(to_email, subject, html_content):
    """
    发送邮件
    """
    try:
        # 创建邮件对象
        msg = MIMEMultipart()
        msg['From'] = formataddr(["失物招领小程序", EMAIL_ADDRESS])
        msg['To'] = to_email
        msg['Subject'] = subject

        # 添加HTML内容
        msg.attach(MIMEText(html_content, 'html'))

        # 连接SMTP服务器并发送邮件
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.send_message(msg)

        current_app.logger.info(f"已发送邮件至 {to_email}")
        return True

    except Exception as e:
        current_app.logger.error(f"发送邮件时出错: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        return False
