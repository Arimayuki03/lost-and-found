from . import common
from flask import request, jsonify, current_app
from app.models import LostItem, FoundItem
from sqlalchemy.exc import SQLAlchemyError
from app.utils.page import escape_like
from app.utils.ratelimit import ip_rate_limit


# 搜索接口，根据关键词搜索物品
@common.route('/search', methods=['GET'])
# 匿名端点且为双 LIKE UNION 全表扫描（cost 高），按 IP 限流防慢查询刷库
@ip_rate_limit('common_search', 30, 60)
def search_items():
    try:
        # 获取查询参数（限制分页范围）
        page = max(request.args.get('page', 1, type=int) or 1, 1)
        size = min(max(request.args.get('size', 10, type=int) or 10, 1), 100)
        sort_by = request.args.get('sort_by', 'created_at')
        sort_order = request.args.get('sort_order', 'desc')
        query = request.args.get('query', '')  # 搜索关键词
        item_type = request.args.get('type', 'lost')  # 物品类型：lost-失物, found-招领，默认为失物

        # 记录搜索请求
        current_app.logger.info(f"搜索请求: 关键词={query}, 类型={item_type}")

        # 根据类型决定搜索范围
        if item_type == 'lost':
            # 构建失物查询
            base_query = LostItem.query.filter_by(is_under_review=False)

            # 应用关键词搜索 - 分别在名称和描述中搜索
            if query:
                # 在名称中搜索（转义LIKE通配符，防止用户输入%/_扰动匹配）
                name_query = base_query.filter(LostItem.name.like(f"%{escape_like(query)}%"))

                # 在描述中搜索
                description_query = base_query.filter(LostItem.description.like(f"%{escape_like(query)}%"))

                # 合并查询结果（使用UNION去重）
                items_query = name_query.union(description_query)
            else:
                items_query = base_query

            # 应用排序（白名单限制，防止任意属性访问导致 500）
            sortable_fields = ('id', 'name', 'category', 'location', 'lost_time', 'created_at', 'updated_at')
            if sort_by not in sortable_fields:
                sort_by = 'created_at'
            if sort_order == 'desc':
                items_query = items_query.order_by(getattr(LostItem, sort_by).desc())
            else:
                items_query = items_query.order_by(getattr(LostItem, sort_by).asc())

            # 获取总数
            total = items_query.count()

            # 应用分页
            items_query = items_query.offset((page - 1) * size).limit(size)

            # 转换为字典列表
            items_list = [item.to_dict() for item in items_query.all()]

        else:  # found
            # 构建招领查询
            base_query = FoundItem.query.filter_by(is_under_review=False)

            # 应用关键词搜索 - 分别在名称和描述中搜索
            if query:
                # 在名称中搜索（转义LIKE通配符，防止用户输入%/_扰动匹配）
                name_query = base_query.filter(FoundItem.name.like(f"%{escape_like(query)}%"))

                # 在描述中搜索
                description_query = base_query.filter(FoundItem.description.like(f"%{escape_like(query)}%"))

                # 合并查询结果（使用UNION去重）
                items_query = name_query.union(description_query)
            else:
                items_query = base_query

            # 应用排序（白名单限制，防止任意属性访问导致 500）
            sortable_fields = ('id', 'name', 'category', 'location', 'found_time', 'created_at', 'updated_at')
            if sort_by not in sortable_fields:
                sort_by = 'created_at'
            if sort_order == 'desc':
                items_query = items_query.order_by(getattr(FoundItem, sort_by).desc())
            else:
                items_query = items_query.order_by(getattr(FoundItem, sort_by).asc())

            # 获取总数
            total = items_query.count()

            # 应用分页
            items_query = items_query.offset((page - 1) * size).limit(size)

            # 转换为字典列表
            items_list = [item.to_dict() for item in items_query.all()]

        # 返回结果
        response = {
            'items': items_list,
            'total': total,
            'page': page,
            'size': size
        }

        return jsonify(response), 200

    except SQLAlchemyError as e:
        current_app.logger.error(f"搜索时发生数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"搜索时发生意外错误: {str(e)}")
        return jsonify({"error": "搜索失败"}), 500
