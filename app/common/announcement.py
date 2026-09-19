from . import common
from flask import request, jsonify, current_app
from app.models import Announcement
from sqlalchemy.exc import SQLAlchemyError
from app.utils.page import escape_like
from app.utils.ratelimit import ip_rate_limit


# 获取所有公告接口 - 不使用分页
@common.route('/announcements', methods=['GET'])
# 匿名公开列表端点：无分页全量返回，按 IP 限流防批量抓取
@ip_rate_limit('common_list', 60, 60)
def get_announcements():
    try:
        # 获取查询参数
        sort_by = request.args.get('sort_by', 'created_at')  # 默认按创建时间排序
        sort_order = request.args.get('sort_order', 'desc')  # 默认降序（最新的在前）
        query = request.args.get('query', '')

        # 构建查询
        announcements_query = Announcement.query

        # 应用搜索
        if query:
            from sqlalchemy import or_
            announcements_query = announcements_query.filter(
                or_(
                    Announcement.title.like(f"%{escape_like(query)}%"),
                    Announcement.content.like(f"%{escape_like(query)}%")
                )
            )

        # 确保排序稳定
        valid_sort_fields = ['id', 'title', 'created_at', 'updated_at']
        if sort_by not in valid_sort_fields:
            sort_by = 'created_at'  # 默认排序字段

        # 获取排序字段属性
        sort_attr = getattr(Announcement, sort_by)

        # 应用排序
        if sort_order.lower() == 'desc':
            announcements_query = announcements_query.order_by(sort_attr.desc(), Announcement.id.desc())
        else:
            announcements_query = announcements_query.order_by(sort_attr, Announcement.id)

        # 获取所有公告
        announcements = announcements_query.all()

        # 转换结果为字典列表
        items_list = [item.to_dict() for item in announcements]

        # 返回前端期望的格式
        response = {
            'items': items_list,
            'total': len(items_list)
        }

        return jsonify(response), 200
    except SQLAlchemyError as e:
        # 数据库错误处理
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        # 其他异常处理
        current_app.logger.error(f"获取公告时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 获取单个公告接口
@common.route('/announcements/<int:announcement_id>', methods=['GET'])
# 匿名公开详情端点：单行查询成本低于列表，限流放宽
@ip_rate_limit('common_detail', 120, 60)
def get_announcement(announcement_id):
    try:
        # 查询指定ID的公告
        announcement = Announcement.query.get(announcement_id)

        # 检查是否存在
        if not announcement:
            return jsonify({"error": "公告不存在"}), 404

        # 返回公告信息
        return jsonify(announcement.to_dict()), 200
    except SQLAlchemyError as e:
        # 数据库错误处理
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        # 其他异常处理
        current_app.logger.error(f"获取公告详情时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500