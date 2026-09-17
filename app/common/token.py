from . import common
from flask import jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity, create_access_token, get_jwt


# 刷新Token接口
@common.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)  # 需要使用刷新Token进行身份验证
def refresh():
    try:
        # 获取当前用户身份
        current_user = get_jwt_identity()

        # role claim 需透传到新 access token，否则超管刷新后权限丢失
        jwt_data = get_jwt()
        role = jwt_data.get('role')

        # 创建新的访问Token，设置为非新鲜的
        access_token = create_access_token(
            identity=current_user,
            fresh=False,
            additional_claims={"role": role} if role else None
        )

        # 返回新的访问Token
        return jsonify(access_token=access_token), 200
    except Exception as e:
        current_app.logger.error(f"刷新Token时发生错误: {str(e)}")
        import traceback
        current_app.logger.error(traceback.format_exc())
        return jsonify({"error": "刷新Token时发生错误"}), 500
