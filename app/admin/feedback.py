from flask import jsonify, current_app, request
from sqlalchemy.exc import SQLAlchemyError
from app import db
from app.models import Feedback
from app.utils.decorators import admin_required
from app.utils.page import paginate_query, escape_like
from . import admin


# 查询所有反馈信息接口
# 说明：搜索直接构建在查询上（paginate_query 的 searchable_fields 亦支持，
# 这里保留显式写法以维持 contact 字段扩展的直观性），不再需要历史版本中
# 针对 paginate_query 返回形状的层层防御——该函数恒返回 {items,total,page,size} 字典
@admin.route('/feedbacks', methods=['GET'])
@admin_required
def get_all_feedbacks():
    try:
        # 获取查询参数
        query = request.args.get('query', '')
        sort_by = request.args.get('sort_by', 'id')
        sort_order = request.args.get('sort_order', 'desc')

        # 构建查询
        feedback_query = Feedback.query

        # 应用搜索条件
        if query:
            feedback_query = feedback_query.filter(Feedback.content.ilike(f"%{escape_like(query)}%"))

        # 应用分页和排序
        result = paginate_query(
            feedback_query,
            sortable_fields=['id', 'user_id', 'timestamp'],
            sort_by=sort_by,
            sort_order=sort_order
        )

        return jsonify({
            'items': [feedback.to_dict() for feedback in result['items']],
            'total': result['total'],
            'page': result['page'],
            'size': result['size']
        }), 200
    except SQLAlchemyError as e:
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"查询反馈信息时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500


# 删除指定反馈信息接口
@admin.route('/feedbacks/<int:feedback_id>', methods=['DELETE'])
@admin_required
def delete_feedback(feedback_id):
    try:
        # 查找反馈记录
        feedback = Feedback.query.get(feedback_id)
        if not feedback:
            current_app.logger.warning(f"反馈 ID {feedback_id} 未找到")
            return jsonify({"error": "反馈未找到"}), 404

        # 删除反馈记录
        db.session.delete(feedback)
        db.session.commit()

        current_app.logger.info(f"反馈 ID {feedback_id} 删除成功")
        return jsonify({"message": "反馈删除成功"}), 200
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"数据库错误: {str(e)}")
        return jsonify({"error": "数据库错误"}), 500
    except Exception as e:
        current_app.logger.error(f"删除反馈时发生错误: {str(e)}")
        return jsonify({"error": "发生意外错误"}), 500
