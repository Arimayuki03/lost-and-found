from app.utils.decorators import super_admin_required
from app.utils.password import hash_password
from app.utils.ratelimit import ip_rate_limit
from app.utils.account_lock import is_locked, record_failure, clear_failures, SURFACE_SUPER
from app.common.photo import detect_misbehavior_result
from . import sadmin
from flask import request, jsonify, current_app
from werkzeug.security import check_password_hash
from app.models import SuperAdmin, User, Feedback, FoundItem, LostItem, ItemMatch, ChatMessage
from flask_jwt_extended import create_access_token, create_refresh_token, get_jwt_identity
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from app import db
from app.utils.page import paginate_query


# 超级管理员登录接口
@sadmin.route('/login', methods=['POST'])
@ip_rate_limit('sadmin_login', 10, 60)
def super_admin_login():
    # 从请求中获取JSON数据
    data = request.get_json(silent=True)
    if not data:
        current_app.logger.warning("用户名和密码是必需的")
        return jsonify({"error": "用户名和密码是必需的"}), 400
    # 获取用户名和密码
    name = data.get('name')
    password = data.get('password')

    # 检查用户名和密码是否提供（类型防护：非字符串会在 Redis 锁键与哈希校验处产生 500）
    if not name or not password:
        current_app.logger.warning("用户名和密码是必需的")
        return jsonify({"error": "用户名和密码是必需的"}), 400
    if not isinstance(name, str) or len(name) > 100 \
            or not isinstance(password, str) or len(password) > 128:
        return jsonify({"error": "用户名或密码格式不正确"}), 400

    # 账号级锁定：连续失败达阈值后暂时禁止该超管账号登录
    # surface=super：与其他登录面隔离，避免超管用户名与其他面标识撞名时互相影响
    if is_locked(name, surface=SURFACE_SUPER):
        current_app.logger.warning(f"超管账号 {name} 登录已被临时锁定")
        return jsonify({"error": "失败次数过多，账号已临时锁定，请15分钟后再试"}), 429

    try:
        # 查询超级管理员
        super_admin = SuperAdmin.query.filter_by(name=name).first()
        current_app.logger.info(f"尝试登录的用户名: {name}")

        # 检查提供的名称和密码是否匹配
        if super_admin and check_password_hash(super_admin.password, password):
            # 登录成功清除失败计数
            clear_failures(name, surface=SURFACE_SUPER)
            # role claim 用于与普通用户令牌区分（两者 identity 共用数字空间），
            # super_admin_required 据此鉴权；/common/refresh 会透传该声明
            claims = {"role": "super_admin"}
            # 创建 JWT 访问令牌，确保 identity 是字符串类型
            access_token = create_access_token(identity=str(super_admin.id), fresh=True, additional_claims=claims)
            refresh_token = create_refresh_token(identity=str(super_admin.id), additional_claims=claims)  # 创建 refresh token
            current_app.logger.info(f"超级管理员 {name} 登录成功")
            return jsonify({
                "access_token": access_token,
                "refresh_token": refresh_token,
                "id": super_admin.id  # 返回超级管理员的 ID
            }), 200

        # 记录失败，达到阈值后锁定该账号（用户不存在时同样计入，见 account_lock.is_locked 策略说明）
        record_failure(name, surface=SURFACE_SUPER)
        current_app.logger.warning("凭证无效")
        return jsonify({"error": "凭证无效"}), 401
    except Exception as e:
        current_app.logger.error(f"登录过程中发生错误: {str(e)}")
        return jsonify({"error": "登录过程中发生错误"}), 500


# 添加管理员接口
@sadmin.route('/admins', methods=['POST'])
@super_admin_required
def add_admin():
    # 从请求中获取JSON数据
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "请求体不能为空"}), 400
    # 获取必要的字段
    name = data.get('name')
    password = data.get('password')
    student_id = data.get('student_id')
    email = data.get('email')
    avatar_url = data.get('avatar_url')  # 新增头像URL字段

    # 检查是否提供了所有必要的数据
    if not name or not password or not student_id or not email:
        current_app.logger.warning("所有字段都是必需的")
        return jsonify({"error": "所有字段都是必需的"}), 400

    # 输入校验：姓名/学号/密码/邮箱/头像的类型、长度与格式
    if not isinstance(name, str) or not name or len(name) > 50:
        return jsonify({"error": "姓名需为非空字符串且长度不超过50"}), 400
    if not isinstance(student_id, str) or not student_id or len(student_id) > 12:
        return jsonify({"error": "学号需为非空字符串且长度不超过12"}), 400
    if not isinstance(password, str) or not (8 <= len(password) <= 64):
        return jsonify({"error": "密码长度需为8-64位"}), 400
    if not isinstance(email, str) or len(email) > 100 or '@' not in email:
        return jsonify({"error": "邮箱需为非空字符串、长度不超过100且包含@"}), 400
    if avatar_url is not None and (not isinstance(avatar_url, str) or len(avatar_url) > 200):
        return jsonify({"error": "头像地址需为长度不超过200的字符串"}), 400

    try:

        # 检查学号是否已存在
        existing_student = User.query.filter_by(student_id=student_id).first()
        if existing_student:
            current_app.logger.warning(f"学号 {student_id} 已存在")
            return jsonify({"error": "学号已存在"}), 400

        # 检查头像是否包含不良内容
        if avatar_url:
            try:
                result = detect_misbehavior_result(avatar_url)
                if result.get('Type') != '正常':
                    current_app.logger.warning("检测到不良内容，头像无法使用")
                    return jsonify({"error": "检测到不良内容，头像无法使用"}), 400
            except ValueError as e:
                # 图片地址无效（SSRF 白名单拒绝等）属于请求问题，返回 400
                current_app.logger.warning(f"头像地址无效: {str(e)}")
                return jsonify({"error": str(e)}), 400
            except Exception as e:
                current_app.logger.error(f"不良内容检测失败: {str(e)}")
                # 统一 fail-closed，防止检测服务故障期间不良头像绕过审核
                return jsonify({"error": "内容检测服务不可用，请稍后再试"}), 503

        # 创建新管理员（密码哈希存储）
        new_admin = User(
            name=name,
            student_id=student_id,
            email=email,
            avatar_url='' if avatar_url is None else avatar_url,  # 处理null值
            is_admin=True,
            password=hash_password(password)
        )

        # 添加到数据库
        db.session.add(new_admin)
        db.session.commit()
        current_app.logger.info(f"管理员 {name} 添加成功")
        return jsonify({"message": "管理员添加成功", "id": new_admin.id}), 201
    except IntegrityError:
        db.session.rollback()
        current_app.logger.warning("添加管理员触发唯一约束冲突")
        return jsonify({"error": "邮箱或学号已存在"}), 400
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"添加管理员时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 删除用户接口
@sadmin.route('/users/<int:user_id>', methods=['DELETE'])
@super_admin_required
def delete_user(user_id):
    try:
        # 查找用户
        user = User.query.get(user_id)
        if not user:
            current_app.logger.warning(f"用户 ID {user_id} 未找到")
            return jsonify({"message": "用户未找到"}), 404

        # 不做"删除自己"比对：超管 identity 是 super_admins 表 ID，与 user 表 ID 空间独立，
        # 不存在"删除自己"场景；原比对在两表 ID 撞号时会永久误拒删除同 ID 的普通用户，故移除

        # 禁止删除管理员账号：删除后审核/管理入口失守且不可恢复（对照 admins.py 的禁删保护）
        if user.is_admin:
            current_app.logger.warning(
                f"超管 ID {get_jwt_identity()} 尝试删除管理员（用户 ID {user_id}），已拒绝")
            return jsonify({"error": "不能删除管理员账号"}), 403

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

        # 提交事务
        db.session.commit()
        current_app.logger.info(f"用户 ID {user_id} 删除成功")
        return jsonify({"message": "用户删除成功"}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"删除用户时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 修改用户信息接口，可修改管理员信息
@sadmin.route('/users/<int:user_id>', methods=['PUT'])
@super_admin_required
def update_user(user_id):
    try:
        # 从请求中获取JSON数据
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "请求体不能为空"}), 400
        # 查找用户
        user = User.query.get(user_id)
        if not user:
            current_app.logger.warning(f"用户 ID {user_id} 未找到")
            return jsonify({"error": "用户未找到"}), 404

        # 检查头像是否包含不良内容
        avatar_url = data.get('avatar_url')
        if avatar_url is not None and (not isinstance(avatar_url, str) or len(avatar_url) > 200):
            return jsonify({"error": "头像地址需为长度不超过200的字符串"}), 400
        if avatar_url and avatar_url != user.avatar_url:
            try:
                result = detect_misbehavior_result(avatar_url)
                if result.get('Type') != '正常':
                    current_app.logger.warning("检测到不良内容，头像无法使用")
                    return jsonify({"error": "检测到不良内容，头像无法使用"}), 400
            except ValueError as e:
                # 图片地址无效（SSRF 白名单拒绝等）属于请求问题，返回 400
                current_app.logger.warning(f"头像地址无效: {str(e)}")
                return jsonify({"error": str(e)}), 400
            except Exception as e:
                current_app.logger.error(f"不良内容检测失败: {str(e)}")
                # 统一 fail-closed，防止检测服务故障期间不良头像绕过审核
                return jsonify({"error": "内容检测服务不可用，请稍后再试"}), 503

        # 输入校验：类型与长度与 add_admin 保持一致，防止超长/非法类型写入触发数据库 500
        if 'name' in data:
            if not isinstance(data['name'], str) or not data['name'] or len(data['name']) > 50:
                return jsonify({"error": "姓名需为非空字符串且长度不超过50"}), 400
        if 'student_id' in data:
            if not isinstance(data['student_id'], str) or not data['student_id'] or len(data['student_id']) > 12:
                return jsonify({"error": "学号需为非空字符串且长度不超过12"}), 400
        if 'email' in data:
            if not isinstance(data['email'], str) or not data['email'] or len(data['email']) > 100 or '@' not in data['email']:
                return jsonify({"error": "邮箱需为非空字符串、长度不超过100且包含@"}), 400
        if 'is_admin' in data and not isinstance(data['is_admin'], bool):
            return jsonify({"error": "is_admin 需为布尔值"}), 400

        # 学号/邮箱唯一性校验：提前返回 400，避免落到唯一索引冲突变成 500
        if 'student_id' in data and data['student_id'] != user.student_id:
            if User.query.filter(User.student_id == data['student_id'], User.id != user.id).first():
                current_app.logger.warning(f"学号 {data['student_id']} 已被其他用户占用")
                return jsonify({"error": "学号已存在"}), 400
        if 'email' in data and data['email'] != user.email:
            if User.query.filter(User.email == data['email'], User.id != user.id).first():
                current_app.logger.warning(f"邮箱 {data['email']} 已被其他用户占用")
                return jsonify({"error": "邮箱已被绑定"}), 400

        # 更新字段（如果提供了新值）
        if 'name' in data:
            user.name = data['name']
        if 'student_id' in data:
            user.student_id = data['student_id']
        if 'email' in data:
            user.email = data['email']
        if 'is_admin' in data:
            # 防止把最后一名管理员降级：系统将没有任何管理员可用（用户/物品审核入口全部失守）
            if user.is_admin and not data['is_admin'] and User.query.filter_by(is_admin=True).count() <= 1:
                current_app.logger.warning(
                    f"超管 ID {get_jwt_identity()} 尝试降级最后一名管理员（用户 ID {user_id}），已拒绝")
                return jsonify({"error": "不能降级最后一名管理员"}), 400
            # 审计日志：管理员身份变更是高危操作，记录操作者、目标、旧值与新值
            current_app.logger.warning(
                f"超管 ID {get_jwt_identity()} 将用户 ID {user_id} 的 is_admin 由 {user.is_admin} 改为 {data['is_admin']}")
            user.is_admin = data['is_admin']
        if 'avatar_url' in data:
            user.avatar_url = '' if data['avatar_url'] is None else data['avatar_url']
        # 提交更改
        db.session.commit()
        current_app.logger.info(f"用户 ID {user_id} 信息更新成功")
        return jsonify({"message": "用户信息更新成功"}), 200
    except IntegrityError:
        db.session.rollback()
        current_app.logger.warning(f"更新用户 {user_id} 触发唯一约束冲突")
        return jsonify({"error": "学号或邮箱已被占用"}), 400
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"更新用户信息时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 查询所有用户接口，包括管理员
@sadmin.route('/users', methods=['GET'])
@super_admin_required
def get_all_users():
    try:
        # 使用增强的分页功能，支持排序和搜索
        result = paginate_query(
            User.query,
            searchable_fields=['name', 'student_id', 'email'],
            sortable_fields=['id', 'name', 'student_id']
        )

        # 将用户信息转换为字典列表
        users_list = [{
            "id": user.id,
            "name": user.name,
            "student_id": user.student_id,
            "email": user.email,
            "avatar_url": user.avatar_url,
            "is_admin": user.is_admin
        } for user in result['items']]

        # 返回分页结果
        response = {
            'items': users_list,
            'total': result['total'],
            'page': result['page'],
            'size': result['size']
        }

        current_app.logger.info("成功查询所有用户")
        return jsonify(response), 200
    except SQLAlchemyError as e:
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"查询用户时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 查询所有管理员接口
@sadmin.route('/admins', methods=['GET'])
@super_admin_required
def get_all_admins():
    try:
        # 使用增强的分页功能，支持排序
        result = paginate_query(
            User.query.filter_by(is_admin=True),
            sortable_fields=['id', 'name', 'student_id']
        )

        # 将管理员信息转换为字典列表
        admins_list = [{
            "id": admin.id,
            "name": admin.name,
            "student_id": admin.student_id,
            "email": admin.email,
            "avatar_url": admin.avatar_url,
            "is_admin": admin.is_admin
        } for admin in result['items']]

        # 返回分页结果
        response = {
            'items': admins_list,
            'total': result['total'],
            'page': result['page'],
            'size': result['size']
        }

        current_app.logger.info("成功查询所有管理员")
        return jsonify(response), 200
    except SQLAlchemyError as e:
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"查询管理员时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 获取用户统计数据接口
@sadmin.route('/users/stats', methods=['GET'])
@super_admin_required
def get_user_stats():
    try:
        # 获取总用户数
        total_users = User.query.count()

        # 获取管理员数量
        total_admins = User.query.filter_by(is_admin=True).count()

        # 返回统计结果
        response = {
            'totalUsers': total_users,
            'totalAdmins': total_admins
        }

        current_app.logger.info("成功获取用户统计数据")
        return jsonify(response), 200
    except SQLAlchemyError as e:
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"获取用户统计数据时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500
