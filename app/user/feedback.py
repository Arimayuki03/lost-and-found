from . import user
from flask import request, jsonify, current_app
from flask_jwt_extended import get_jwt_identity
from sqlalchemy.exc import SQLAlchemyError
from app import db
from app.models import Feedback
from app.utils.page import paginate_query
from app.utils.decorators import user_required


# 用户提交反馈接口
@user.route('/feedback', methods=['POST'])
@user_required  # 需要用户登录
def submit_feedback():
    try:
        # 从请求中获取JSON数据（silent=True：无 JSON 体/Content-Type 错误时返回 None，走下方 400 而非 500）
        data = request.get_json(silent=True)
        # 获取当前用户ID
        current_user_id = get_jwt_identity()

        # 验证必要字段是否存在
        if not data or 'content' not in data:
            current_app.logger.warning("反馈内容是必需的")
            return jsonify({"error": "反馈内容是必需的"}), 400

        # 反馈内容需为非空字符串且长度受限（Text 列无库级长度约束，防灌水/滥用）
        content = data['content']
        if not isinstance(content, str) or not content.strip():
            return jsonify({"error": "反馈内容需为非空字符串"}), 400
        if len(content) > 2000:
            return jsonify({"error": "反馈内容长度不能超过2000"}), 400

        # 检查是否是注销申请
        is_delete_account_request = False
        if data.get('type') == 'delete_account' or data.get('content', '').startswith('申请注销账号'):
            is_delete_account_request = True
            current_app.logger.warning(f"用户 {current_user_id} 提交了注销账号申请")

        # 创建反馈记录
        feedback = Feedback(user_id=current_user_id, content=content)
        db.session.add(feedback)
        db.session.commit()

        if is_delete_account_request:
            current_app.logger.info(f"用户 {current_user_id} 提交注销账号申请成功")
            # 这里可以添加额外的处理逻辑，如发送邮件通知管理员等
            return jsonify({"message": "注销账号申请提交成功，管理员将在3-5个工作日内处理"}), 201
        else:
            current_app.logger.info(f"用户 {current_user_id} 提交反馈成功")
            return jsonify({"message": "反馈提交成功"}), 201
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"提交反馈时发生意外错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 用户查询自己的反馈记录接口
@user.route('/feedback', methods=['GET'])
@user_required  # 需要用户登录
def get_my_feedback():
    try:
        # 获取当前用户ID
        current_user_id = get_jwt_identity()

        # 查询当前用户的所有反馈记录，应用分页，并按时间戳降序排序
        result = paginate_query(
            Feedback.query.filter_by(user_id=current_user_id).order_by(Feedback.timestamp.desc()),
            sortable_fields=['timestamp', 'id'],
            sort_by='timestamp',
            sort_order='desc'
        )
        current_app.logger.info(f"用户 {current_user_id} 查询反馈记录成功")

        # 从结果中获取反馈记录列表
        feedbacks = result.get('items', [])

        # 将反馈记录转换为字典列表
        feedbacks_list = [feedback.to_dict() for feedback in feedbacks]

        # 构建响应数据
        response_data = {
            'feedbacks': feedbacks_list,
            'total': result.get('total', 0),
            'page': result.get('page', 1),
            'size': result.get('size', 10)
        }

        # 返回反馈记录列表
        return jsonify(response_data), 200
    except SQLAlchemyError as e:
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"查询反馈记录时发生意外错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500
