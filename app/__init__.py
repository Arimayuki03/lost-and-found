from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from flask_socketio import SocketIO
from flask_cors import CORS


from config.config import Config
from app.utils.redis_client import redis_client  # 导入 Redis 客户端
from app.utils.log_sanitize import SqlParamScrubber
import os
import logging
from logging.handlers import RotatingFileHandler
from werkzeug.security import generate_password_hash

db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()
socketio = SocketIO(cors_allowed_origins="*", async_mode='threading')


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # CORS 白名单：逗号分隔的来源列表；默认 '*' 保持开发环境可用，生产必须配置为实际前端域名
    cors_origins_raw = os.getenv('CORS_ORIGINS', '*').strip()
    cors_origins = '*' if cors_origins_raw in ('', '*') else [o.strip() for o in cors_origins_raw.split(',') if o.strip()]

    # 配置日志
    if not app.debug:
        # 检查并创建日志目录
        if not os.path.exists('logs'):
            os.makedirs('logs')

        # 创建日志处理器（10MB 轮转）
        file_handler = RotatingFileHandler('logs/app.log', maxBytes=10 * 1024 * 1024, backupCount=10)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
        ))
        file_handler.setLevel(logging.INFO)
        file_handler.addFilter(SqlParamScrubber())
        app.logger.addHandler(file_handler)

        app.logger.setLevel(logging.INFO)
        app.logger.addFilter(SqlParamScrubber())  # 兜底：stderr 默认处理器同样不落敏感参数
        app.logger.info('Flask应用启动')

    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    socketio.init_app(app, cors_allowed_origins=cors_origins, async_mode='threading')
    CORS(app, origins=cors_origins)

    @jwt.token_in_blocklist_loader
    def check_if_token_revoked(jwt_header, jwt_payload):
        # 登出撤销 + 密码变更撤销的统一实现抽至 token_revocation.is_token_revoked，
        # 供 HTTP blocklist 回调与 Socket.IO 事件认证（不经 @jwt_required）共用
        from app.utils.token_revocation import is_token_revoked
        return is_token_revoked(jwt_payload)

    from app.user import user
    from app.admin import admin
    from app.sadmin import sadmin
    from app.common import common
    app.register_blueprint(user, url_prefix='/user')
    app.register_blueprint(admin, url_prefix='/admin')
    app.register_blueprint(sadmin, url_prefix='/sadmin')
    app.register_blueprint(common, url_prefix='/common')

    # 初始化调度器
    with app.app_context():
        from app.utils.scheduler import init_scheduler
        init_scheduler(app)
        create_super_admin()

    return app


def create_super_admin():
    from app.models import SuperAdmin

    super_admin_name = os.getenv('SUPER_ADMIN_NAME')
    super_admin_password = os.getenv('SUPER_ADMIN_PASSWORD')

    # 环境变量缺失时跳过创建，避免以 None 建号（name 为 NULL 时唯一索引不生效，二次启动会重复插入崩溃）
    if not super_admin_name or not super_admin_password:
        print("未配置 SUPER_ADMIN_NAME / SUPER_ADMIN_PASSWORD，跳过超级管理员初始化")
        return

    # 检查是否已经存在超级管理员
    existing_super_admin = SuperAdmin.query.filter_by(name=super_admin_name).first()
    if existing_super_admin is None:
        # 创建新的超级管理员
        new_super_admin = SuperAdmin(
            name=super_admin_name,
            password=generate_password_hash(super_admin_password)
        )
        db.session.add(new_super_admin)
        db.session.commit()
        print(f"超级管理员 '{super_admin_name}' 创建成功")
    else:
        print(f"超级管理员'{super_admin_name}' 已存在")
