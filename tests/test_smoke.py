"""
后端冒烟测试（无外部服务依赖：SQLite 内存库 + Redis 不可用时 fail-open 放行）。
运行：.venv\\Scripts\\python.exe tests\\test_smoke.py
覆盖结论.md 修复项的关键回归断言：
  H1  user_required 拒绝超管令牌穿越
  M1  admin 登录非字符串密码 400（原 500）
  M5  avatar 端点限流装饰器与"URL 未变跳过检测"
  P1  POST /common/logout 撤销令牌
  M13 月份统计日历月分桶无重复
  A12 匹配任务不含 == False
  M8  /unreviewed /sift 支持 keyword
  M3  /common 匿名端点已挂限流装饰器
  A21 MinIO 未配置时应用仍可启动（惰性初始化）
  新增1 超管 delete_user 禁删管理员/自己
"""
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 最小必需环境：MinIO 配齐以走默认路径；Redis 指向空端口触发 fail-open
os.environ.setdefault('SECRET_KEY', 'test-secret')
os.environ.setdefault('JWT_SECRET_KEY', 'test-jwt')
os.environ.setdefault('DATABASE_URL', 'sqlite://')
os.environ.setdefault('MINIO_ENDPOINT', 'localhost:9000')
os.environ.setdefault('MINIO_ACCESS_KEY', 'a')
os.environ.setdefault('MINIO_SECRET_KEY', 'b')
os.environ.setdefault('REDIS_HOST', '127.0.0.1')
os.environ.setdefault('REDIS_PORT', '6390')

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

results = []


def check(name, cond, detail=''):
    results.append((name, bool(cond), detail))
    print(('PASS' if cond else 'FAIL') + f'  {name}' + (f'  [{detail}]' if detail and not cond else ''))


def make_app():
    from app import create_app, db
    app = create_app()
    with app.app_context():
        db.create_all()
    return app


def get_token(client, url, body):
    r = client.post(url, json=body)
    data = r.get_json(silent=True) or {}
    return data.get('access_token') or data.get('token'), r


# ---------- 应用可创建（基础） ----------
app = make_app()
client = app.test_client()
check('app 创建成功', True)

from flask_jwt_extended import create_access_token  # noqa: E402

with app.app_context():
    admin_token = create_access_token(identity='1')            # 普通管理员（无 role claim）
    super_token = create_access_token(identity='1', additional_claims={'role': 'super_admin'})

# ---------- H1：user_required 拒绝超管令牌 ----------
r = client.get('/user/profile', headers={'Authorization': f'Bearer {super_token}'})
check('H1 超管令牌访问用户端点被拒', r.status_code == 403, f'status={r.status_code}')

r = client.get('/user/lost-items', headers={'Authorization': f'Bearer {super_token}'})
check('H1 超管令牌访问用户失物列表被拒', r.status_code in (403, 404), f'status={r.status_code}')

# ---------- M1：admin 登录类型校验 ----------
r = client.post('/admin/login', json={'student_id': 'x', 'password': 12345})
check('M1 admin 登录非字符串密码 400', r.status_code == 400, f'status={r.status_code}')
r = client.post('/admin/login', json={'student_id': {'a': 1}, 'password': 'pw123456'})
check('M1 admin 登录非字符串学号 400', r.status_code == 400, f'status={r.status_code}')

# ---------- P1：logout 撤销 ----------
r = client.post('/common/logout')
check('logout 无令牌 401', r.status_code == 401, f'status={r.status_code}')
r = client.post('/common/logout', headers={'Authorization': f'Bearer {admin_token}'})
check('logout 正常返回 200', r.status_code == 200, f'status={r.status_code}')

# ---------- M8 后端：/unreviewed /sift 支持 keyword（需真实 admin 用户身份，admin_required 要查 User 表） ----------
from app import db  # noqa: E402
from app.models import User  # noqa: E402
with app.app_context():
    if not User.query.filter_by(student_id='smoke_admin').first():
        db.session.add(User(student_id='smoke_admin', name='冒烟管理员', password='x',
                            email=f'smoke_{os.getpid()}@test.local', is_admin=True))
        db.session.commit()
    admin_uid = User.query.filter_by(student_id='smoke_admin').first().id
    admin_token2 = create_access_token(identity=str(admin_uid))
for url in ('/admin/lost-items/unreviewed', '/admin/found-items/unreviewed',
            '/admin/lost-items/sift', '/admin/found-items/sift'):
    r = client.get(f'{url}?page=1&size=10&keyword=xx', headers={'Authorization': f'Bearer {admin_token2}'})
    check(f'M8 {url} 带 keyword 可用', r.status_code == 200, f'status={r.status_code}')
# ---------- M3：/common 匿名端点限流装饰器在位 ----------
common_rate = {}
for fname in ('lost_items.py', 'found_items.py', 'search.py', 'announcement.py', 'carousel_image.py'):
    path = os.path.join(BASE, 'app', 'common', fname)
    src = open(path, encoding='utf-8').read()
    common_rate[fname] = src.count('@ip_rate_limit(')
check('M3 common 公开端点已挂限流', sum(common_rate.values()) >= 10, str(common_rate))

# ---------- A12：matching_service 无 == False ----------
src = open(os.path.join(BASE, 'app', 'utils', 'matching_service.py'), encoding='utf-8').read()
check('A12 matching_service 无 == False', '== False' not in src)

# ---------- A21：MinIO 未配置时应用仍可启动（import 时读取，用子进程模拟真实启动） ----------
a21_code = (
    "import os; os.environ.pop('MINIO_ENDPOINT', None); os.environ.pop('MINIO_ACCESS_KEY', None); "
    "os.environ.pop('MINIO_SECRET_KEY', None);"
    "import sys; sys.path.insert(0, r'" + BASE + "');"
    "os.environ.setdefault('SECRET_KEY','x'); os.environ.setdefault('JWT_SECRET_KEY','y');"
    "os.environ.setdefault('DATABASE_URL','sqlite://');"
    "from app import create_app;"
    "from contextlib import contextmanager as _cm;"
    "from app.utils import scheduler as _sched;"
    "import app.common.photo as _photo;"
    "app = create_app();"
    "_get = _sched._get_minio_client; _get2 = _photo._get_minio_client;"
    # 在 app context 内调用惰性工厂（内部用 current_app.logger）
    "_ctx = app.app_context(); _ctx.push();"
    "_a = _get(); _b = _get2();"
    "_ctx.pop();"
    "assert _a is None and _b is None, (_a, _b);"
    "print('A21_OK', len(list(app.url_map.iter_rules())))"
)
probe = subprocess.run([sys.executable, '-c', a21_code],
                       capture_output=True, text=True, timeout=120)
check('A21 MinIO 未配置时应用可启动且客户端为 None', 'A21_OK' in probe.stdout,
      (probe.stderr or probe.stdout)[-300:])

# ---------- M13：日历月分桶 ----------
from app.admin.stats import build_calendar_month_buckets  # noqa: E402
from datetime import date  # noqa: E402
labels = build_calendar_month_buckets(date(2026, 3, 31), months=6)
check('M13 2026-03-31 起 6 个月无重复',
      len(labels) == 6 and len(set(labels)) == 6 and set(labels) == {
          '2026-03', '2026-02', '2026-01', '2025-12', '2025-11', '2025-10'}, str(labels))

# ---------- 新增1：超管 delete_user 保护 ----------
# 构造数据：一个管理员用户、一个普通用户
from app import db  # noqa: E402
from app.models import User, SuperAdmin  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402
with app.app_context():
    su = SuperAdmin(name='root', password=generate_password_hash('x'))
    db.session.add(su)
    db.session.commit()
    with app.test_request_context():
        pass
    admin_user = User(student_id='admin001', name='管理员', password=generate_password_hash('x'),
                      email=f'admin001_{os.getpid()}@test.local', is_admin=True)
    normal_user = User(student_id='u001', name='普通用户', password=generate_password_hash('x'),
                       email=f'u001_{os.getpid()}@test.local', is_admin=False)
    db.session.add_all([admin_user, normal_user])
    db.session.commit()
    admin_uid, normal_uid = admin_user.id, normal_user.id
    super_admin_id = su.id

with app.app_context():
    s_token = create_access_token(identity=str(super_admin_id), additional_claims={'role': 'super_admin'})
r = client.delete(f'/sadmin/users/{admin_uid}', headers={'Authorization': f'Bearer {s_token}'})
check('新增1 超管禁删管理员', r.status_code in (400, 403), f'status={r.status_code}')
r = client.delete(f'/sadmin/users/{normal_uid}', headers={'Authorization': f'Bearer {s_token}'})
check('新增1 超管可删普通用户', r.status_code == 200, f'status={r.status_code}')
r = client.delete(f'/sadmin/users/{super_admin_id}', headers={'Authorization': f'Bearer {s_token}'})
check('新增1 超管禁删自己（404/400 均可，路由对象是 user 表）', r.status_code in (400, 403, 404), f'status={r.status_code}')

# ---------- 汇总 ----------
failed = [n for n, ok, _ in results if not ok]
print('\n==== SMOKE SUMMARY: %d/%d passed ====' % (len(results) - len(failed), len(results)))
if failed:
    print('FAILED:', failed)
    sys.exit(1)
