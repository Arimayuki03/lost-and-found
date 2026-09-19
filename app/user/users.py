from flask import request, jsonify, current_app
from flask_jwt_extended import create_access_token, get_jwt_identity, create_refresh_token
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from app import db
from app.models import User
from app.utils.code import verify_email_logic
from app.utils.password import hash_password, verify_user_password
from app.utils.ratelimit import ip_rate_limit
from app.utils.account_lock import is_locked, record_failure, clear_failures, SURFACE_USER
from app.utils.token_revocation import mark_user_tokens_revoked
from app.utils.decorators import user_required
from app.common.photo import detect_misbehavior_result
from . import user


# 用户注册接口
@user.route('/register', methods=['POST'])
@ip_rate_limit('user_register', 10, 60)
def register():
    try:
        # 从请求中获取JSON数据
        data = request.get_json(silent=True)

        # 验证必要字段是否存在
        if (not data or 'name' not in data or 'student_id' not in data or 'password' not in data
                or 'email' not in data or 'code' not in data):
            current_app.logger.warning("缺少必要字段")
            return jsonify({"error": "缺少必要字段"}), 400

        # 输入校验：姓名/学号/密码/邮箱/头像的类型、长度与格式（非字符串类型直接拒绝）
        if not isinstance(data['name'], str) or not data['name'] or len(data['name']) > 50:
            return jsonify({"error": "姓名需为非空字符串且长度不超过50"}), 400
        if not isinstance(data['student_id'], str) or not data['student_id'] or len(data['student_id']) > 12:
            return jsonify({"error": "学号需为非空字符串且长度不超过12"}), 400
        if not isinstance(data['password'], str) or not (8 <= len(data['password']) <= 64):
            return jsonify({"error": "密码长度需为8-64位"}), 400
        if (not isinstance(data['email'], str) or not data['email']
                or len(data['email']) > 100 or '@' not in data['email']):
            return jsonify({"error": "邮箱需为非空字符串、长度不超过100且包含@"}), 400
        if data.get('avatar_url') is not None and not isinstance(data['avatar_url'], str):
            return jsonify({"error": "头像地址需为字符串"}), 400
        if data.get('avatar_url') and len(data['avatar_url']) > 200:
            return jsonify({"error": "头像地址长度不能超过200"}), 400

        # 验证码需为字符串（此前非字符串如 int 会在 strip() 处抛异常落入 500）
        if not isinstance(data['code'], str):
            return jsonify({"error": "验证码需为字符串"}), 400

        # 验证邮箱验证码
        email = data['email']
        code = data['code'].strip()
        success, message = verify_email_logic(email, code)
        if not success:
            current_app.logger.warning(f"邮箱验证码验证失败: {message}")
            return jsonify({"error": message}), 400

        # 检查邮箱是否已被绑定
        if User.query.filter_by(email=data['email']).first():
            current_app.logger.warning("邮箱已被绑定")
            return jsonify({"error": "邮箱已被绑定"}), 400

        # 处理头像上传
        avatar_url = data.get('avatar_url')
        if avatar_url:
            try:
                result = detect_misbehavior_result(avatar_url)
            except ValueError as e:
                # 图片地址无效（SSRF 白名单拒绝等）属于请求问题，返回 400
                current_app.logger.warning(f"注册头像地址无效: {str(e)}")
                return jsonify({"error": str(e)}), 400
            except Exception as e:
                current_app.logger.error(f"检查不良内容失败: {str(e)}")
                return jsonify({"error": "检查不良内容失败"}), 500
            if result.get('Type') != '正常':
                current_app.logger.warning("检测到不良内容，头像无法使用")
                return jsonify({"error": "检测到不良内容，头像无法使用"}), 400

        # 创建新用户（密码哈希存储；数据库 avatar_url 为 NOT NULL，未上传头像时以空串兜底）
        user = User(name=data['name'], student_id=data['student_id'],
                    password=hash_password(data['password']), email=data['email'],
                    avatar_url='' if avatar_url is None else avatar_url)
        db.session.add(user)
        db.session.commit()
        current_app.logger.info(f"用户 {data['name']} 注册成功")

        return jsonify({"message": "用户注册成功"}), 201
    except IntegrityError:
        db.session.rollback()
        current_app.logger.warning("注册触发唯一约束冲突")
        return jsonify({"error": "邮箱或学号已被注册"}), 400
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"发生意外错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 用户登录接口
@user.route('/login', methods=['POST'])
# 阈值放宽：校园网大量用户共享 NAT 出口 IP，过紧会误伤正常登录
@ip_rate_limit('user_login', 30, 60)
def login():
    try:
        # 从请求中获取JSON数据
        data = request.get_json(silent=True)

        # 验证必要字段是否存在
        if not data or 'student_id' not in data or 'password' not in data:
            current_app.logger.warning("缺少必要字段")
            return jsonify({"error": "缺少必要字段"}), 400

        # 类型/长度防护：非字符串会在 Redis 键与 filter_by 处产生 500
        student_id = data['student_id']
        password = data['password']
        if not isinstance(student_id, str) or len(student_id) > 64 \
                or not isinstance(password, str) or len(password) > 128:
            return jsonify({"error": "学号或密码格式不正确"}), 400

        # 账号级锁定：连续失败达阈值后暂时禁止该学号登录（IP 限流之外的第二道防线）
        # surface=user：与管理端/超管端隔离，防止用户端失败计数把同名管理员的登录锁死
        if is_locked(student_id, surface=SURFACE_USER):
            current_app.logger.warning(f"学号 {student_id} 登录已被临时锁定")
            return jsonify({"error": "失败次数过多，账号已临时锁定，请15分钟后再试"}), 429

        # 查找用户
        user = User.query.filter_by(student_id=student_id).first()
        if user and verify_user_password(user, data['password']):
            # 若数据库中为历史明文密码，verify_user_password 已将其升级为哈希，此处统一提交
            db.session.commit()
            # 登录成功清除失败计数
            clear_failures(student_id, surface=SURFACE_USER)
            # 创建访问和刷新令牌
            access_token = create_access_token(identity=str(user.id), fresh=True)
            refresh_token = create_refresh_token(identity=str(user.id))
            current_app.logger.info(f"用户 {student_id} 登录成功")

            # 返回用户信息
            user_info = {
                "id": user.id,
                "name": user.name,
                "student_id": user.student_id,
                "email": user.email,
                "avatar_url": user.avatar_url,
                "created_at": user.created_at.isoformat() if user.created_at else None
            }

            return jsonify(access_token=access_token, refresh_token=refresh_token, user=user_info), 200

        current_app.logger.warning("凭证无效")
        # 记录失败，达到阈值后锁定该学号（用户不存在时同样计入，见 account_lock.is_locked 策略说明）
        record_failure(student_id, surface=SURFACE_USER)
        return jsonify({"message": "凭证无效"}), 401
    except Exception as e:
        current_app.logger.error(f"登录时发生意外错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 用户修改个人信息接口
@user.route('/profile', methods=['PUT'])
@user_required  # 需要用户登录
def update_profile():
    try:
        # 标记本次请求是否修改了密码，用于提交后撤销旧令牌
        password_changed = False
        # 从请求中获取JSON数据
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "请求体不能为空"}), 400
        # 获取当前用户ID
        current_user_id = get_jwt_identity()

        # 查找用户
        user = User.query.get(current_user_id)
        if not user:
            current_app.logger.warning(f"用户 ID {current_user_id} 未找到")
            return jsonify({"error": "用户未找到"}), 404

        # 更新字段（如果提供了新值）
        if 'name' in data:
            if not isinstance(data['name'], str) or not data['name'] or len(data['name']) > 50:
                return jsonify({"error": "姓名需为非空字符串且长度不超过50"}), 400
            user.name = data['name']
        if 'password' in data:
            new_password = data['password']
            if not isinstance(new_password, str) or not (8 <= len(new_password) <= 64):
                return jsonify({"error": "新密码长度需为8-64位"}), 400
            old_password = data.get('old_password')
            if not old_password or not verify_user_password(user, old_password):
                current_app.logger.warning(f"用户 ID {current_user_id} 修改密码时旧密码校验失败")
                return jsonify({"error": "旧密码不正确"}), 400
            user.password = hash_password(new_password)
            password_changed = True

        if password_changed:
            # 先写撤销标记再提交：Redis 失败时本次密码变更一并回滚，
            # 避免"密码已改但旧令牌未撤销"的不一致状态
            if not mark_user_tokens_revoked(user.id):
                db.session.rollback()
                current_app.logger.error(f"用户 ID {current_user_id} 密码变更失败：撤销标记写入失败")
                return jsonify({"error": "密码修改失败，请稍后再试"}), 500

        db.session.commit()
        current_app.logger.info(f"用户 ID {current_user_id} 信息更新成功")
        return jsonify({"message": "个人信息更新成功"}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"更新个人信息时发生意外错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 获取用户信息接口
@user.route('/profile', methods=['GET'])
@user_required  # 需要用户登录
def get_profile():
    try:
        # 获取当前用户ID
        current_user_id = get_jwt_identity()

        # 查找用户
        user = User.query.get(current_user_id)
        if not user:
            current_app.logger.warning(f"用户 ID {current_user_id} 未找到")
            return jsonify({"error": "用户未找到"}), 404

        # 返回用户信息
        user_info = {
            "id": user.id,
            "name": user.name,
            "student_id": user.student_id,
            "email": user.email,
            "avatar_url": user.avatar_url,
            "created_at": user.created_at.isoformat() if user.created_at else None
        }

        return jsonify({"user": user_info}), 200
    except Exception as e:
        current_app.logger.error(f"获取用户信息时发生意外错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 根据ID获取用户信息接口
@user.route('/profile/<int:user_id>', methods=['GET'])
def get_user_by_id(user_id):
    try:
        # 查找用户
        user = User.query.get(user_id)
        if not user:
            current_app.logger.warning(f"用户 ID {user_id} 未找到")
            return jsonify({"error": "用户未找到"}), 404

        # 返回用户信息（只返回公开信息）
        user_info = {
            "id": user.id,
            "name": user.name,
            "avatar_url": user.avatar_url,
            "created_at": user.created_at.isoformat() if user.created_at else None
        }

        return jsonify(user_info), 200
    except Exception as e:
        current_app.logger.error(f"获取用户信息时发生意外错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 用户修改头像接口
@user.route('/avatar', methods=['PUT'])
# 腾讯云内容检测按次计费，不加限流会被刷出真金白银的账单（与注册同策略）
@ip_rate_limit('user_avatar', 10, 60)
@user_required  # 需要用户登录
def update_avatar():
    try:
        # 获取当前用户ID
        current_user_id = get_jwt_identity()

        # 查找用户
        user = User.query.get(current_user_id)
        if not user:
            current_app.logger.warning(f"用户 ID {current_user_id} 未找到")
            return jsonify({"error": "用户未找到"}), 404

        # 从请求中获取JSON数据
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "请求体不能为空"}), 400
        avatar_url = data.get('avatar_url')
        if not avatar_url:
            current_app.logger.warning("头像URL是必需的")
            return jsonify({"error": "头像URL是必需的"}), 400
        if not isinstance(avatar_url, str) or len(avatar_url) > 200:
            return jsonify({"error": "头像地址需为长度不超过200的字符串"}), 400

        # URL 未变跳过检测：内容检测按次计费，重复提交同一地址无需再次付费
        # （对照超管端 update_user 的防重入写法）
        if avatar_url != user.avatar_url:
            # 调用不良内容检测
            try:
                result = detect_misbehavior_result(avatar_url)
            except ValueError as e:
                # 图片地址无效（SSRF 白名单拒绝等）属于请求问题，返回 400
                current_app.logger.warning(f"头像地址无效: {str(e)}")
                return jsonify({"error": str(e)}), 400
            except Exception as e:
                current_app.logger.error(f"检查不良内容失败: {str(e)}")
                return jsonify({"error": "检查不良内容失败"}), 500

            if result.get('Type') != '正常':
                current_app.logger.warning("检测到不良内容，头像无法使用")
                return jsonify({"error": "检测到不良内容，头像无法使用"}), 400

        # 更新用户头像
        user.avatar_url = avatar_url
        db.session.commit()
        current_app.logger.info(f"用户 ID {current_user_id} 头像更新成功")
        return jsonify({"message": "头像更新成功", "avatar_url": avatar_url}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"更新头像时发生意外错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 用户修改邮箱接口
@user.route('/email', methods=['POST'])
@user_required  # 需要用户登录
def change_email():
    try:
        # 从请求中获取JSON数据
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "请求体不能为空"}), 400
        # 获取当前用户ID
        current_user_id = get_jwt_identity()

        # 获取新邮箱和验证码
        new_email = data.get('new_email')
        code = data.get('code')

        if not new_email or not code:
            current_app.logger.warning("新邮箱和验证码是必需的")
            return jsonify({"error": "新邮箱和验证码是必需的"}), 400
        if not isinstance(new_email, str) or len(new_email) > 100 or '@' not in new_email:
            return jsonify({"error": "邮箱需为长度不超过100且包含@的字符串"}), 400

        # 验证邮箱验证码
        success, message = verify_email_logic(new_email, code)
        if not success:
            current_app.logger.warning(f"邮箱验证码验证失败: {message}")
            return jsonify({"error": message}), 400

        # 检查邮箱是否已被绑定
        if User.query.filter_by(email=new_email).first():
            current_app.logger.warning("邮箱已被绑定")
            return jsonify({"error": "邮箱已被绑定"}), 400

        # 更新用户邮箱
        user = User.query.get(current_user_id)
        if not user:
            current_app.logger.warning(f"用户 ID {current_user_id} 未找到")
            return jsonify({"error": "用户未找到"}), 404

        user.email = new_email
        db.session.commit()
        current_app.logger.info(f"用户 ID {current_user_id} 邮箱更新成功")
        return jsonify({"message": "邮箱修改成功"}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"修改邮箱时发生意外错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 重置密码接口
@user.route('/password', methods=['POST'])
# 验证码爆破之外的第三道闸：按 IP 限流（与登录/注册同策略，窗口内阈值放宽到 10 次/分）
@ip_rate_limit('user_reset_password', 10, 60)
def reset_password():
    try:
        # 从请求中获取JSON数据
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "请求体不能为空"}), 400

        # 获取邮箱、新密码和验证码
        email = data.get('email')
        new_password = data.get('new_password')
        code = data.get('code')

        if not email or not new_password or not code:
            current_app.logger.warning("邮箱、新密码和验证码是必需的")
            return jsonify({"error": "邮箱、新密码和验证码是必需的"}), 400

        # 新密码长度校验
        if not isinstance(new_password, str) or not (8 <= len(new_password) <= 64):
            return jsonify({"error": "新密码长度需为8-64位"}), 400
        # 邮箱/验证码类型防护：非字符串会在 filter_by / strip 处产生 500
        if not isinstance(email, str) or len(email) > 100 or '@' not in email:
            return jsonify({"error": "邮箱格式不正确"}), 400
        if not isinstance(code, str):
            return jsonify({"error": "验证码需为字符串"}), 400

        # 验证邮箱验证码
        success, message = verify_email_logic(email, code)
        if not success:
            current_app.logger.warning(f"邮箱验证码验证失败: {message}")
            return jsonify({"error": message}), 400

        # 更新用户密码
        user = User.query.filter_by(email=email).first()
        if not user:
            current_app.logger.warning(f"用户邮箱 {email} 未找到")
            return jsonify({"error": "用户未找到"}), 404

        user.password = hash_password(new_password)
        # 先写撤销标记再提交：Redis 失败时本次密码变更一并回滚，防止验证码被重放后旧令牌仍有效
        if not mark_user_tokens_revoked(user.id):
            db.session.rollback()
            current_app.logger.error(f"用户邮箱 {email} 密码重置失败：撤销标记写入失败")
            return jsonify({"error": "密码重置失败，请稍后再试"}), 500
        db.session.commit()
        current_app.logger.info(f"用户邮箱 {email} 密码重置成功")
        return jsonify({"message": "密码重置成功"}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"重置密码时发生意外错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500
