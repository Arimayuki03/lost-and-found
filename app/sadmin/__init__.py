from flask import Blueprint

# 创建蓝图对象
sadmin = Blueprint("sadmin", __name__)
from . import superadmin
