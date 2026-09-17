from flask import request
from sqlalchemy.orm import Query
from sqlalchemy import desc, asc, or_
from flask import current_app


def escape_like(s: str) -> str:
    """转义 LIKE 通配符（% _ \\），防止用户输入被当作模糊匹配模式。

    仅用于 MySQL（默认转义符为反斜杠）；拼接方式：like(f"%{escape_like(q)}%")
    """
    if s is None:
        return s
    return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def validate_str(value, max_length, field_name, allow_empty=False):
    """校验字段为字符串且长度不超限，非法直接抛 ValueError（由调用方映射 400）。

    此前的 `isinstance(x, str) and len(x) > 50` 写法会让 int/list 等非字符串类型
    穿透校验直接写入数据库（SQLAlchemy 会隐式 str() 或直接报 500）。
    """
    if not isinstance(value, str):
        raise ValueError(f"{field_name}需为字符串")
    if not allow_empty and not value:
        raise ValueError(f"{field_name}不能为空")
    if len(value) > max_length:
        raise ValueError(f"{field_name}长度不能超过{max_length}")
    return value


def _order_by_id(query: Query, desc_order: bool) -> Query:
    """按模型主键 id 排序的分页稳定性兜底。

    从 query.column_descriptions[0]['entity'] 取真实 id 列（而非字符串 'id'，
    字符串形式在带 join/别名的查询上会解析到歧义列）；
    getattr 失败或取不到实体时保持原查询无序，不抛错。
    """
    try:
        model_class = query.column_descriptions[0]['entity']
        id_column = getattr(model_class, 'id', None)
        if id_column is not None:
            if desc_order:
                return query.order_by(desc(id_column))
            return query.order_by(asc(id_column))
    except Exception as e:
        # 记录错误但不中断执行
        current_app.logger.error(f"回退 id 排序时发生错误: {str(e)}")
    return query


def paginate_query(query: Query, default_page: int = 1, default_size: int = 10, max_per_page: int = 100,
                   searchable_fields=None, sortable_fields=None,
                   sort_by=None, sort_order=None):
    """
    通用分页功能，用于处理查询的分页、排序和搜索。

    :param query: SQLAlchemy 查询对象
    :param default_page: 默认页码
    :param default_size: 默认每页记录数
    :param max_per_page: 每页最大数量
    :param searchable_fields: 可搜索的字段列表，例如 ['name', 'student_id']；
        提供时对请求参数 query 做跨字段 OR 模糊匹配（此前该参数被静默忽略，
        导致 /sadmin/users 等接口的服务端搜索实际不生效）
    :param sortable_fields: 可排序的字段列表，例如 ['id', 'name', 'student_id']
    :param sort_by: 排序字段
    :param sort_order: 排序顺序
    :return: 分页后的查询结果和总数
    """
    # 获取分页参数（限制页码下限与每页数量上限，防止负 offset 报错和一次拉取全表）
    page = request.args.get('page', default_page, type=int)
    per_page = request.args.get('size', default_size, type=int)
    page = max(page, 1)
    per_page = min(max(per_page, 1), max_per_page)

    # 应用搜索（转义 LIKE 通配符，防止用户输入 %/_ 扰动匹配）
    search_query = (request.args.get('query') or '').strip()
    if search_query and searchable_fields:
        try:
            model_class = query.column_descriptions[0]['entity']
            conditions = []
            for field_name in searchable_fields:
                column = getattr(model_class, field_name, None)
                if column is not None:
                    conditions.append(column.ilike(f"%{escape_like(search_query)}%"))
            if conditions:
                query = query.filter(or_(*conditions))
        except Exception as e:
            # 搜索失败不中断列表返回，与排序降级策略一致
            current_app.logger.error(f"搜索时发生错误: {str(e)}")

    # 如果没有提供排序参数，从请求中获取
    if sort_by is None:
        sort_by = request.args.get('sort_by', 'id')
    if sort_order is None:
        sort_order = request.args.get('sort_order', 'asc')

    # 应用排序。
    # 白名单未命中回退策略：只要传了 sortable_fields 但 sort_by 不在其中，或调用方根本
    # 未传 sortable_fields，都回退为按模型主键 id 排序（sort_order 仍生效），
    # 保证 offset/limit 分页稳定——否则无 ORDER BY 的分页在翻页时会出现重复行/丢行；
    # 且白名单机制不能被"传非白名单值就跳过排序"绕过。
    if sortable_fields and sort_by in sortable_fields:
        try:
            # 获取模型类
            model_class = query.column_descriptions[0]['entity']
            # 获取排序字段
            sort_column = getattr(model_class, sort_by, None)

            if sort_column is not None:
                if sort_order.lower() == 'desc':
                    query = query.order_by(desc(sort_column))
                else:
                    query = query.order_by(asc(sort_column))
            else:
                # 白名单命中但模型上无该属性（防御性），回退 id 排序
                query = _order_by_id(query, sort_order.lower() == 'desc')
        except Exception as e:
            # 记录错误但不中断执行，回退按ID排序
            current_app.logger.error(f"排序时发生错误: {str(e)}")
            query = _order_by_id(query, sort_order.lower() == 'desc')
    else:
        # 白名单未命中（或调用方未传白名单）→ 回退 id 排序，保证分页稳定性
        query = _order_by_id(query, sort_order.lower() == 'desc')

    # 计算总数
    total = query.count()

    # 应用分页
    items = query.offset((page - 1) * per_page).limit(per_page).all()

    # 返回分页结果和总数
    return {
        'items': items,
        'total': total,
        'page': page,
        'size': per_page
    }
