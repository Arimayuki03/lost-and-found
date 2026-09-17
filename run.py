import os

from dotenv import load_dotenv

# python run.py 启动时 Flask 不会自动加载 .env，而 config 在导入时即读取环境变量，
# 因此必须在导入 app 之前完成加载（flask 命令行方式由 Flask 自动加载，重复调用无副作用）
load_dotenv()

from app import create_app
from app import socketio

app = create_app()

if __name__ == '__main__':
    # debug 默认关闭：Werkzeug 交互式调试器暴露在 0.0.0.0 上等同于远程代码执行入口，
    # 仅在本机临时调试时设置 FLASK_DEBUG=1
    socketio.run(app, host='0.0.0.0', port=5000,
                 debug=os.getenv('FLASK_DEBUG') == '1',
                 allow_unsafe_werkzeug=True, use_reloader=False)
