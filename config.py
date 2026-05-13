import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(BASE_DIR, 'data.db')

SQLALCHEMY_DATABASE_URI = f'sqlite:///{DATABASE_PATH}'
SQLALCHEMY_TRACK_MODIFICATIONS = False
SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
JSON_AS_ASCII = False

PRIORITY_OPTIONS = {
    'high': {'label': '高', 'color': '#dc2626'},
    'medium': {'label': '中', 'color': '#d97706'},
    'low': {'label': '低', 'color': '#059669'},
}

STATUS_OPTIONS = {
    'active': {'label': '待办', 'color': '#2563eb'},
    'completed': {'label': '已完成', 'color': '#16a34a'},
    'archived': {'label': '已归档', 'color': '#64748b'},
}

DEFAULT_CATEGORIES = [
    {'name': '个人', 'color': '#2563eb', 'sort_order': 10},
    {'name': '工作', 'color': '#059669', 'sort_order': 20},
    {'name': '项目', 'color': '#d97706', 'sort_order': 30},
]
