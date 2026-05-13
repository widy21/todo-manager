from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

from config import PRIORITY_OPTIONS, STATUS_OPTIONS


db = SQLAlchemy()


class Category(db.Model):
    __tablename__ = 'category'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    color = db.Column(db.String(7), nullable=False, default='#2563eb')
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)

    todos = db.relationship('Todo', back_populates='category', lazy=True)

    def __repr__(self):
        return f'<Category {self.name}>'


class Todo(db.Model):
    __tablename__ = 'todo'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.Text)
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
