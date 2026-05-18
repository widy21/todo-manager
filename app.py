from datetime import date, datetime, timedelta

from flask import Flask, flash, redirect, render_template, request, url_for
from sqlalchemy import case, or_
from werkzeug.middleware.proxy_fix import ProxyFix

import config
from models import Category, Todo, db


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(config)
    if test_config:
        app.config.update(test_config)

    # Respect proxy headers so the app can live under a path prefix like /todo.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    db.init_app(app)

    @app.context_processor
    def inject_options():
        return {
            'priority_options': config.PRIORITY_OPTIONS,
            'status_options': config.STATUS_OPTIONS,
        }

    register_routes(app)

    with app.app_context():
        db.create_all()
        seed_default_categories()

    return app


def seed_default_categories():
    if Category.query.count() > 0:
        return
    for item in config.DEFAULT_CATEGORIES:
        db.session.add(Category(**item))
    db.session.commit()


def parse_date(value):
    if not value:
        return None
    return datetime.strptime(value, '%Y-%m-%d').date()


def validate_todo_form(form):
    errors = []
    title = form.get('title', '').strip()
    description = form.get('description', '').strip()
    category_id = form.get('category_id', type=int)
    priority = form.get('priority', 'medium')
    start_date = parse_date(form.get('start_date'))
    end_date = parse_date(form.get('end_date'))

    if not title:
        errors.append('标题不能为空')
    if not category_id or not Category.query.get(category_id):
        errors.append('请选择有效分类')
    if priority not in config.PRIORITY_OPTIONS:
        errors.append('请选择有效优先级')
    if start_date and end_date and start_date > end_date:
        errors.append('开始日期不能晚于结束日期')

    return errors, {
        'title': title,
        'description': description,
        'category_id': category_id,
        'priority': priority,
        'start_date': start_date,
        'end_date': end_date,
    }


def active_categories():
    return Category.query.order_by(Category.sort_order, Category.name).all()


def apply_todo_filters(query, include_search=True):
    category_id = request.args.get('category_id', type=int)
    priority = request.args.get('priority', '')
    q = request.args.get('q', '').strip() if include_search else ''

    if category_id:
        query = query.filter(Todo.category_id == category_id)
    if priority in config.PRIORITY_OPTIONS:
        query = query.filter(Todo.priority == priority)
    if q:
        like = f'%{q}%'
        query = query.join(Category).filter(
            or_(Todo.title.ilike(like), Todo.description.ilike(like), Category.name.ilike(like))
        )
    return query


def report_date_range(range_key):
    today = date.today()
    if range_key == 'week':
        start = today - timedelta(days=today.weekday())
        return start, today
    if range_key == 'month':
        return today.replace(day=1), today
    if range_key == 'year':
        return today.replace(month=1, day=1), today
    return None, None


def register_routes(app):
    @app.route('/')
    def index():
        view = request.args.get('view', 'card')
        if view not in {'card', 'list', 'timeline'}:
            view = 'card'

        query = Todo.query.filter(Todo.status == 'active', Todo.deleted_at.is_(None))
        query = apply_todo_filters(query)
        priority_order = case(
            (Todo.priority == 'high', 3),
            (Todo.priority == 'medium', 2),
            (Todo.priority == 'low', 1),
            else_=0,
        )
        todos = query.order_by(priority_order.desc(), Todo.end_date.is_(None), Todo.end_date, Todo.created_at.desc()).all()

        return render_template(
            'index.html',
            todos=todos,
            categories=active_categories(),
            view=view,
            selected_category=request.args.get('category_id', type=int),
            selected_priority=request.args.get('priority', ''),
            q=request.args.get('q', '').strip(),
        )

    @app.route('/todo/new', methods=['GET', 'POST'])
    def todo_new():
        todo = Todo(priority='medium')
        if request.method == 'POST':
            errors, data = validate_todo_form(request.form)
            if not errors:
                todo = Todo(**data, status='active')
                db.session.add(todo)
                db.session.commit()
                flash('待办事项已创建', 'success')
                return redirect(url_for('index'))
            for error in errors:
                flash(error, 'error')
            for key, value in data.items():
                setattr(todo, key, value)

        return render_template('todo_form.html', todo=todo, categories=active_categories(), mode='new')

    @app.route('/todo/<int:id>/edit', methods=['GET', 'POST'])
    def todo_edit(id):
        todo = Todo.query.get_or_404(id)
        if request.method == 'POST':
            errors, data = validate_todo_form(request.form)
            if not errors:
                for key, value in data.items():
                    setattr(todo, key, value)
                db.session.commit()
                flash('待办事项已更新', 'success')
                return redirect(url_for('index'))
            for error in errors:
                flash(error, 'error')

        return render_template('todo_form.html', todo=todo, categories=active_categories(), mode='edit')

    @app.route('/todo/<int:id>/complete', methods=['POST'])
    def todo_complete(id):
        todo = Todo.query.get_or_404(id)
        todo.status = 'completed'
        todo.completed_at = datetime.now()
        todo.archived_at = None
        db.session.commit()
        flash('待办事项已标记完成', 'success')
        return redirect(request.referrer or url_for('index'))

    @app.route('/todo/<int:id>/archive', methods=['POST'])
    def todo_archive(id):
        todo = Todo.query.get_or_404(id)
        todo.status = 'archived'
        todo.archived_at = datetime.now()
        db.session.commit()
        flash('待办事项已归档', 'success')
        return redirect(request.referrer or url_for('index'))

    @app.route('/todo/<int:id>/restore', methods=['POST'])
    def todo_restore(id):
        todo = Todo.query.get_or_404(id)
        todo.status = 'active'
        todo.archived_at = None
        db.session.commit()
        flash('待办事项已恢复', 'success')
        return redirect(request.referrer or url_for('index'))

    @app.route('/todo/<int:id>/delete', methods=['POST'])
    def todo_delete(id):
        todo = Todo.query.get_or_404(id)
        todo.deleted_at = datetime.now()
        db.session.commit()
        flash('待办事项已逻辑删除', 'success')
        return redirect(request.referrer or url_for('index'))

    @app.route('/archive')
    def archive():
        todos = Todo.query.filter(Todo.status == 'archived', Todo.deleted_at.is_(None)).order_by(Todo.archived_at.desc()).all()
        return render_template('archive.html', todos=todos)

    @app.route('/reports')
    def reports():
        range_key = request.args.get('range', 'month')
        category_id = request.args.get('category_id', type=int)
        priority = request.args.get('priority', '')
        start, end = report_date_range(range_key)

        query = Todo.query.filter(Todo.status == 'completed')
        if start:
            query = query.filter(Todo.completed_at >= datetime.combine(start, datetime.min.time()))
        if end:
            query = query.filter(Todo.completed_at <= datetime.combine(end, datetime.max.time()))
        if category_id:
            query = query.filter(Todo.category_id == category_id)
        if priority in config.PRIORITY_OPTIONS:
            query = query.filter(Todo.priority == priority)

        todos = query.order_by(Todo.completed_at.desc()).all()
        priority_counts = {key: 0 for key in config.PRIORITY_OPTIONS}
        category_counts = {}
        for todo in todos:
            priority_counts[todo.priority] = priority_counts.get(todo.priority, 0) + 1
            name = todo.category.name if todo.category else '未分类'
            category_counts[name] = category_counts.get(name, 0) + 1

        max_category_count = max(category_counts.values(), default=1)
        return render_template(
            'reports.html',
            todos=todos,
            categories=active_categories(),
            range_key=range_key,
            selected_category=category_id,
            selected_priority=priority,
            priority_counts=priority_counts,
            category_counts=category_counts,
            max_category_count=max_category_count,
        )

    @app.route('/categories')
    def categories():
        items = active_categories()
        return render_template('categories.html', categories=items)

    @app.route('/category/new', methods=['POST'])
    def category_new():
        name = request.form.get('name', '').strip()
        color = request.form.get('color', '#2563eb')
        sort_order = request.form.get('sort_order', type=int) or 0
        if not name:
            flash('分类名称不能为空', 'error')
        elif Category.query.filter_by(name=name).first():
            flash('分类名称已存在', 'error')
        else:
            db.session.add(Category(name=name, color=color, sort_order=sort_order))
            db.session.commit()
            flash('分类已创建', 'success')
        return redirect(url_for('categories'))

    @app.route('/category/<int:id>/edit', methods=['POST'])
    def category_edit(id):
        category = Category.query.get_or_404(id)
        name = request.form.get('name', '').strip()
        color = request.form.get('color', '#2563eb')
        sort_order = request.form.get('sort_order', type=int) or 0
        exists = Category.query.filter(Category.name == name, Category.id != id).first()
        if not name:
            flash('分类名称不能为空', 'error')
        elif exists:
            flash('分类名称已存在', 'error')
        else:
            category.name = name
            category.color = color
            category.sort_order = sort_order
            db.session.commit()
            flash('分类已更新', 'success')
        return redirect(url_for('categories'))

    @app.route('/category/<int:id>/delete', methods=['POST'])
    def category_delete(id):
        category = Category.query.get_or_404(id)
        if Todo.query.filter_by(category_id=id).first():
            flash('该分类已有待办关联，不能删除', 'error')
        else:
            db.session.delete(category)
            db.session.commit()
            flash('分类已删除', 'success')
        return redirect(url_for('categories'))


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
