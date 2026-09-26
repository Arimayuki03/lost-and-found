import secrets

from flask import request, jsonify, current_app
from flask_jwt_extended import create_refresh_token,  create_access_token
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from app import db
from app.models import User, LostItem, FoundItem, Feedback, ItemMatch, ChatMessage
from app.utils.decorators import admin_required
from app.utils.password import hash_password, verify_user_password, verify_dummy_password
from app.utils.ratelimit import ip_rate_limit
from app.utils.account_lock import is_locked, record_failure, clear_failures, SURFACE_ADMIN
from app.utils.token_revocation import mark_user_tokens_revoked
from app.utils.page import escape_like
from . import admin
from sqlalchemy import or_, func


# 管理员登录接口
@admin.route('/login', methods=['POST'])
@ip_rate_limit('admin_login', 10, 60)
def admin_login():
    # 从请求中获取JSON数据
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "需要提供学生ID和密码"}), 400
    student_id = data.get('student_id')
    password = data.get('password')

    # 检查是否提供了学生ID和密码
    if not student_id or not password:
        return jsonify({"error": "需要提供学生ID和密码"}), 400
    # 类型/长度防护：非字符串会在 Redis 锁键与哈希校验处产生 500
    if not isinstance(student_id, str) or len(student_id) > 64 \
            or not isinstance(password, str) or len(password) > 128:
        return jsonify({"error": "学号或密码格式不正确"}), 400

    # 账号级锁定：连续失败达阈值后暂时禁止该学号登录
    # surface=admin：与用户端隔离——管理员在 users 表中也是用户（学号相同），
    # 不隔离则用户端打满的失败次数会把管理员锁在管理端之外（跨登录面 DoS）
    if is_locked(student_id, surface=SURFACE_ADMIN):
        current_app.logger.warning(f"管理员学号 {student_id} 登录已被临时锁定")
        return jsonify({"error": "失败次数过多，账号已临时锁定，请15分钟后再试"}), 429

    try:
        # 查询管理员用户
        admin_user = User.query.filter_by(student_id=student_id, is_admin=True).first()

        if admin_user is None:
            # 时序对齐：用户不存在时也执行一次同等代价的哈希校验，
            # 防止通过响应时间差枚举学号（account_lock 只统一了状态码与计数，未统一耗时）
            verify_dummy_password(password)

        # 检查提供的学生ID和密码是否匹配
        if admin_user and verify_user_password(admin_user, password):
            # 若数据库中为历史明文密码，verify_user_password 已将其升级为哈希，此处统一提交
            db.session.commit()
            # 登录成功清除失败计数
            clear_failures(student_id, surface=SURFACE_ADMIN)
            # 创建 JWT 访问令牌，确保 identity 是字符串类型
            access_token = create_access_token(identity=str(admin_user.id), fresh=True)
            refresh_token = create_refresh_token(identity=str(admin_user.id))  # 创建 refresh token
            return jsonify({
                "access_token": access_token,
                "refresh_token": refresh_token,
                "id": admin_user.id  # 返回管理员的 ID
            }), 200

        # 记录失败，达到阈值后锁定该学号（用户不存在时同样计入，见 account_lock.is_locked 策略说明）
        record_failure(student_id, surface=SURFACE_ADMIN)
        return jsonify({"error": "凭证无效"}), 401
    except SQLAlchemyError as e:
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"管理员登录时发生错误: {str(e)}")
        return jsonify({"error": "管理员登录时发生错误"}), 500


# 删除用户接口
@admin.route('/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    try:
        # 查找用户
        user = User.query.get(user_id)
        if not user:
            return jsonify({"message": "用户未找到"}), 404

        # 检查用户是否为管理员
        if user.is_admin:
            return jsonify({"error": "无法删除管理员用户"}), 403

        # 使用事务确保所有操作要么全部成功，要么全部失败
        with db.session.begin_nested():
            # 获取用户的所有失物和招领物品ID
            found_item_ids = [item.id for item in FoundItem.query.filter_by(user_id=user_id).all()]
            lost_item_ids = [item.id for item in LostItem.query.filter_by(user_id=user_id).all()]

            # 删除与这些物品相关的匹配记录
            if found_item_ids:
                ItemMatch.query.filter(ItemMatch.found_item_id.in_(found_item_ids)).delete(
                    synchronize_session=False)
            if lost_item_ids:
                ItemMatch.query.filter(ItemMatch.lost_item_id.in_(lost_item_ids)).delete(synchronize_session=False)

            # 删除用户的反馈
            Feedback.query.filter_by(user_id=user_id).delete(synchronize_session=False)

            # 删除用户的聊天消息
            ChatMessage.query.filter_by(sender_id=user_id).delete(synchronize_session=False)
            ChatMessage.query.filter_by(receiver_id=user_id).delete(synchronize_session=False)

            # 删除用户的失物和招领物品
            FoundItem.query.filter_by(user_id=user_id).delete(synchronize_session=False)
            LostItem.query.filter_by(user_id=user_id).delete(synchronize_session=False)

            # 最后删除用户
            db.session.delete(user)

        db.session.commit()
        current_app.logger.info(f"用户 {user_id} 已删除")
        return jsonify({"message": "用户删除成功"}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"删除用户时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 修改用户信息接口
@admin.route('/users/<int:user_id>', methods=['PUT'])
@admin_required
def update_user(user_id):
    try:
        # 从请求中获取JSON数据
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "请求体不能为空"}), 400
        # 查找用户
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "用户未找到"}), 404

        # 检查是否为管理员
        if user.is_admin:
            return jsonify({"error": "无法修改管理员用户"}), 403

        # 类型/长度校验（与超管端 update_user 同标准，防止非法类型穿透或撞库 500）
        if 'name' in data:
            if not isinstance(data['name'], str) or not data['name'] or len(data['name']) > 50:
                return jsonify({"error": "姓名需为非空字符串且长度不超过50"}), 400
        if 'student_id' in data:
            if not isinstance(data['student_id'], str) or not data['student_id'] or len(data['student_id']) > 12:
                return jsonify({"error": "学号需为非空字符串且长度不超过12"}), 400
            # 学号唯一索引冲突提前返回 400（否则 IntegrityError 落入 500）
            if data['student_id'] != user.student_id:
                if User.query.filter(User.student_id == data['student_id'], User.id != user_id).first():
                    return jsonify({"error": "学号已被占用"}), 400

        # 更新字段（如果提供了新值）
        if 'name' in data:
            user.name = data['name']
        if 'student_id' in data:
            user.student_id = data['student_id']

        # 提交更改
        db.session.commit()
        current_app.logger.info(f"用户 {user_id} 信息已更新")
        return jsonify({"message": "用户信息更新成功"}), 200
    except IntegrityError:
        db.session.rollback()
        current_app.logger.warning(f"更新用户 {user_id} 触发唯一约束冲突")
        return jsonify({"error": "学号已被占用"}), 400
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"更新用户信息时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 查询所有普通用户接口
@admin.route('/users', methods=['GET'])
@admin_required
def get_users():
    try:
        # 获取分页和筛选参数
        page = request.args.get('page', 1, type=int)
        size = request.args.get('size', 10, type=int)
        query = request.args.get('query', '')
        sort_by = request.args.get('sort_by', 'id')
        sort_order = request.args.get('sort_order', 'desc')

        # 构建查询
        users_query = User.query.filter_by(is_admin=False)

        # 处理搜索查询
        if query:
            users_query = users_query.filter(
                or_(
                    User.name.ilike(f"%{escape_like(query)}%"),
                    User.student_id.ilike(f"%{escape_like(query)}%"),
                    User.email.ilike(f"%{escape_like(query)}%")
                )
            )

        # 处理排序（白名单限制，防止按密码等敏感列排序）
        sortable_fields = ('id', 'name', 'student_id', 'email', 'created_at')
        if sort_by in sortable_fields:
            column = getattr(User, sort_by)
            if sort_order.lower() == 'desc':
                users_query = users_query.order_by(column.desc())
            else:
                users_query = users_query.order_by(column)
        else:
            users_query = users_query.order_by(User.id.desc())

        # 分页（限制每页数量上限；error_out=False：页码越界返回空列表而非内部 abort 404，
        # 避免 NotFound 被末尾 except Exception 吞成 500，与 paginate_query 行为一致）
        paginated = users_query.paginate(page=max(page, 1), per_page=min(max(size, 1), 100), error_out=False)

        # 一次聚合查询统计每用户的失物/拾物数量，避免逐用户 COUNT 的 N+1 查询
        user_ids = [u.id for u in paginated.items]
        if user_ids:
            lost_counts = dict(
                db.session.query(LostItem.user_id, func.count(LostItem.id))
                .filter(LostItem.user_id.in_(user_ids))
                .group_by(LostItem.user_id).all()
            )
            found_counts = dict(
                db.session.query(FoundItem.user_id, func.count(FoundItem.id))
                .filter(FoundItem.user_id.in_(user_ids))
                .group_by(FoundItem.user_id).all()
            )
        else:
            lost_counts, found_counts = {}, {}

        # 转换为前端期望的格式
        users_list = []
        for user in paginated.items:
            users_list.append({
                'id': user.id,
                'name': user.name,
                'student_id': user.student_id,
                'email': user.email,
                'avatar_url': user.avatar_url,
                'is_admin': user.is_admin,
                'lostItemsCount': lost_counts.get(user.id, 0),
                'foundItemsCount': found_counts.get(user.id, 0)
            })

        return jsonify({
            'data': users_list,
            'total': paginated.total,
            'page': page,
            'size': size,
            'pages': paginated.pages
        }), 200
    except Exception as e:
        current_app.logger.error(f"查询用户时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 获取用户详情
@admin.route('/users/<int:user_id>', methods=['GET'])
@admin_required
def get_user_detail(user_id):
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({"error": "用户未找到"}), 404

        # 确保只能查看普通用户
        if user.is_admin:
            return jsonify({"error": "无法查看管理员用户详情"}), 403

        user_data = {
            'id': user.id,
            'name': user.name,
            'student_id': user.student_id,
            'email': user.email,
            'avatar_url': user.avatar_url,
            'lostItemsCount': LostItem.query.filter_by(user_id=user.id).count(),
            'foundItemsCount': FoundItem.query.filter_by(user_id=user.id).count()
        }

        return jsonify(user_data), 200
    except Exception as e:
        current_app.logger.error(f"获取用户详情时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 重置用户密码
@admin.route('/users/<int:user_id>/reset-password', methods=['POST'])
@admin_required
def reset_user_password(user_id):
    try:
        user = User.query.get(user_id)
        if not user:
            return jsonify({"message": "用户未找到"}), 404

        # 确保只能重置普通用户密码
        if user.is_admin:
            return jsonify({"error": "无法重置管理员用户密码"}), 403

        # 随机密码替代固定 123456，响应中返回由管理员当面告知用户
        default_password = secrets.token_urlsafe(9)
        user.password = hash_password(default_password)
        # 先写撤销标记再提交：Redis 失败时本次密码变更一并回滚，
        # 避免密码已改但新密码未返回、旧令牌仍有效导致账号处于不一致状态
        if not mark_user_tokens_revoked(user_id):
            db.session.rollback()
            current_app.logger.error(f"重置用户 {user_id} 密码失败：撤销标记写入失败")
            return jsonify({"error": "密码重置失败，请稍后再试"}), 500
        db.session.commit()

        current_app.logger.info(f"已重置用户 {user_id} 的密码")
        return jsonify({"message": "密码重置成功", "new_password": default_password}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"重置用户密码时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500
