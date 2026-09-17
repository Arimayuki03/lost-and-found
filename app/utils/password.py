from werkzeug.security import generate_password_hash, check_password_hash

# werkzeug 3.x 生成的哈希格式为 "scrypt:..." / "pbkdf2:..."，用于区分历史明文密码
_HASH_PREFIXES = ('scrypt:', 'pbkdf2:')


def hash_password(raw_password):
    """将明文密码哈希后返回，用于所有新密码的写入"""
    return generate_password_hash(raw_password)


def verify_user_password(user, raw_password):
    """
    校验用户密码，兼容历史明文数据：
    - 存储为哈希值时使用 check_password_hash 校验
    - 存储为历史明文时退回直接比较，校验通过后立即改写为哈希（由调用方提交事务）
    """
    stored = user.password
    if not stored:
        return False

    if stored.startswith(_HASH_PREFIXES):
        return check_password_hash(stored, raw_password)

    # 历史明文密码：校验通过后透明升级为哈希存储
    if stored == raw_password:
        user.password = hash_password(raw_password)
        return True

    return False
