from datetime import datetime

from . import user
from flask import request, jsonify, current_app
from flask_jwt_extended import get_jwt_identity
from sqlalchemy.exc import SQLAlchemyError
from app import db
from app.models import LostItem, ItemMatch
from app.utils.decorators import user_required
from app.utils.page import paginate_query, validate_str


# 用户添加失物信息接口
@user.route('/lost-items', methods=['POST'])
@user_required  # 需要用户登录
def create_lost_item():
    try:
        # 从请求中获取JSON数据（silent=True，非法JSON时返回None而不是抛异常）
        data = request.get_json(silent=True)
        # 获取当前用户ID
        current_user = get_jwt_identity()

        # 验证必要字段是否存在（location 库列为 NOT NULL，缺失必须 400 而非落到数据库 500）
        if (not data or 'category' not in data or 'name' not in data or 'description' not in data
                or 'lost_time' not in data or 'contact' not in data or 'location' not in data):
            current_app.logger.warning("缺少必要字段")
            return jsonify({"error": "缺少必要字段"}), 400

        # 校验字符串字段的类型与长度（非字符串类型直接拒绝，防止穿透写入数据库）
        location = data['location']
        try:
            validate_str(data['category'], 50, 'category')
            validate_str(data['name'], 100, 'name')
            validate_str(data['contact'], 50, 'contact')
            validate_str(location, 200, 'location')
            if data.get('description') is not None:
                validate_str(data['description'], 5000, 'description', allow_empty=True)
            if data.get('image_url') is not None:
                validate_str(data['image_url'], 200, 'image_url', allow_empty=True)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

        # 校验时间格式是否可解析
        try:
            lost_time = datetime.fromisoformat(data['lost_time'])
        except (TypeError, ValueError):
            return jsonify({"error": "lost_time 时间格式无效"}), 400

        # 获取可选字段（is_completed 严格限定布尔：字符串 "false" 经 bool() 会变 True）
        image_url = data.get('image_url')
        if 'is_completed' in data and not isinstance(data['is_completed'], bool):
            return jsonify({"error": "is_completed 需为布尔值"}), 400
        is_completed = data.get('is_completed', False)

        # 创建失物记录
        lost_item = LostItem(
            category=data['category'], name=data['name'], description=data['description'],
            lost_time=lost_time, location=location, contact=data['contact'],
            image_url=image_url, user_id=current_user, is_completed=is_completed
        )
        db.session.add(lost_item)
        db.session.commit()
        current_app.logger.info(f"用户 {current_user} 创建失物信息成功")
        return jsonify({"message": "失物信息创建成功"}), 201
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"发生意外错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 用户修改失物信息接口
@user.route('/lost-items/<int:item_id>', methods=['PUT'])
@user_required  # 需要用户登录
def update_lost_item(item_id):
    try:
        # 从请求中获取JSON数据（silent=True，非法JSON时返回None而不是抛异常）
        data = request.get_json(silent=True)
        # 请求体为空时直接拒绝，避免后续 len(data) 报错
        if not data:
            return jsonify({"error": "请求体不能为空"}), 400
        # 获取当前用户ID
        current_user = get_jwt_identity()

        # 校验待更新字段的类型与长度（非字符串类型直接拒绝），时间格式不合法直接拒绝
        try:
            if 'category' in data:
                validate_str(data['category'], 50, 'category')
            if 'name' in data:
                validate_str(data['name'], 100, 'name')
            if 'location' in data:
                validate_str(data['location'], 200, 'location')
            if 'contact' in data:
                validate_str(data['contact'], 50, 'contact')
            if 'description' in data and data['description'] is not None:
                validate_str(data['description'], 5000, 'description', allow_empty=True)
            if 'image_url' in data and data['image_url'] is not None:
                validate_str(data['image_url'], 200, 'image_url', allow_empty=True)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        if 'lost_time' in data:
            try:
                data['lost_time'] = datetime.fromisoformat(data['lost_time'])
            except (TypeError, ValueError):
                return jsonify({"error": "lost_time 时间格式无效"}), 400
        # 完成状态直接参与审核流转判断，必须为布尔（"false" 等字符串会误判为真）
        if 'is_completed' in data and not isinstance(data['is_completed'], bool):
            return jsonify({"error": "is_completed 需为布尔值"}), 400

        # 查找失物记录
        lost_item = LostItem.query.filter_by(id=item_id, user_id=current_user).first()
        if not lost_item:
            current_app.logger.warning(f"失物信息 ID {item_id} 未找到或无权限编辑")
            return jsonify({"error": "失物信息未找到或无权限编辑"}), 404

        # 记录原始状态，用于判断是否是重新发布
        original_is_completed = lost_item.is_completed
        original_is_under_review = lost_item.is_under_review

        # 检查是否只是更新完成状态
        is_status_update_only = len(data) == 1 and 'is_completed' in data
        # 仅记录请求摘要，不落整个 body（可能含联系方式等 PII，与 log_sanitize 脱敏意图一致）
        current_app.logger.info(
            f"用户 {current_user} 提交了失物更新请求（字段数 {len(data)}），是否仅更新状态: {is_status_update_only}")

        # 如果物品正在审核中，且请求仅是更改完成状态，则拒绝请求
        if is_status_update_only and original_is_under_review:
            current_app.logger.warning(f"物品 ID {item_id} 正在审核中，不能更改完成状态")
            return jsonify({"error": "物品正在审核中，不能更改完成状态"}), 403

        # 更新字段（如果提供了新值）
        if 'category' in data:
            lost_item.category = data['category']
        if 'name' in data:
            lost_item.name = data['name']
        if 'description' in data:
            lost_item.description = data['description']
        if 'lost_time' in data:
            lost_item.lost_time = data['lost_time']
        if 'location' in data:
            lost_item.location = data['location']
        if 'contact' in data:
            lost_item.contact = data['contact']
        if 'image_url' in data:
            lost_item.image_url = data['image_url']
        if 'is_completed' in data and not original_is_under_review:
            lost_item.is_completed = data['is_completed']
            current_app.logger.info(f"更新完成状态: 从 {original_is_completed} 到 {data['is_completed']}")

            # 如果是将状态从"已找到"改为"寻找中"（重新发布），需要重新审核
            if original_is_completed and not data['is_completed']:
                lost_item.is_under_review = True
                current_app.logger.info(f"物品 ID {item_id} 重新发布，设置为需要审核")
            # 如果是标记为已找到，则不需要审核
            elif not original_is_completed and data['is_completed']:
                # 保持当前审核状态不变
                current_app.logger.info(f"物品 ID {item_id} 标记为已找到，保持审核状态不变")

        # 如果不是仅更新完成状态，而是修改了物品信息，则需要重新审核
        if not is_status_update_only:
            lost_item.is_under_review = True  # 设置为需要审核
            current_app.logger.info(f"物品 ID {item_id} 信息被修改，设置为需要审核")

        # 提交更改
        db.session.commit()

        # 记录更新后的状态
        current_app.logger.info(
            f"更新后状态: is_completed={lost_item.is_completed}, is_under_review={lost_item.is_under_review}")

        current_app.logger.info(f"用户 {current_user} 更新失物信息 ID {item_id} 成功")
        return jsonify({"message": "失物信息更新成功", "is_under_review": lost_item.is_under_review}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"更新失物信息时发生意外错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 用户删除失物信息接口
@user.route('/lost-items/<int:item_id>', methods=['DELETE'])
@user_required  # 需要用户登录
def delete_lost_item(item_id):
    try:
        # 获取当前用户ID
        current_user_id = get_jwt_identity()
        current_app.logger.info(f"用户 {current_user_id} 尝试删除失物信息 ID {item_id}")

        # 查找失物记录
        lost_item = LostItem.query.get(item_id)
        if not lost_item:
            current_app.logger.warning(f"失物信息 ID {item_id} 未找到")
            return jsonify({"error": "失物信息未找到"}), 404

        # 记录失物信息的所有者ID
        current_app.logger.info(f"失物信息 ID {item_id} 的所有者ID为 {lost_item.user_id}")

        # 验证用户权限
        if str(lost_item.user_id) != str(current_user_id):
            current_app.logger.warning(
                f"用户 {current_user_id} 无权限删除失物信息 ID {item_id}，所有者ID为 {lost_item.user_id}")
            return jsonify({"error": "无权限删除此信息"}), 403

        # 检查物品是否处于审核状态
        if lost_item.is_under_review:
            current_app.logger.warning(f"物品 ID {item_id} 正在审核中，不能删除")
            return jsonify({"error": "物品正在审核中，不能删除"}), 403

        ItemMatch.query.filter_by(lost_item_id=item_id).delete(synchronize_session=False)

        # 删除记录
        db.session.delete(lost_item)
        db.session.commit()
        current_app.logger.info(f"用户 {current_user_id} 删除失物信息 ID {item_id} 成功")
        return jsonify({"message": "失物信息删除成功"}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"删除失物信息时发生意外错误: {str(e)}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({"error": "发生意外错误"}), 500


# 查询当前用户的所有失物信息接口
@user.route('/lost-items', methods=['GET'])
@user_required  # 需要用户登录
def get_my_lost_items():
    try:
        # 获取当前用户ID
        current_user = get_jwt_identity()

        # 查询当前用户发布的所有失物记录，应用分页
        query = LostItem.query.filter_by(user_id=current_user)
        # 排序白名单与 /admin/lost-items 保持一致（字段均真实存在于 LostItem）；
        # 未命中时 paginate_query 回退 id 排序，保证 offset/limit 分页稳定
        paginated_result = paginate_query(
            query,
            sortable_fields=['id', 'name', 'category', 'location',
                             'is_completed', 'is_under_review', 'lost_time',
                             'created_at', 'updated_at'],
        )

        if not paginated_result or not paginated_result['items']:
            return jsonify({"message": "未找到失物信息", "items": []}), 200

        current_app.logger.info(f"用户 {current_user} 查询失物信息成功")

        # 将记录转换为字典列表
        lost_items_list = [item.to_dict() for item in paginated_result['items']]

        # 构建响应
        response = {
            "items": lost_items_list,
            "total": paginated_result['total'],
            "page": paginated_result['page'],
            "size": paginated_result['size']
        }

        return jsonify(response), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"查询失物信息时发生意外错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 用户查询自己的单个失物详情接口（包括正在审核的记录）
@user.route('/lost-items/<int:item_id>/detail', methods=['GET'])
@user_required  # 需要用户登录
def get_my_lost_item_detail(item_id):
    try:
        # 获取当前用户ID
        current_user = get_jwt_identity()

        # 查询指定ID的失物记录（必须是当前用户发布的）
        lost_item = LostItem.query.filter_by(id=item_id, user_id=current_user).first()

        # 如果找不到记录，尝试获取公共接口的数据
        if not lost_item:
            current_app.logger.info(
                f"用户 {current_user} 查询的失物信息 ID {item_id} 不是该用户发布的，尝试获取公共数据")

            # 查询公共接口的数据（必须是已审核的）
            public_item = LostItem.query.filter_by(id=item_id, is_under_review=False).first()

            if not public_item:
                current_app.logger.warning(f"失物信息 ID {item_id} 未找到或正在审核中")
                return jsonify({"error": "失物信息未找到或正在审核中"}), 404

            # 返回公共数据
            current_app.logger.info(f"用户 {current_user} 查询公共失物详情 ID {item_id} 成功")
            return jsonify(public_item.to_dict()), 200

        # 返回用户自己的失物详情（包括审核中的）
        current_app.logger.info(f"用户 {current_user} 查询自己的失物详情 ID {item_id} 成功")
        return jsonify(lost_item.to_dict()), 200
    except SQLAlchemyError as e:
        # 数据库错误处理
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        # 其他异常处理
        current_app.logger.error(f"查询失物详情时发生意外错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


