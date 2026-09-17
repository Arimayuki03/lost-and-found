from . import common
from flask import request, jsonify
from app.models import User
from app.utils.ratelimit import ip_rate_limit


# 检查邮箱是否已注册接口
# 该接口本身即可探测账号存在性（审计 B14 因注册/找回密码流程需要保留），
# 但必须限制匿名高频批量枚举：按 IP 30 次/分（正常表单校验每分钟最多触发几次）
@common.route('/emails', methods=['POST'])
@ip_rate_limit('check_email', 30, 60)
def check_email():
    # 从请求中获取JSON数据（silent=True：无 body/非法 JSON 返回 400 而非 415/500）
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "请求体不能为空"}), 400
    # 获取邮箱地址
    email = data.get('email')
    if not isinstance(email, str) or len(email) > 100:
        return jsonify({"error": "邮箱格式不正确"}), 400
    # 查询数据库中是否存在该邮箱的用户
    user = User.query.filter_by(email=email).first()
    # 返回查询结果，存在则返回True，否则返回False
    return jsonify({"exists": bool(user)})


# 检查学号是否已注册接口
@common.route('/student-ids', methods=['POST'])
@ip_rate_limit('check_student_id', 30, 60)
def check_student_id():
    # 从请求中获取JSON数据
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "请求体不能为空"}), 400
    # 获取学号
    student_id = data.get('student_id')
    if not isinstance(student_id, str) or len(student_id) > 12:
        return jsonify({"error": "学号格式不正确"}), 400
    # 查询数据库中是否存在该学号的用户
    user = User.query.filter_by(student_id=student_id).first()
    # 返回查询结果，存在则返回True，否则返回False
    return jsonify({"exists": bool(user)})
