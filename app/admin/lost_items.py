from datetime import datetime

from flask import current_app, request, jsonify
from sqlalchemy.exc import SQLAlchemyError
from app import db
from app.models import LostItem, ItemMatch
from app.utils.page import paginate_query, escape_like
from . import admin
from ..utils.decorators import admin_required


# 查询所有失物信息接口
@admin.route('/lost-items', methods=['GET'])
@admin_required
def get_all_lost_items():
    try:
        # 获取查询参数
        page = request.args.get('page', 1, type=int)
        size = request.args.get('size', 10, type=int)
        sort_by = request.args.get('sort_by', 'id')
        sort_order = request.args.get('sort_order', 'desc')
        query = request.args.get('query', '')

        # 构建查询
        lost_items_query = LostItem.query

        # 应用搜索
        if query:
            from sqlalchemy import or_
            lost_items_query = lost_items_query.filter(
                or_(
                    LostItem.name.like(f"%{escape_like(query)}%"),
                    LostItem.category.like(f"%{escape_like(query)}%"),
                    LostItem.location.like(f"%{escape_like(query)}%"),
                    LostItem.contact.like(f"%{escape_like(query)}%")
                )
            )

        # 使用分页查询，传递排序参数
        result = paginate_query(
            lost_items_query,
            default_page=page,
            default_size=size,
            sortable_fields=['id', 'name', 'category', 'location',
                             'is_completed', 'is_under_review', 'lost_time', 'user_id',
                             'created_at', 'updated_at'],
            sort_by=sort_by,
            sort_order=sort_order
        )

        # 检查items是否为列表，否则报错
        if not isinstance(result['items'], list):
            raise TypeError(f"Expected list but got {type(result['items'])}")

        # 转换为字典列表
        items_list = [item.to_dict() for item in result['items']]

        # 构建响应
        response = {
            'items': items_list,
            'total': result['total'],
            'page': result['page'],
            'size': result['size']
        }

        return jsonify(response), 200
    except Exception as e:
        current_app.logger.error(f"查询失物信息时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 查询所有未审核失物接口
@admin.route('/lost-items/unreviewed', methods=['GET'])
@admin_required
def get_all_unreviewed_lost_items():
    try:
        # 获取查询参数
        page = request.args.get('page', 1, type=int)
        size = request.args.get('size', 10, type=int)
        sort_by = request.args.get('sort_by', 'id')
        sort_order = request.args.get('sort_order', 'desc')

        # 查询所有未审核的失物记录，应用分页和排序
        result = paginate_query(
            LostItem.query.filter_by(is_under_review=True),
            default_page=page,
            default_size=size,
            sortable_fields=['id', 'name', 'category', 'location',
                             'is_completed', 'is_under_review', 'lost_time', 'user_id',
                             'created_at', 'updated_at'],
            sort_by=sort_by,
            sort_order=sort_order
        )

        # 检查items是否为列表，否则报错
        if not isinstance(result['items'], list):
            raise TypeError(f"Expected list but got {type(result['items'])}")

        # 转换为字典列表
        items_list = [item.to_dict() for item in result['items']]

        # 构建响应
        response = {
            'items': items_list,
            'total': result['total'],
            'page': result['page'],
            'size': result['size']
        }

        current_app.logger.info("成功查询所有未审核的失物信息")
        return jsonify(response), 200
    except SQLAlchemyError as e:
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"查询未审核失物信息时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 根据参数查询失物信息接口
@admin.route('/lost-items/sift', methods=['GET'])
@admin_required
def sift_lost_items():
    try:
        # 获取查询参数
        page = request.args.get('page', 1, type=int)
        size = request.args.get('size', 10, type=int)
        category = request.args.get('category')
        name = request.args.get('name')
        location = request.args.get('location')
        is_completed = request.args.get('is_completed')
        user_id = request.args.get('user_id')

        # 获取时间范围参数
        lost_time_start = request.args.get('lost_time_start')
        lost_time_end = request.args.get('lost_time_end')
        created_at_start = request.args.get('created_at_start')
        created_at_end = request.args.get('created_at_end')

        # 时间参数格式预检：非法字符串会参与列比较导致 MySQL 报错落入 500（对齐 common 端 B5 修复）
        for param_name, param_value in (('lost_time_start', lost_time_start),
                                        ('lost_time_end', lost_time_end),
                                        ('created_at_start', created_at_start),
                                        ('created_at_end', created_at_end)):
            if param_value:
                try:
                    datetime.fromisoformat(param_value)
                except (ValueError, TypeError):
                    return jsonify({"error": f"{param_name} 时间格式无效"}), 400

        # 创建基础查询
        query = LostItem.query

        # 处理各种筛选参数
        if name:
            query = query.filter(LostItem.name.like(f"%{escape_like(name)}%"))
        if category:
            query = query.filter(LostItem.category == category)
        if location:
            query = query.filter(LostItem.location.like(f"%{escape_like(location)}%"))
        if user_id:
            query = query.filter(LostItem.user_id == int(user_id))

        # 处理 is_completed 参数
        if is_completed is not None:
            # 将字符串转换为布尔值
            if is_completed.lower() == 'true':
                is_completed_bool = True
            elif is_completed.lower() == 'false':
                is_completed_bool = False
            else:
                is_completed_bool = None

            if is_completed_bool is not None:
                query = query.filter(LostItem.is_completed == is_completed_bool)

        # 添加对 is_under_review 参数的处理
        if 'is_under_review' in request.args:
            # 将字符串转换为布尔值
            is_under_review_str = request.args['is_under_review'].lower()
            is_under_review = is_under_review_str == 'true'

            # 使用转换后的布尔值进行筛选
            query = query.filter(LostItem.is_under_review == is_under_review)

            # 记录日志以便调试
            current_app.logger.info(f"筛选审核状态: {is_under_review_str} -> {is_under_review}")

        # 处理丢失时间范围筛选：纯日期（YYYY-MM-DD）的结束值补齐到当天 23:59:59，
        # 完整时间戳直接使用（原实现对任何 end 值都盲拼后缀，完整时间戳会变成非法值导致 500）
        if lost_time_start and lost_time_end:
            lost_time_end_with_time = f"{lost_time_end} 23:59:59" if len(lost_time_end) == 10 else lost_time_end
            query = query.filter(
                LostItem.lost_time >= lost_time_start,
                LostItem.lost_time <= lost_time_end_with_time
            )
            current_app.logger.info(f"筛选丢失时间范围: {lost_time_start} 到 {lost_time_end_with_time}")

        # 处理创建时间范围筛选（同上）
        if created_at_start and created_at_end:
            created_at_end_with_time = f"{created_at_end} 23:59:59" if len(created_at_end) == 10 else created_at_end
            query = query.filter(
                LostItem.created_at >= created_at_start,
                LostItem.created_at <= created_at_end_with_time
            )
            current_app.logger.info(f"筛选创建时间范围: {created_at_start} 到 {created_at_end_with_time}")

        # 处理排序
        sort_by = request.args.get('sort_by', 'id')
        sort_order = request.args.get('sort_order', 'desc')

        # 处理排序（白名单限制）
        sortable_fields = ('id', 'name', 'category', 'location', 'is_completed', 'is_under_review',
                           'lost_time', 'user_id', 'created_at', 'updated_at')
        if sort_by in sortable_fields:
            order_attr = getattr(LostItem, sort_by)
            if sort_order == 'desc':
                query = query.order_by(order_attr.desc())
            else:
                query = query.order_by(order_attr.asc())
        else:
            query = query.order_by(LostItem.id.desc())

        # 分页处理（限制每页数量上限）
        paginated_items = query.paginate(page=max(page, 1), per_page=min(max(size, 1), 100))

        # 返回分页结果
        return jsonify({
            'items': [item.to_dict() for item in paginated_items.items],
            'total': paginated_items.total,
            'page': page,
            'size': size
        })
    except ValueError as e:
        current_app.logger.error(f"参数错误: {str(e)}")
        return jsonify({"error": "参数错误"}), 400
    except SQLAlchemyError as e:
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"根据参数查询失物信息时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 管理员删除用户失物信息接口
@admin.route('/lost-items/<int:item_id>', methods=['DELETE'])
@admin_required
def admin_delete_lost_item(item_id):
    try:
        # 查找失物记录
        lost_item = LostItem.query.get(item_id)
        if not lost_item:
            current_app.logger.warning(f"失物 ID {item_id} 未找到")
            return jsonify({"error": "失物未找到"}), 404

        ItemMatch.query.filter_by(lost_item_id=item_id).delete(synchronize_session=False)
        # 删除记录
        db.session.delete(lost_item)
        db.session.commit()

        current_app.logger.info(f"失物 ID {item_id} 删除成功")
        return jsonify({"message": "失物删除成功"}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"删除失物时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 审核失物接口
@admin.route('/lost-items/<int:item_id>/review', methods=['PUT'])
@admin_required
def review_lost_item(item_id):
    try:
        # 查找失物记录
        lost_item = LostItem.query.get(item_id)
        if not lost_item:
            current_app.logger.warning(f"失物 ID {item_id} 未找到")
            return jsonify({"error": "失物未找到"}), 404

        # 更新审核状态
        lost_item.is_under_review = False  # 设置为已审核
        db.session.commit()

        current_app.logger.info(f"失物 ID {item_id} 审核成功")
        return jsonify({"message": "失物审核成功"}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"审核失物时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 取消审核失物接口
@admin.route('/lost-items/<int:id>/cancel-review', methods=['PUT'])
@admin_required
def cancel_review_lost_item(id):
    try:
        # 查询失物记录
        lost_item = LostItem.query.get(id)
        if not lost_item:
            current_app.logger.warning(f"失物 ID {id} 未找到")
            return jsonify({"error": "失物未找到"}), 404

        # 检查是否已经是未审核状态
        if lost_item.is_under_review:
            return jsonify({"message": "该失物已经是未审核状态"}), 400

        # 更新为未审核状态
        lost_item.is_under_review = True
        db.session.commit()

        current_app.logger.info(f"管理员取消审核失物ID: {id}")
        return jsonify({"message": "取消审核成功"}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"取消审核失物时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500
