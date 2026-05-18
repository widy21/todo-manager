import os
import sqlite3
import sys
from datetime import datetime

import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from app import create_app
from models import Category, Todo, User, db


@pytest.fixture()
def app(tmp_path):
    database_path = tmp_path / 'test.db'
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{database_path}',
        'WTF_CSRF_ENABLED': False,
        'SECRET_KEY': 'test-secret',
    })
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, username='admin', password='admin123'):
    return client.post('/login', data={
        'username': username,
        'password': password,
    }, follow_redirects=True)


def logout(client):
    return client.post('/logout', follow_redirects=True)


def first_category_id(app, username='admin'):
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        return Category.query.filter_by(owner_id=user.id).order_by(Category.id).first().id


def create_todo(client, category_id, title='完成接口设计', description='API 搜索能力'):
    return client.post('/todo/new', data={
        'title': title,
        'description': description,
        'category_id': category_id,
        'priority': 'high',
        'start_date': '2026-05-12',
        'end_date': '2026-05-14',
    }, follow_redirects=True)


def create_user(client, username='user_b', display_name='用户B', password='User123_', role='user'):
    return client.post('/users/new', data={
        'username': username,
        'display_name': display_name,
        'password': password,
        'role': role,
    }, follow_redirects=True)


def test_login_required_and_login_success(client):
    response = client.get('/')
    assert response.status_code == 302
    assert '/login' in response.headers['Location']

    response = login(client)
    assert '登录成功'.encode() in response.data
    assert 'Todo Manager'.encode() in response.data


def test_create_search_complete_and_report(client, app):
    login(client)
    category_id = first_category_id(app)
    response = create_todo(client, category_id)
    assert '待办事项已创建'.encode() in response.data

    response = client.get('/?q=接口&view=list')
    assert '完成接口设计'.encode() in response.data

    with app.app_context():
        todo_id = Todo.query.filter_by(title='完成接口设计').first().id

    client.post(f'/todo/{todo_id}/complete', follow_redirects=True)
    response = client.get('/')
    assert '完成接口设计'.encode() not in response.data

    response = client.get('/reports?range=all')
    assert '完成接口设计'.encode() in response.data
    assert '总完成'.encode() in response.data


def test_archive_restore_and_logical_delete(client, app):
    login(client)
    category_id = first_category_id(app)
    create_todo(client, category_id, title='整理照片')
    with app.app_context():
        todo_id = Todo.query.filter_by(title='整理照片').first().id

    client.post(f'/todo/{todo_id}/archive', follow_redirects=True)
    response = client.get('/archive')
    assert '整理照片'.encode() in response.data

    client.post(f'/todo/{todo_id}/restore', follow_redirects=True)
    response = client.get('/')
    assert '整理照片'.encode() in response.data

    client.post(f'/todo/{todo_id}/delete', follow_redirects=True)
    response = client.get('/')
    assert '整理照片'.encode() not in response.data
    with app.app_context():
        todo = db.session.get(Todo, todo_id)
        assert todo is not None
        assert todo.deleted_at is not None


def test_completed_deleted_todo_still_in_report(client, app):
    login(client)
    category_id = first_category_id(app)
    create_todo(client, category_id, title='完成周报')
    with app.app_context():
        todo_id = Todo.query.filter_by(title='完成周报').first().id

    client.post(f'/todo/{todo_id}/complete', follow_redirects=True)
    client.post(f'/todo/{todo_id}/delete', follow_redirects=True)
    response = client.get('/reports?range=all')
    assert '完成周报'.encode() in response.data
    assert '已删除'.encode() in response.data


def test_date_validation(client, app):
    login(client)
    category_id = first_category_id(app)
    response = client.post('/todo/new', data={
        'title': '错误日期',
        'category_id': category_id,
        'priority': 'medium',
        'start_date': '2026-05-20',
        'end_date': '2026-05-12',
    }, follow_redirects=True)
    assert '开始日期不能晚于结束日期'.encode() in response.data


def test_user_isolation_and_admin_access_control(client, app):
    login(client)
    admin_category_id = first_category_id(app)
    create_todo(client, admin_category_id, title='管理员事项')
    response = create_user(client)
    assert '用户已创建'.encode() in response.data

    logout(client)
    response = login(client, username='user_b', password='User123_')
    assert '登录成功'.encode() in response.data

    response = client.get('/users')
    assert response.status_code == 403

    response = client.get('/')
    assert '管理员事项'.encode() not in response.data

    second_category_id = first_category_id(app, username='user_b')
    response = create_todo(client, second_category_id, title='用户B事项')
    assert '待办事项已创建'.encode() in response.data

    with app.app_context():
        admin_todo_id = Todo.query.filter_by(title='管理员事项').first().id

    response = client.post(f'/todo/{admin_todo_id}/delete', follow_redirects=False)
    assert response.status_code == 404

    logout(client)
    login(client)
    response = client.get('/')
    assert '管理员事项'.encode() in response.data
    assert '用户B事项'.encode() not in response.data


def test_legacy_data_migrates_to_default_admin(tmp_path):
    database_path = tmp_path / 'legacy.db'
    conn = sqlite3.connect(database_path)
    conn.execute(
        'CREATE TABLE category ('
        'id INTEGER NOT NULL PRIMARY KEY, '
        'name VARCHAR(50) NOT NULL UNIQUE, '
        'color VARCHAR(7) NOT NULL DEFAULT "#2563eb", '
        'sort_order INTEGER NOT NULL DEFAULT 0, '
        'created_at DATETIME NOT NULL'
        ')'
    )
    conn.execute(
        'CREATE TABLE todo ('
        'id INTEGER NOT NULL PRIMARY KEY, '
        'title VARCHAR(120) NOT NULL, '
        'description TEXT, '
        'category_id INTEGER NOT NULL, '
        'priority VARCHAR(20) NOT NULL DEFAULT "medium", '
        'start_date DATE, '
        'end_date DATE, '
        'status VARCHAR(20) NOT NULL DEFAULT "active", '
        'completed_at DATETIME, '
        'archived_at DATETIME, '
        'deleted_at DATETIME, '
        'created_at DATETIME NOT NULL, '
        'updated_at DATETIME NOT NULL, '
        'FOREIGN KEY(category_id) REFERENCES category(id)'
        ')'
    )
    now = datetime.now().isoformat(sep=' ')
    conn.execute(
        'INSERT INTO category (id, name, color, sort_order, created_at) VALUES (?, ?, ?, ?, ?)',
        (1, '历史分类', '#2563eb', 10, now),
    )
    conn.execute(
        'INSERT INTO todo (id, title, description, category_id, priority, status, created_at, updated_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (1, '历史待办', '迁移前数据', 1, 'high', 'active', now, now),
    )
    conn.commit()
    conn.close()

    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{database_path}',
        'SECRET_KEY': 'test-secret',
    })

    with app.app_context():
        admin = User.query.filter_by(username='admin').first()
        assert admin is not None

        category = Category.query.filter_by(name='历史分类').first()
        todo = Todo.query.filter_by(title='历史待办').first()
        assert category.owner_id == admin.id
        assert todo.owner_id == admin.id

    client = app.test_client()
    login_response = client.post('/login', data={
        'username': 'admin',
        'password': 'admin123',
    }, follow_redirects=True)
    assert '登录成功'.encode() in login_response.data
    home_response = client.get('/')
    assert '历史待办'.encode() in home_response.data


def test_reverse_proxy_prefix_support(client):
    response = client.get(
        '/',
        headers={
            'X-Forwarded-Proto': 'http',
            'X-Forwarded-Host': '82.156.157.166',
            'X-Forwarded-Prefix': '/todo',
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert '/todo/login?next=/todo/' == response.headers['Location']
