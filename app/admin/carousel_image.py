from flask import request, jsonify, current_app
from sqlalchemy.exc import SQLAlchemyError
from app import db
from app.models import CarouselImage
from app.utils.decorators import admin_required
from app.utils.page import escape_like
from datetime import datetime
from . import admin


# 查询所有轮播图接口 - 手动实现排序和分页
@admin.route('/carousel-images', methods=['GET'])
@admin_required
def get_all_carousel_images():
    try:
        # 获取分页和排序参数
        page = request.args.get('page', 1, type=int)
        size = request.args.get('size', 10, type=int)
        page = max(page, 1)
        size = min(max(size, 1), 100)
        sort_by = request.args.get('sort_by', 'created_at')
        sort_order = request.args.get('sort_order', 'desc')
        query = request.args.get('query', '')
        
        # 创建基础查询
        carousel_query = CarouselImage.query
        
        # 应用搜索过滤
        if query:
            carousel_query = carousel_query.filter(CarouselImage.description.ilike(f"%{escape_like(query)}%"))
        
        # 验证排序字段是否有效
        valid_sort_fields = ['id', 'image_url', 'description', 'order', 'created_at', 'updated_at']
        if sort_by not in valid_sort_fields:
            sort_by = 'created_at'  # 默认排序字段
        
        # 获取排序字段属性
        sort_attr = getattr(CarouselImage, sort_by)
        
        # 应用排序
        if sort_order.lower() == 'desc':
            carousel_query = carousel_query.order_by(sort_attr.desc())
        else:
            carousel_query = carousel_query.order_by(sort_attr)
        
        # 记录日志
        current_app.logger.info(f"轮播图排序: 字段={sort_by}, 顺序={sort_order}")
        
        # 手动分页
        total = carousel_query.count()
        carousel_images = carousel_query.offset((page - 1) * size).limit(size).all()
        
        # 转换为字典列表
        carousel_items = [image.to_dict() for image in carousel_images]
        
        # 构建响应
        response = {
            'items': carousel_items,
            'total': total,
            'page': page,
            'size': size
        }
        
        current_app.logger.info(f"成功查询轮播图列表，共 {len(carousel_items)} 条记录")
        return jsonify(response), 200
        
    except SQLAlchemyError as e:
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"查询轮播图时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 添加轮播图接口
@admin.route('/carousel-images', methods=['POST'])
@admin_required
def add_carousel_image():
    try:
        # 从请求中获取JSON数据
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "请求体不能为空"}), 400
        image_url = data.get('image_url')
        description = data.get('description', '')  # 默认描述为空字符串
        order = data.get('order', 0)  # 默认顺序为0

        # 检查是否提供了图片URL
        if not image_url:
            current_app.logger.warning("缺少图片URL")
            return jsonify({"error": "需要提供图片URL"}), 400

        # 类型与长度校验（image_url 库列为 String(200)，description 为 String(255)）
        if not isinstance(image_url, str) or len(image_url) > 200:
            return jsonify({"error": "图片地址需为长度不超过200的字符串"}), 400
        if description is not None and (not isinstance(description, str) or len(description) > 255):
            return jsonify({"error": "描述需为长度不超过255的字符串"}), 400
        if not isinstance(order, int) or isinstance(order, bool):
            return jsonify({"error": "排序值需为整数"}), 400

        # 创建新的轮播图对象
        carousel_image = CarouselImage(
            image_url=image_url, 
            description=description, 
            order=order,
            created_at=datetime.now()
        )
        db.session.add(carousel_image)
        db.session.commit()

        current_app.logger.info(f"轮播图 '{image_url}' 添加成功")
        return jsonify({"message": "轮播图添加成功", "id": carousel_image.id}), 201
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"添加轮播图时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 修改轮播图接口
@admin.route('/carousel-images/<int:image_id>', methods=['PUT'])
@admin_required
def update_carousel_image(image_id):
    try:
        # 从请求中获取JSON数据
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "请求体不能为空"}), 400
        # 查找轮播图
        image = CarouselImage.query.get(image_id)
        if not image:
            current_app.logger.warning(f"轮播图 ID {image_id} 未找到")
            return jsonify({"error": "轮播图未找到"}), 404

        # 更新轮播图信息（如果提供了新值；类型与长度校验，非字符串/非法类型直接拒绝）
        if 'image_url' in data:
            new_url = data['image_url']
            if not isinstance(new_url, str) or not new_url or len(new_url) > 200:
                return jsonify({"error": "图片地址需为非空字符串且长度不超过200"}), 400
            image.image_url = new_url
        if 'description' in data and data['description'] is not None:
            if not isinstance(data['description'], str) or len(data['description']) > 255:
                return jsonify({"error": "描述需为长度不超过255的字符串"}), 400
            image.description = data['description']
        if 'order' in data:
            if not isinstance(data['order'], int) or isinstance(data['order'], bool):
                return jsonify({"error": "排序值需为整数"}), 400
            image.order = data['order']
        image.updated_at = datetime.now()  # 记录更新时间

        db.session.commit()
        current_app.logger.info(f"轮播图 ID {image_id} 更新成功")
        return jsonify({"message": "轮播图更新成功"}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"更新轮播图时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 删除轮播图接口
@admin.route('/carousel-images/<int:image_id>', methods=['DELETE'])
@admin_required
def delete_carousel_image(image_id):
    try:
        # 查找轮播图
        image = CarouselImage.query.get(image_id)
        if not image:
            current_app.logger.warning(f"轮播图 ID {image_id} 未找到")
            return jsonify({"error": "轮播图未找到"}), 404

        # 删除轮播图
        db.session.delete(image)
        db.session.commit()
        current_app.logger.info(f"轮播图 ID {image_id} 删除成功")
        return jsonify({"message": "轮播图删除成功"}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"删除轮播图时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500
