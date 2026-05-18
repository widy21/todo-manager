from datetime import datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint

from config import PRIORITY_OPTIONS, ROLE_OPTIONS, STATUS_OPTIONS


db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(50), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='user')
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    last_login_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    categories = db.relationship('Category', back_populates='owner', lazy=True)
    todos = db.relationship('Todo', back_populates='owner', lazy=True)

    def __repr__(self):
        return f'<User {self.username}>'

    @property
    def role_label(self):
        return ROLE_OPTIONS.get(self.role, {}).get('label', self.role)


class Category(db.Model):
    __tablename__ = 'category'
    __table_args__ = (
        UniqueConstraint('owner_id', 'name', name='uq_category_owner_name'),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    color = db.Column(db.String(7), nullable=False, default='#2563eb')
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    owner = db.relationship('User', back_populates='categories')
    todos = db.relationship('Todo', back_populates='category', lazy=True)

    def __repr__(self):
        return f'<Category {self.name}>'


class Todo(db.Model):
    __tablename__ = 'todo'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    priority = db.Column(db.String(20), nullable=False, default='medium')
    start_date = db.Column(db.Date)
    end_date = db.Column(db.Date)
    status = db.Column(db.String(20), nullable=False, default='active')
    completed_at = db.Column(db.DateTime)
    archived_at = db.Column(db.DateTime)
    deleted_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    category = db.relationship('Category', back_populates='todos')
    owner = db.relationship('User', back_populates='todos')

    def __repr__(self):
        return f'<Todo {self.title}>'

    @property
    def priority_label(self):
        return PRIORITY_OPTIONS.get(self.priority, {}).get('label', self.priority)

    @property
    def priority_color(self):
        return PRIORITY_OPTIONS.get(self.priority, {}).get('color', '#64748b')

    @property
    def status_label(self):
        return STATUS_OPTIONS.get(self.status, {}).get('label', self.status)

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    @property
    def date_range_label(self):
        if self.start_date and self.end_date:
            return f'{self.start_date:%Y-%m-%d} ~ {self.end_date:%Y-%m-%d}'
        if self.start_date:
            return f'{self.start_date:%Y-%m-%d} 开始'
        if self.end_date:
            return f'{self.end_date:%Y-%m-%d} 截止'
        return '无日期'
