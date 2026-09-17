from . import common
from flask import request, jsonify, current_app
from app.models import CarouselImage
from sqlalchemy.exc import SQLAlchemyError
from app.utils.page import paginate_query


# 获取所有轮播图接口
@common.route('/carousel-images', methods=['GET'])
def get_carousel_images():
    try:
        # 获取查询参数
        page = request.args.get('page', 1, type=int)
        size = request.args.get('size', 10, type=int)
        sort_by = request.args.get('sort_by', 'order')  # 默认按顺序排序
        sort_order = request.args.get('sort_order', 'asc')  # 默认升序

        # 构建查询
        carousel_query = CarouselImage.query

        # 执行查询并分页
        result = paginate_query(
            carousel_query,
            default_page=page,
            default_size=size,
            sortable_fields=['id', 'order', 'created_at', 'updated_at'],
            sort_by=sort_by,
            sort_order=sort_order
        )

        # 将轮播图记录转换为字典列表
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
        current_app.logger.error(f"获取轮播图时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 获取单个轮播图接口
@common.route('/carousel-images/<int:image_id>', methods=['GET'])
def get_carousel_image(image_id):
    try:
        # 查询指定ID的轮播图
        carousel_image = CarouselImage.query.get(image_id)

        # 检查是否存在
        if not carousel_image:
            return jsonify({"error": "轮播图不存在"}), 404

        # 返回轮播图信息
        return jsonify(carousel_image.to_dict()), 200
    except SQLAlchemyError as e:
        # 数据库错误处理
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        # 其他异常处理
        current_app.logger.error(f"获取轮播图详情时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500