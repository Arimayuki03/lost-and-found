from . import common
from flask import jsonify, current_app, request
from flask_jwt_extended import jwt_required, get_jwt_identity, create_access_token, get_jwt


# 服务端登出接口：撤销当前 access token（jti 拉黑），并可选撤销随请求体传入的 refresh token。
# 修复：此前登出只清前端本地存储，refresh token 在 30 天内持续有效可继续换取新 access token
@common.route('/logout', methods=['POST'])
@jwt_required()  # 接受 access token；refresh token 也一并兼容，便于前端只传刷新令牌的场景
def logout():
    try:
        from app.utils.token_revocation import revoke_token, revoke_refresh_token

        # 撤销当前已验证令牌（access 或 refresh）的 jti，TTL 到令牌自然过期为止；
        # 撤销失败（Redis 异常 fail-open）仅记日志，登出响应照常返回
        revoke_token()

        # 可选撤销 refresh token：客户端随请求体传入时才处理，防止登出后 30 天内仍可刷新
        data = request.get_json(silent=True) or {}
        refresh_token = data.get('refresh_token')
        if refresh_token:
            revoke_refresh_token(refresh_token)

        current_app.logger.info(f"用户/管理员 {get_jwt_identity()} 登出成功")
        return jsonify({"message": "登出成功"}), 200
    except Exception as e:
        current_app.logger.error(f"登出时发生错误: {str(e)}")
        return jsonify({"error": "登出时发生错误"}), 500


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
