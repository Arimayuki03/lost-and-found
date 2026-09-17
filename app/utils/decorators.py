from functools import wraps
from flask import jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity, get_jwt
from app.models import User, SuperAdmin


# 管理员权限装饰器
def admin_required(fn):
    @wraps(fn)
    @jwt_required()  # 需要用户登录
    def decorated(*args, **kwargs):
        # 超级管理员令牌的 identity 是 super_admins 表的 ID，与 user 表共用数字空间，
        # 必须先按 role claim 拒绝，否则会冒充同 ID 的普通用户
        if get_jwt().get('role') == 'super_admin':
            return jsonify({"error": "权限被拒绝"}), 403

        # 获取当前用户ID
        current_user_id = get_jwt_identity()
        # 查找用户
        user = User.query.get(current_user_id)

        # 检查用户是否存在
        if user is None:
            return jsonify({"error": "用户未找到"}), 404

        # 检查是否为管理员
        if user.is_admin:
            return fn(*args, **kwargs)  # 管理员可以访问

        return jsonify({"error": "权限被拒绝"}), 403

    return decorated


# 超级管理员权限装饰器
def super_admin_required(fn):
    @wraps(fn)
    @jwt_required()  # 需要用户登录
    def decorated(*args, **kwargs):
        # 仅接受登录时签发且带 role=super_admin 声明的令牌。
        # 不能只按 identity 查 super_admins 表：普通用户令牌的 identity 是 user 表 ID，
        # 两个表自增 ID 重叠时（超管首行和首个注册用户都是 1）会被冒名通过
        if get_jwt().get('role') != 'super_admin':
            return jsonify({"error": "权限被拒绝"}), 403

        # 获取当前用户ID
        current_user_id = get_jwt_identity()
        # 查找超级管理员
        user = SuperAdmin.query.get(current_user_id)

        # 检查用户是否存在
        if user is None:
            return jsonify({"error": "用户未找到"}), 404

        return fn(*args, **kwargs)  # 超级管理员可以访问

    return decorated
