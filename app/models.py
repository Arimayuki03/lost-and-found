from sqlalchemy import TIMESTAMP, UniqueConstraint
from sqlalchemy.sql import func

from app import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    student_id = db.Column(db.String(12), unique=True, nullable=False)
    # 长度需容纳 werkzeug 哈希（scrypt 默认约 178 字符），与 lost_and_found.sql 中 varchar(255) 保持一致
    password = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    lost_items = db.relationship('LostItem', backref='user', lazy=True)
    found_items = db.relationship('FoundItem', backref='user', lazy=True)
    avatar_url = db.Column(db.String(200), nullable=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    created_at = db.Column(TIMESTAMP, server_default=func.now())


class LostItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    lost_time = db.Column(db.DateTime, nullable=False)
    location = db.Column(db.String(200), nullable=False)
    contact = db.Column(db.String(50), nullable=False)
    image_url = db.Column(db.String(200), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_completed = db.Column(db.Boolean, default=False)
    is_under_review = db.Column(db.Boolean, default=True)
    created_at = db.Column(TIMESTAMP, server_default=func.now())
    updated_at = db.Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "category": self.category,
            "name": self.name,
            "description": self.description,
            "lost_time": self.lost_time.isoformat() if self.lost_time else None,
            "location": self.location,
            "contact": self.contact,
            "image_url": self.image_url,
            "user_id": self.user_id,
            "is_completed": self.is_completed,
            "is_under_review": self.is_under_review,  # 新增审核字段
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }


class FoundItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    found_time = db.Column(db.DateTime, nullable=False)
    location = db.Column(db.String(200), nullable=False)
    contact = db.Column(db.String(50), nullable=False)
    image_url = db.Column(db.String(200), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_completed = db.Column(db.Boolean, default=False)
    is_under_review = db.Column(db.Boolean, default=True)
    created_at = db.Column(TIMESTAMP, server_default=func.now())
    updated_at = db.Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "category": self.category,
            "name": self.name,
            "description": self.description,
            "found_time": self.found_time.isoformat() if self.found_time else None,
            "location": self.location,
            "contact": self.contact,
            "image_url": self.image_url,
            "user_id": self.user_id,
            "is_completed": self.is_completed,
            "is_under_review": self.is_under_review,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }


class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(TIMESTAMP, server_default=func.now())

    user = db.relationship('User', backref='feedbacks')

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "content": self.content,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None
        }


class CarouselImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    image_url = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(TIMESTAMP, server_default=func.now())
    updated_at = db.Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "image_url": self.image_url,
            "description": self.description,
            "order": self.order,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }


class Announcement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(TIMESTAMP, server_default=func.now())
    updated_at = db.Column(TIMESTAMP, server_default=func.now(), onupdate=func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }


class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.TIMESTAMP, server_default=func.now())
    is_read = db.Column(db.Boolean, default=False)
    read_at = db.Column(db.TIMESTAMP, nullable=True)

    sender = db.relationship('User', foreign_keys=[sender_id], backref='messages_sent')
    receiver = db.relationship('User', foreign_keys=[receiver_id], backref='messages_received')

    def to_dict(self):
        return {
            "id": self.id,
            "sender_id": self.sender_id,
            "receiver_id": self.receiver_id,
            "message": self.message,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "is_read": self.is_read,
            "read_at": self.read_at.isoformat() if self.read_at else None
        }


class ItemMatch(db.Model):
    """失物和拾物匹配记录模型"""
    __table_args__ = (
        # 与调度器/手动触发并发兜底：同一对物品只允许一条匹配记录
        UniqueConstraint('lost_item_id', 'found_item_id', name='uk_lost_found'),
    )
    id = db.Column(db.Integer, primary_key=True)
    lost_item_id = db.Column(db.Integer, db.ForeignKey('lost_item.id'), nullable=False)
    found_item_id = db.Column(db.Integer, db.ForeignKey('found_item.id'), nullable=False)
    similarity_score = db.Column(db.Float, nullable=False)  # 相似度得分
    name_similarity = db.Column(db.Float, nullable=False)  # 名称相似度
    category_similarity = db.Column(db.Float, nullable=False)  # 类别相似度
    location_similarity = db.Column(db.Float, nullable=False)  # 地点相似度
    time_similarity = db.Column(db.Float, nullable=False)  # 时间相似度
    matched_at = db.Column(TIMESTAMP, server_default=func.now())  # 匹配时间
    notified = db.Column(db.Boolean, default=False)  # 是否已通知用户

    # 关联关系
    lost_item = db.relationship('LostItem', backref='matches')
    found_item = db.relationship('FoundItem', backref='matches')

    def to_dict(self):
        return {
            "id": self.id,
            "lost_item_id": self.lost_item_id,
            "found_item_id": self.found_item_id,
            "similarity_score": self.similarity_score,
            "name_similarity": self.name_similarity,
            "category_similarity": self.category_similarity,
            "location_similarity": self.location_similarity,
            "time_similarity": self.time_similarity,
            "matched_at": self.matched_at.isoformat() if self.matched_at else None,
            "notified": self.notified
        }


class SuperAdmin(db.Model):
    __tablename__ = 'super_admins'  # 确保表名为 super_admins
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)  # 超级管理员名称
    password = db.Column(db.String(200), nullable=False)  # 超级管理员密码
