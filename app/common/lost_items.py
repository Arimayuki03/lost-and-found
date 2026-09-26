from . import common
from flask import request, jsonify, current_app
from app.models import LostItem
from sqlalchemy.exc import SQLAlchemyError
from app.utils.page import paginate_query, escape_like, parse_local_datetime
from app.utils.ratelimit import ip_rate_limit


# 查询所有已审核的失物接口
@common.route('/lost-items', methods=['GET'])
# 匿名公开列表端点：按 IP 限流防批量抓取
@ip_rate_limit('common_list', 60, 60)
def get_all_lost_items():
    try:
        # 获取查询参数
        page = request.args.get('page', 1, type=int)
        size = request.args.get('size', 10, type=int)
        sort_by = request.args.get('sort_by', 'id')
        sort_order = request.args.get('sort_order', 'desc')
        query = request.args.get('query', '')

        # 构建查询
        lost_items_query = LostItem.query.filter_by(is_under_review=False)

        # 应用搜索（转义LIKE通配符，防止用户输入%/_扰动匹配）
        if query:
            from sqlalchemy import or_
            lost_items_query = lost_items_query.filter(
                or_(
                    LostItem.name.like(f"%{escape_like(query)}%"),
                    LostItem.category.like(f"%{escape_like(query)}%"),
                    LostItem.location.like(f"%{escape_like(query)}%"),
                    LostItem.description.like(f"%{escape_like(query)}%")
                )
            )

        # 查询所有已审核的失物记录并分页
        result = paginate_query(
            lost_items_query,
            default_page=page,
            default_size=size,
            sortable_fields=['id', 'name', 'category', 'location', 'lost_time', 'created_at', 'updated_at'],
            sort_by=sort_by,
            sort_order=sort_order
        )

        # 将失物记录转换为字典列表
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


# 筛选已审核的失物接口
@common.route('/lost-items/sift', methods=['GET'])
# 匿名公开筛选端点：按 IP 限流防批量抓取
@ip_rate_limit('common_list', 60, 60)
def sift_lost_items():
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

        # 构建查询条件，只查询已审核的失物
        query = LostItem.query.filter_by(is_under_review=False)
        if category:
            query = query.filter(LostItem.category == category)  # 精确匹配
        if name:
            query = query.filter(LostItem.name.ilike(f"%{escape_like(name)}%"))  # 模糊匹配（转义LIKE通配符）
        if location:
            query = query.filter(LostItem.location.ilike(f"%{escape_like(location)}%"))  # 模糊匹配（转义LIKE通配符）
        if is_completed is not None:
            is_completed_bool = is_completed.lower() == 'true'
            query = query.filter(LostItem.is_completed == is_completed_bool)
        if user_id:
            # user_id 必须为整数（对齐 admin 端），非数字串直接拒绝而非参与列比较
            try:
                uid = int(user_id)
            except (TypeError, ValueError):
                return jsonify({"error": "user_id 需为整数"}), 400
            query = query.filter(LostItem.user_id == uid)  # 精确匹配
        # 新增时间范围筛选（校验后立刻转为 datetime 对象传入 filter：消除"Python 校验
        # 通过但 MySQL 不认的字符串"导致的 500，同时归一化时区后缀为钟面时间）
        start_dt = end_dt = None
        for param_name, param_value in (('start_time', start_time), ('end_time', end_time)):
            if param_value:
                try:
                    converted = parse_local_datetime(param_value, param_name)
                except (TypeError, ValueError):
                    return jsonify({"error": f"{param_name} 时间格式无效"}), 400
                if param_name == 'start_time':
                    start_dt = converted
                else:
                    end_dt = converted

        if start_dt is not None:
            # 使用精确时间比较（datetime 对象），而不是只比较日期部分
            query = query.filter(LostItem.lost_time >= start_dt)
        if end_dt is not None:
            # 使用精确时间比较（datetime 对象），而不是只比较日期部分
            query = query.filter(LostItem.lost_time <= end_dt)

        # 执行查询并分页
        result = paginate_query(
            query,
            default_page=page,
            default_size=size,
            sortable_fields=['id', 'name', 'category', 'location', 'lost_time', 'created_at', 'updated_at'],
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


# 获取单个失物详情接口
@common.route('/lost-items/<int:item_id>', methods=['GET'])
# 匿名公开详情端点：单行查询成本低于列表，限流放宽
@ip_rate_limit('common_detail', 120, 60)
def get_lost_item_detail(item_id):
    try:
        # 查询指定ID的失物记录
        lost_item = LostItem.query.filter_by(id=item_id, is_under_review=False).first()

        # 如果找不到记录或记录正在审核中，返回404错误
        if not lost_item:
            return jsonify({"error": "未找到该失物记录或记录正在审核中"}), 404

        # 返回失物详情
        return jsonify(lost_item.to_dict()), 200
    except SQLAlchemyError as e:
        # 数据库错误处理
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        # 其他异常处理
        current_app.logger.error(f"发生意外错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500
