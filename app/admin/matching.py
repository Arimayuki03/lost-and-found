from flask import current_app, jsonify
from flask_jwt_extended import get_jwt_identity
from app.models import User
from app.utils.decorators import admin_required
from app.utils.matching_service import match_items
from app.utils.ratelimit import ip_rate_limit
from . import admin
import threading


# 手动触发匹配过程接口
@admin.route('/run', methods=['POST'])
# 匹配任务是重操作（全表扫描 + 发邮件），即便有互斥锁兜底也按 IP 限流防滥用；
# 认证装饰器在最外层（与 photo.py 的 jwt_required + ip_rate_limit 顺序一致），未认证请求不消耗配额
@admin_required
@ip_rate_limit('admin_run_matching', 10, 60)
def run_matching():
    try:
        # 获取当前用户ID
        user_id = get_jwt_identity()

        # 检查用户是否是管理员
        user = User.query.get(user_id)
        if not user or not user.is_admin:
            current_app.logger.warning(f"用户 ID {user_id} 尝试手动触发匹配过程但无权限")
            return jsonify({"error": "只有管理员可以手动触发匹配过程"}), 403

        # 在创建线程前获取应用实例
        app = current_app._get_current_object()

        # 在后台线程中运行匹配过程
        def run_matching_task(app, user_id):
            with app.app_context():
                try:
                    # 运行匹配过程
                    match_count = match_items()
                    app.logger.info(f"管理员 ID {user_id} 触发匹配过程，找到 {match_count} 个匹配项")
                except Exception as e:
                    app.logger.error(f"后台匹配过程执行出错: {str(e)}")

        # 启动后台线程
        matching_thread = threading.Thread(target=run_matching_task, args=(app, user_id))
        matching_thread.daemon = True
        matching_thread.start()

        return jsonify({
            "success": True,
            "message": "匹配过程已在后台启动，请稍后查看结果"
        }), 200

    except Exception as e:
        current_app.logger.error(f"运行匹配过程时出错: {str(e)}")
        return jsonify({"error": "运行匹配过程时出错"}), 500
