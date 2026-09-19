from datetime import datetime

from . import common
from flask import request, jsonify, current_app
from app.models import FoundItem
from sqlalchemy.exc import SQLAlchemyError
from app.utils.page import paginate_query, escape_like
from app.utils.ratelimit import ip_rate_limit


# 查询所有已审核的拾物接口
@common.route('/found-items', methods=['GET'])
# 匿名公开列表端点：按 IP 限流防批量抓取
@ip_rate_limit('common_list', 60, 60)
def get_all_found_items():
    try:
        # 获取查询参数
        page = request.args.get('page', 1, type=int)
        size = request.args.get('size', 10, type=int)
        sort_by = request.args.get('sort_by', 'id')
        sort_order = request.args.get('sort_order', 'desc')
        query = request.args.get('query', '')

        # 构建查询
        found_items_query = FoundItem.query.filter_by(is_under_review=False)

        # 应用搜索（转义LIKE通配符，防止用户输入%/_扰动匹配）
        if query:
            from sqlalchemy import or_
            found_items_query = found_items_query.filter(
                or_(
                    FoundItem.name.like(f"%{escape_like(query)}%"),
                    FoundItem.category.like(f"%{escape_like(query)}%"),
                    FoundItem.location.like(f"%{escape_like(query)}%"),
                    FoundItem.description.like(f"%{escape_like(query)}%")
                )
            )

        # 查询所有已审核的拾物记录并分页
        result = paginate_query(
            found_items_query,
            default_page=page,
            default_size=size,
            sortable_fields=['id', 'name', 'category', 'location', 'found_time', 'created_at', 'updated_at'],
            sort_by=sort_by,
            sort_order=sort_order
        )

        # 将拾物记录转换为字典列表
        items_list = [item.to_dict() for item in result['items']]

        # 返回前端期望的格式
        response = {
            'items': items_list,
            'total': result['total'],
            'page': result['page'],
            'size': result['size']
        }

        return jsonify(response), 200
    except SQLAlchemyError as e:
        # 数据库错误处理
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        # 其他异常处理
        current_app.logger.error(f"发生意外错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 筛选已审核的拾物接口
@common.route('/found-items/sift', methods=['GET'])
# 匿名公开筛选端点：按 IP 限流防批量抓取
@ip_rate_limit('common_list', 60, 60)
def sift_found_items():
    try:
        # 获取查询参数
        page = request.args.get('page', 1, type=int)
        size = request.args.get('size', 10, type=int)
        sort_by = request.args.get('sort_by', 'id')
        sort_order = request.args.get('sort_order', 'desc')
        category = request.args.get('category')
        name = request.args.get('name')
        location = request.args.get('location')
        is_completed = request.args.get('is_completed')
        user_id = request.args.get('user_id')
        # 新增时间范围参数
        start_time = request.args.get('start_time')
        end_time = request.args.get('end_time')

        # 构建查询条件，只查询已审核的拾物
        query = FoundItem.query.filter_by(is_under_review=False)
        if category:
            query = query.filter(FoundItem.category == category)  # 精确匹配
        if name:
            query = query.filter(FoundItem.name.ilike(f"%{escape_like(name)}%"))  # 模糊匹配（转义LIKE通配符）
        if location:
            query = query.filter(FoundItem.location.ilike(f"%{escape_like(location)}%"))  # 模糊匹配（转义LIKE通配符）
        if is_completed is not None:
            is_completed_bool = is_completed.lower() == 'true'
            query = query.filter(FoundItem.is_completed == is_completed_bool)
        if user_id:
            query = query.filter(FoundItem.user_id == user_id)  # 精确匹配
        # 新增时间范围筛选（先校验时间格式，防止非法字符串参与比较导致异常）
        for param_name, param_value in (('start_time', start_time), ('end_time', end_time)):
            if param_value:
                try:
                    datetime.fromisoformat(param_value)
                except ValueError:
                    return jsonify({"error": f"{param_name} 时间格式无效"}), 400

        if start_time:
            # 使用精确时间比较，而不是只比较日期部分
            query = query.filter(FoundItem.found_time >= start_time)
        if end_time:
            # 使用精确时间比较，而不是只比较日期部分
            query = query.filter(FoundItem.found_time <= end_time)

        # 执行查询并分页
        result = paginate_query(
            query,
            default_page=page,
            default_size=size,
            sortable_fields=['id', 'name', 'category', 'location', 'found_time', 'created_at', 'updated_at'],
            sort_by=sort_by,
            sort_order=sort_order
        )

        # 将记录转换为字典列表
        items_list = [item.to_dict() for item in result['items']]

        # 返回前端期望的格式
        response = {
            'items': items_list,
            'total': result['total'],
            'page': result['page'],
            'size': result['size']
        }

        return jsonify(response), 200
    except SQLAlchemyError as e:
        # 数据库错误处理
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        # 其他异常处理
        current_app.logger.error(f"发生意外错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 获取单个拾物详情接口
@common.route('/found-items/<int:item_id>', methods=['GET'])
# 匿名公开详情端点：单行查询成本低于列表，限流放宽
@ip_rate_limit('common_detail', 120, 60)
def get_found_item_detail(item_id):
    try:
        # 查询指定ID的拾物记录
        found_item = FoundItem.query.filter_by(id=item_id, is_under_review=False).first()

        # 如果找不到记录或记录正在审核中，返回404错误
        if not found_item:
            return jsonify({"error": "未找到该拾物记录或记录正在审核中"}), 404

        # 返回拾物详情
        return jsonify(found_item.to_dict()), 200
    except SQLAlchemyError as e:
        # 数据库错误处理
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        # 其他异常处理
        current_app.logger.error(f"发生意外错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500
