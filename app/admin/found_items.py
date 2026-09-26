from datetime import datetime

from flask import current_app, request, jsonify
from sqlalchemy.exc import SQLAlchemyError
from app import db
from app.models import FoundItem, ItemMatch
from app.utils.page import paginate_query, escape_like
from . import admin
from ..utils.decorators import admin_required


# 查询所有拾物信息接口
@admin.route('/found-items', methods=['GET'])
@admin_required
def get_all_found_items():
    try:
        # 获取查询参数
        page = request.args.get('page', 1, type=int)
        size = request.args.get('size', 10, type=int)
        sort_by = request.args.get('sort_by', 'id')
        sort_order = request.args.get('sort_order', 'desc')
        query = request.args.get('query', '')

        # 构建查询
        found_items_query = FoundItem.query

        # 应用搜索
        if query:
            from sqlalchemy import or_
            found_items_query = found_items_query.filter(
                or_(
                    FoundItem.name.like(f"%{escape_like(query)}%"),
                    FoundItem.category.like(f"%{escape_like(query)}%"),
                    FoundItem.location.like(f"%{escape_like(query)}%"),
                    FoundItem.contact.like(f"%{escape_like(query)}%")
                )
            )

        # 使用分页查询，传递排序参数
        result = paginate_query(
            found_items_query,
            default_page=page,
            default_size=size,
            sortable_fields=['id', 'name', 'category', 'location',
                             'is_completed', 'is_under_review', 'found_time', 'user_id',
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
        current_app.logger.error(f"查询拾物信息时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 查询所有未审核拾物接口
@admin.route('/found-items/unreviewed', methods=['GET'])
@admin_required
def get_all_unreviewed_found_items():
    try:
        # 获取查询参数
        page = request.args.get('page', 1, type=int)
        size = request.args.get('size', 10, type=int)
        sort_by = request.args.get('sort_by', 'id')
        sort_order = request.args.get('sort_order', 'desc')
        keyword = request.args.get('keyword', '')

        # 构建未审核拾物的基础查询
        unreviewed_query = FoundItem.query.filter_by(is_under_review=True)

        # 应用关键词搜索（与普通列表端点一致：名称/类别/地点/联系方式模糊匹配，有值才过滤）
        if keyword:
            from sqlalchemy import or_
            unreviewed_query = unreviewed_query.filter(
                or_(
                    FoundItem.name.like(f"%{escape_like(keyword)}%"),
                    FoundItem.category.like(f"%{escape_like(keyword)}%"),
                    FoundItem.location.like(f"%{escape_like(keyword)}%"),
                    FoundItem.contact.like(f"%{escape_like(keyword)}%")
                )
            )

        # 查询所有未审核的拾物记录，应用分页和排序
        result = paginate_query(
            unreviewed_query,
            default_page=page,
            default_size=size,
            sortable_fields=['id', 'name', 'category', 'location',
                             'is_completed', 'is_under_review', 'found_time', 'user_id',
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

        current_app.logger.info("成功查询所有未审核的拾物信息")
        return jsonify(response), 200
    except SQLAlchemyError as e:
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"查询未审核拾物信息时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 根据参数查询拾物信息接口
@admin.route('/found-items/sift', methods=['GET'])
@admin_required
def sift_found_items():
    try:
        # 获取查询参数
        page = request.args.get('page', 1, type=int)
        size = request.args.get('size', 10, type=int)
        category = request.args.get('category')
        name = request.args.get('name')
        location = request.args.get('location')
        is_completed = request.args.get('is_completed')
        user_id = request.args.get('user_id')
        keyword = request.args.get('keyword')

        # 获取时间范围参数
        found_time_start = request.args.get('found_time_start')
        found_time_end = request.args.get('found_time_end')
        created_at_start = request.args.get('created_at_start')
        created_at_end = request.args.get('created_at_end')

        # 时间参数格式预检：非法字符串会参与列比较导致 MySQL 报错落入 500（对齐 common 端 B5 修复）
        for param_name, param_value in (('found_time_start', found_time_start),
                                        ('found_time_end', found_time_end),
                                        ('created_at_start', created_at_start),
                                        ('created_at_end', created_at_end)):
            if param_value:
                try:
                    datetime.fromisoformat(param_value)
                except (ValueError, TypeError):
                    return jsonify({"error": f"{param_name} 时间格式无效"}), 400

        # 创建基础查询
        query = FoundItem.query

        # 处理各种筛选参数
        if name:
            query = query.filter(FoundItem.name.like(f"%{escape_like(name)}%"))
        if category:
            query = query.filter(FoundItem.category == category)
        if location:
            query = query.filter(FoundItem.location.like(f"%{escape_like(location)}%"))
        if user_id:
            query = query.filter(FoundItem.user_id == int(user_id))

        # 处理关键词筛选（可选参数：名称/类别/地点/联系方式模糊匹配，不传不过滤）
        if keyword:
            from sqlalchemy import or_
            query = query.filter(
                or_(
                    FoundItem.name.like(f"%{escape_like(keyword)}%"),
                    FoundItem.category.like(f"%{escape_like(keyword)}%"),
                    FoundItem.location.like(f"%{escape_like(keyword)}%"),
                    FoundItem.contact.like(f"%{escape_like(keyword)}%")
                )
            )

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
                query = query.filter(FoundItem.is_completed == is_completed_bool)

        # 添加对 is_under_review 参数的处理
        if 'is_under_review' in request.args:
            # 将字符串转换为布尔值
            is_under_review_str = request.args['is_under_review'].lower()
            is_under_review = is_under_review_str == 'true'

            # 使用转换后的布尔值进行筛选
            query = query.filter(FoundItem.is_under_review == is_under_review)

            # 记录日志以便调试
            current_app.logger.info(f"拾物筛选审核状态: {is_under_review_str} -> {is_under_review}")

        # 处理拾取时间范围筛选：纯日期（YYYY-MM-DD）的结束值补齐到当天 23:59:59，
        # 完整时间戳直接使用（原实现对任何 end 值都盲拼后缀，完整时间戳会变成非法值导致 500）
        if found_time_start and found_time_end:
            found_time_end_with_time = f"{found_time_end} 23:59:59" if len(found_time_end) == 10 else found_time_end
            query = query.filter(
                FoundItem.found_time >= found_time_start,
                FoundItem.found_time <= found_time_end_with_time
            )
            current_app.logger.info(f"筛选拾取时间范围: {found_time_start} 到 {found_time_end_with_time}")

        # 处理创建时间范围筛选（同上）
        if created_at_start and created_at_end:
            created_at_end_with_time = f"{created_at_end} 23:59:59" if len(created_at_end) == 10 else created_at_end
            query = query.filter(
                FoundItem.created_at >= created_at_start,
                FoundItem.created_at <= created_at_end_with_time
            )
            current_app.logger.info(f"筛选创建时间范围: {created_at_start} 到 {created_at_end_with_time}")

        # 处理排序
        sort_by = request.args.get('sort_by', 'id')
        sort_order = request.args.get('sort_order', 'desc')

        # 处理排序（白名单限制）
        sortable_fields = ('id', 'name', 'category', 'location', 'is_completed', 'is_under_review',
                           'found_time', 'user_id', 'created_at', 'updated_at')
        if sort_by in sortable_fields:
            order_attr = getattr(FoundItem, sort_by)
            if sort_order == 'desc':
                query = query.order_by(order_attr.desc())
            else:
                query = query.order_by(order_attr.asc())
        else:
            query = query.order_by(FoundItem.id.desc())

        # 分页处理（限制每页数量上限；error_out=False：页码越界返回空列表而非内部 abort 404，
        # 避免 NotFound 被末尾 except Exception 吞成 500，与 paginate_query 行为一致）
        paginated_items = query.paginate(page=max(page, 1), per_page=min(max(size, 1), 100), error_out=False)

        # 返回分页结果（page/size 回显实际执行值，避免原始参数为负数/超大值时分页控件错乱）
        return jsonify({
            'items': [item.to_dict() for item in paginated_items.items],
            'total': paginated_items.total,
            'page': paginated_items.page,
            'size': paginated_items.per_page
        })
    except ValueError as e:
        current_app.logger.error(f"参数错误: {str(e)}")
        return jsonify({"error": "参数错误"}), 400
    except SQLAlchemyError as e:
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"根据参数查询拾物信息时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 管理员删除用户拾物信息接口
@admin.route('/found-items/<int:item_id>', methods=['DELETE'])
@admin_required
def admin_delete_found_item(item_id):
    try:
        # 查找拾物记录
        found_item = FoundItem.query.get(item_id)
        if not found_item:
            current_app.logger.warning(f"拾物 ID {item_id} 未找到")
            return jsonify({"error": "拾物未找到"}), 404

        ItemMatch.query.filter_by(found_item_id=item_id).delete(synchronize_session=False)
        # 删除记录
        db.session.delete(found_item)
        db.session.commit()

        current_app.logger.info(f"拾物 ID {item_id} 删除成功")
        return jsonify({"message": "拾物删除成功"}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"删除拾物时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 审核拾物接口
@admin.route('/found-items/<int:item_id>/review', methods=['PUT'])
@admin_required
def review_found_item(item_id):
    try:
        # 查找拾物记录
        found_item = FoundItem.query.get(item_id)
        if not found_item:
            current_app.logger.warning(f"拾物 ID {item_id} 未找到")
            return jsonify({"error": "拾物未找到"}), 404

        # 更新审核状态
        found_item.is_under_review = False  # 设置为已审核
        db.session.commit()

        current_app.logger.info(f"拾物 ID {item_id} 审核成功")
        return jsonify({"message": "拾物审核成功"}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"审核拾物时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 取消审核拾物接口
@admin.route('/found-items/<int:id>/cancel-review', methods=['PUT'])
@admin_required
def cancel_review_found_item(id):
    try:
        # 查询拾物记录
        found_item = FoundItem.query.get(id)
        if not found_item:
            current_app.logger.warning(f"拾物 ID {id} 未找到")
            return jsonify({"error": "拾物未找到"}), 404

        # 检查是否已经是未审核状态
        if found_item.is_under_review:
            return jsonify({"message": "该拾物已经是未审核状态"}), 400

        # 更新为未审核状态
        found_item.is_under_review = True
        db.session.commit()

        current_app.logger.info(f"管理员取消审核拾物ID: {id}")
        return jsonify({"message": "取消审核成功"}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"取消审核拾物时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500
