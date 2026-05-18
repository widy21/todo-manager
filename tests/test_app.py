import os
import sys
from datetime import datetime

import pytest

ROOT = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, ROOT)

from app import create_app
from models import Category, Todo, db


@pytest.fixture()
def app():
    app = create_app({
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'WTF_CSRF_ENABLED': False,
    })
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def first_category_id(app):
    with app.app_context():
        return Category.query.order_by(Category.id).first().id


def create_todo(client, category_id, title='完成接口设计', description='API 搜索能力'):
    return client.post('/todo/new', data={
        'title': title,
        'description': description,
        'category_id': category_id,
        'priority': 'high',
        'start_date': '2026-05-12',
        'end_date': '2026-05-14',
    }, follow_redirects=True)


def test_create_search_complete_and_report(client, app):
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
        todo = Todo.query.get(todo_id)
        assert todo is not None
        assert todo.deleted_at is not None


def test_completed_deleted_todo_still_in_report(client, app):
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
    category_id = first_category_id(app)
    response = client.post('/todo/new', data={
        'title': '错误日期',
        'category_id': category_id,
        'priority': 'medium',
        'start_date': '2026-05-20',
        'end_date': '2026-05-12',
    }, follow_redirects=True)
    assert '开始日期不能晚于结束日期'.encode() in response.data


def test_reverse_proxy_prefix_support(client):
    response = client.get(
        '/',
        headers={
            'X-Forwarded-Proto': 'http',
            'X-Forwarded-Host': '82.156.157.166',
            'X-Forwarded-Prefix': '/todo',
        },
    )
    assert response.status_code == 200
    assert 'href="/todo/"'.encode() in response.data
    assert 'href="/todo/todo/new"'.encode() in response.data
    assert 'href="/todo/categories"'.encode() in response.data
    assert 'href="/todo/reports"'.encode() in response.data
    assert 'href="/todo/archive"'.encode() in response.data
    assert 'href="/todo/static/css/style.css"'.encode() in response.data
