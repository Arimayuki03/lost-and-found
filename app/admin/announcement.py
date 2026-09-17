import datetime
from flask import request, jsonify, current_app
from sqlalchemy.exc import SQLAlchemyError
from app import db
from app.models import Announcement
from app.utils.decorators import admin_required
from app.utils.page import escape_like
from . import admin


# 获取所有公告
@admin.route('/announcements', methods=['GET'])
@admin_required
def get_announcements():
    try:
        page = request.args.get('page', 1, type=int)
        size = request.args.get('size', 10, type=int)
        page = max(page, 1)
        size = min(max(size, 1), 100)
        query = request.args.get('query', '')
        sort_by = request.args.get('sort_by', 'created_at')
        sort_order = request.args.get('sort_order', 'desc')

        # 构建基础查询
        announcements_query = Announcement.query

        # 添加搜索条件
        if query:
            announcements_query = announcements_query.filter(
                Announcement.title.ilike(f"%{escape_like(query)}%") |
                Announcement.content.ilike(f"%{escape_like(query)}%")
            )

        # 添加排序 - 确保排序字段存在
        valid_sort_fields = ['id', 'title', 'content', 'created_at', 'updated_at']
        if sort_by not in valid_sort_fields:
            sort_by = 'created_at'  # 默认排序字段

        # 获取排序字段属性
        sort_attr = getattr(Announcement, sort_by)

        # 应用排序
        if sort_order.lower() == 'desc':
            announcements_query = announcements_query.order_by(sort_attr.desc())
        else:
            announcements_query = announcements_query.order_by(sort_attr)

        # 执行分页查询
        total = announcements_query.count()
        announcements = announcements_query.offset((page - 1) * size).limit(size).all()

        # 转换结果为字典列表
        announcements_list = [announcement.to_dict() for announcement in announcements]

        # 计算总页数
        total_pages = (total + size - 1) // size if size > 0 else 0

        return jsonify({
            'items': announcements_list,
            'total': total,
            'page': page,
            'size': size,
            'pages': total_pages
        }), 200

    except SQLAlchemyError as e:
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"查询公告时发生错误: {str(e)}")
        return jsonify({"error": "查询公告时发生错误"}), 500


# 添加公告
@admin.route('/announcements', methods=['POST'])
@admin_required
def add_announcement():
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'error': '请求体不能为空'}), 400

        # 验证必填字段
        if not data.get('title') or not data.get('content'):
            return jsonify({'error': '标题和内容不能为空'}), 400

        # 类型与长度校验（title 库列为 String(200)）
        if not isinstance(data['title'], str) or len(data['title']) > 200:
            return jsonify({'error': '标题需为长度不超过200的字符串'}), 400
        if not isinstance(data['content'], str):
            return jsonify({'error': '内容需为字符串'}), 400

        # 创建新公告
        new_announcement = Announcement(
            title=data.get('title'),
            content=data.get('content'),
            created_at=datetime.datetime.now()
        )

        # 保存到数据库
        db.session.add(new_announcement)
        db.session.commit()

        return jsonify(new_announcement.to_dict()), 201

    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"添加公告时发生错误: {str(e)}")
        return jsonify({"error": "添加公告时发生错误"}), 500


# 更新公告
@admin.route('/announcements/<int:announcement_id>', methods=['PUT'])
@admin_required
def update_announcement(announcement_id):
    try:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({'error': '请求体不能为空'}), 400

        # 查找要更新的公告
        announcement = Announcement.query.get(announcement_id)
        if not announcement:
            return jsonify({'error': '公告不存在'}), 404

        # 更新公告（类型与长度校验，非字符串直接拒绝）
        if 'title' in data:
            if not isinstance(data['title'], str) or not data['title'] or len(data['title']) > 200:
                return jsonify({'error': '标题需为非空字符串且长度不超过200'}), 400
            announcement.title = data['title']
        if 'content' in data:
            if not isinstance(data['content'], str) or not data['content']:
                return jsonify({'error': '内容需为非空字符串'}), 400
            announcement.content = data['content']

        # 更新时间
        announcement.updated_at = datetime.datetime.now()

        # 保存到数据库
        db.session.commit()

        return jsonify(announcement.to_dict()), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"更新公告时发生错误: {str(e)}")
        return jsonify({"error": "更新公告时发生错误"}), 500


# 删除公告
@admin.route('/announcements/<int:announcement_id>', methods=['DELETE'])
@admin_required
def delete_announcement(announcement_id):
    try:
        # 查找要删除的公告
        announcement = Announcement.query.get(announcement_id)
        if not announcement:
            return jsonify({'error': '公告不存在'}), 404

        # 从数据库中删除
        db.session.delete(announcement)
        db.session.commit()

        return jsonify({'message': '公告已成功删除'}), 200

    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"删除公告时发生错误: {str(e)}")
        return jsonify({"error": "删除公告时发生错误"}), 500
