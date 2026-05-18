import re
from datetime import date, datetime, timedelta
from functools import wraps
from urllib.parse import urlsplit

from flask import Flask, abort, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from sqlalchemy import case, inspect, or_, text
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

import config
from models import Category, Todo, User, db


USERNAME_RE = re.compile(r'^[A-Za-z0-9_]+$')

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.login_message = '请先登录后再访问'
login_manager.login_message_category = 'error'


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


@login_manager.unauthorized_handler
def handle_unauthorized():
    return redirect(url_for('login', next=request.full_path if request.query_string else request.path))


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(config)
    if test_config:
        app.config.update(test_config)

    # Respect proxy headers so the app can live under a path prefix like /todo.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
    db.init_app(app)
    login_manager.init_app(app)

    @app.context_processor
    def inject_options():
        return {
            'priority_options': config.PRIORITY_OPTIONS,
            'status_options': config.STATUS_OPTIONS,
            'role_options': config.ROLE_OPTIONS,
        }

    register_routes(app)

    with app.app_context():
        db.create_all()
        admin_user = ensure_default_admin()
        migrate_legacy_schema(admin_user.id)
        seed_default_categories_for_user(admin_user.id)

    return app


def hash_password(password):
    return generate_password_hash(password, method='pbkdf2:sha256')


def ensure_default_admin():
    existing_user = User.query.order_by(User.id).first()
    if existing_user:
        return existing_user

    admin = User(
        username=current_app_config('ADMIN_USERNAME'),
        password_hash=hash_password(current_app_config('ADMIN_PASSWORD')),
        display_name='系统管理员',
        role='admin',
        is_active=True,
    )
    db.session.add(admin)
    db.session.commit()
    return admin


def current_app_config(key):
    from flask import current_app

    return current_app.config[key]


def migrate_legacy_schema(admin_user_id):
    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())

    if 'category' in tables:
        category_columns = {column['name'] for column in inspector.get_columns('category')}
        if 'owner_id' not in category_columns:
            rebuild_category_table(admin_user_id)
        else:
            db.session.execute(
                text('UPDATE category SET owner_id = :owner_id WHERE owner_id IS NULL'),
                {'owner_id': admin_user_id},
            )
            db.session.commit()

    inspector = inspect(db.engine)
    tables = set(inspector.get_table_names())
    if 'todo' in tables:
        todo_columns = {column['name'] for column in inspector.get_columns('todo')}
        if 'owner_id' not in todo_columns:
            db.session.execute(text('ALTER TABLE todo ADD COLUMN owner_id INTEGER'))
            db.session.commit()
        db.session.execute(
            text('UPDATE todo SET owner_id = :owner_id WHERE owner_id IS NULL'),
            {'owner_id': admin_user_id},
        )
        db.session.commit()


def rebuild_category_table(admin_user_id):
    with db.engine.begin() as connection:
        connection.execute(text('PRAGMA foreign_keys=OFF'))
        connection.execute(text('DROP TABLE IF EXISTS category__new'))
        connection.execute(text(
            'CREATE TABLE category__new ('
            'id INTEGER NOT NULL PRIMARY KEY, '
            'name VARCHAR(50) NOT NULL, '
            "color VARCHAR(7) NOT NULL DEFAULT '#2563eb', "
            'sort_order INTEGER NOT NULL DEFAULT 0, '
            'owner_id INTEGER NOT NULL, '
            'created_at DATETIME NOT NULL, '
            'FOREIGN KEY(owner_id) REFERENCES user (id)'
            ')'
        ))
        connection.execute(text(
            'INSERT INTO category__new (id, name, color, sort_order, owner_id, created_at) '
            'SELECT id, name, color, sort_order, :owner_id, created_at FROM category'
        ), {'owner_id': admin_user_id})
        connection.execute(text('DROP TABLE category'))
        connection.execute(text('ALTER TABLE category__new RENAME TO category'))
        connection.execute(text(
            'CREATE UNIQUE INDEX IF NOT EXISTS uq_category_owner_name '
            'ON category (owner_id, name)'
        ))
        connection.execute(text(
            'CREATE INDEX IF NOT EXISTS ix_category_owner_sort '
            'ON category (owner_id, sort_order, name)'
        ))
        connection.execute(text('PRAGMA foreign_keys=ON'))


def seed_default_categories_for_user(user_id):
    existing_count = Category.query.filter_by(owner_id=user_id).count()
    if existing_count > 0:
        return
    for item in config.DEFAULT_CATEGORIES:
        db.session.add(Category(owner_id=user_id, **item))
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

    category = None
    if category_id:
        category = Category.query.filter_by(id=category_id, owner_id=current_user.id).first()
    if not category:
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
    return Category.query.filter_by(owner_id=current_user.id).order_by(Category.sort_order, Category.name).all()


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


def admin_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapped(*args, **kwargs):
        if current_user.role != 'admin':
            abort(403)
        return view_func(*args, **kwargs)

    return wrapped


def get_owned_todo_or_404(todo_id):
    return Todo.query.filter_by(id=todo_id, owner_id=current_user.id).first_or_404()


def get_owned_category_or_404(category_id):
    return Category.query.filter_by(id=category_id, owner_id=current_user.id).first_or_404()


def get_safe_next_url():
    next_url = request.values.get('next', '').strip()
    if not next_url:
        return url_for('index')
    parsed = urlsplit(next_url)
    if parsed.netloc or not next_url.startswith('/'):
        return url_for('index')
    return next_url


def validate_username(username):
    if not username:
        return '用户名不能为空'
    if not USERNAME_RE.match(username):
        return '用户名只允许字母、数字和下划线'
    return None


def validate_password(password):
    if len(password) < current_app_config('MIN_PASSWORD_LENGTH'):
        return f'密码长度不能少于 {current_app_config("MIN_PASSWORD_LENGTH")} 位'
    return None


def register_routes(app):
    @app.errorhandler(403)
    def forbidden(_error):
        return render_template('forbidden.html'), 403

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('index'))

        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')
            user = User.query.filter_by(username=username).first()

            if not user or not check_password_hash(user.password_hash, password):
                flash('用户名或密码错误', 'error')
            elif not user.is_active:
                flash('当前账号已被禁用，请联系管理员', 'error')
            else:
                login_user(user)
                user.last_login_at = datetime.now()
                db.session.commit()
                flash('登录成功', 'success')
                return redirect(get_safe_next_url())

        return render_template('login.html', next_url=request.args.get('next', ''))

    @app.route('/logout', methods=['POST'])
    @login_required
    def logout():
        logout_user()
        flash('已退出登录', 'success')
        return redirect(url_for('login'))

    @app.route('/')
    @login_required
    def index():
        view = request.args.get('view', 'card')
        if view not in {'card', 'list', 'timeline'}:
            view = 'card'

        query = Todo.query.filter(
            Todo.owner_id == current_user.id,
            Todo.status == 'active',
            Todo.deleted_at.is_(None),
        )
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
    @login_required
    def todo_new():
        todo = Todo(priority='medium')
        if request.method == 'POST':
            errors, data = validate_todo_form(request.form)
            if not errors:
                todo = Todo(**data, status='active', owner_id=current_user.id)
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
    @login_required
    def todo_edit(id):
        todo = get_owned_todo_or_404(id)
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
            for key, value in data.items():
                setattr(todo, key, value)

        return render_template('todo_form.html', todo=todo, categories=active_categories(), mode='edit')

    @app.route('/todo/<int:id>/complete', methods=['POST'])
    @login_required
    def todo_complete(id):
        todo = get_owned_todo_or_404(id)
        todo.status = 'completed'
        todo.completed_at = datetime.now()
        todo.archived_at = None
        db.session.commit()
        flash('待办事项已标记完成', 'success')
        return redirect(request.referrer or url_for('index'))

    @app.route('/todo/<int:id>/archive', methods=['POST'])
    @login_required
    def todo_archive(id):
        todo = get_owned_todo_or_404(id)
        todo.status = 'archived'
        todo.archived_at = datetime.now()
        db.session.commit()
        flash('待办事项已归档', 'success')
        return redirect(request.referrer or url_for('index'))

    @app.route('/todo/<int:id>/restore', methods=['POST'])
    @login_required
    def todo_restore(id):
        todo = get_owned_todo_or_404(id)
        todo.status = 'active'
        todo.archived_at = None
        db.session.commit()
        flash('待办事项已恢复', 'success')
        return redirect(request.referrer or url_for('index'))

    @app.route('/todo/<int:id>/delete', methods=['POST'])
    @login_required
    def todo_delete(id):
        todo = get_owned_todo_or_404(id)
        todo.deleted_at = datetime.now()
        db.session.commit()
        flash('待办事项已逻辑删除', 'success')
        return redirect(request.referrer or url_for('index'))

    @app.route('/archive')
    @login_required
    def archive():
        todos = Todo.query.filter(
            Todo.owner_id == current_user.id,
            Todo.status == 'archived',
            Todo.deleted_at.is_(None),
        ).order_by(Todo.archived_at.desc()).all()
        return render_template('archive.html', todos=todos)

    @app.route('/reports')
    @login_required
    def reports():
        range_key = request.args.get('range', 'month')
        category_id = request.args.get('category_id', type=int)
        priority = request.args.get('priority', '')
        start, end = report_date_range(range_key)

        query = Todo.query.filter(Todo.owner_id == current_user.id, Todo.status == 'completed')
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
    @login_required
    def categories():
        items = active_categories()
        return render_template('categories.html', categories=items)

    @app.route('/category/new', methods=['POST'])
    @login_required
    def category_new():
        name = request.form.get('name', '').strip()
        color = request.form.get('color', '#2563eb')
        sort_order = request.form.get('sort_order', type=int) or 0
        if not name:
            flash('分类名称不能为空', 'error')
        elif Category.query.filter_by(owner_id=current_user.id, name=name).first():
            flash('分类名称已存在', 'error')
        else:
            db.session.add(Category(name=name, color=color, sort_order=sort_order, owner_id=current_user.id))
            db.session.commit()
            flash('分类已创建', 'success')
        return redirect(url_for('categories'))

    @app.route('/category/<int:id>/edit', methods=['POST'])
    @login_required
    def category_edit(id):
        category = get_owned_category_or_404(id)
        name = request.form.get('name', '').strip()
        color = request.form.get('color', '#2563eb')
        sort_order = request.form.get('sort_order', type=int) or 0
        exists = Category.query.filter(
            Category.owner_id == current_user.id,
            Category.name == name,
            Category.id != id,
        ).first()
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
    @login_required
    def category_delete(id):
        category = get_owned_category_or_404(id)
        if Todo.query.filter_by(owner_id=current_user.id, category_id=id).first():
            flash('该分类已有待办关联，不能删除', 'error')
        else:
            db.session.delete(category)
            db.session.commit()
            flash('分类已删除', 'success')
        return redirect(url_for('categories'))

    @app.route('/users')
    @admin_required
    def users():
        items = User.query.order_by(User.role.desc(), User.created_at.desc(), User.id.desc()).all()
        return render_template('users.html', users=items)

    @app.route('/users/new', methods=['POST'])
    @admin_required
    def user_new():
        username = request.form.get('username', '').strip()
        display_name = request.form.get('display_name', '').strip() or username
        password = request.form.get('password', '')
        role = request.form.get('role', 'user')

        username_error = validate_username(username)
        password_error = validate_password(password)
        if username_error:
            flash(username_error, 'error')
        elif password_error:
            flash(password_error, 'error')
        elif role not in config.ROLE_OPTIONS:
            flash('请选择有效角色', 'error')
        elif User.query.filter_by(username=username).first():
            flash('用户名已存在', 'error')
        else:
            user = User(
                username=username,
                password_hash=hash_password(password),
                display_name=display_name,
                role=role,
                is_active=True,
            )
            db.session.add(user)
            db.session.flush()
            for item in config.DEFAULT_CATEGORIES:
                db.session.add(Category(owner_id=user.id, **item))
            db.session.commit()
            flash('用户已创建', 'success')
        return redirect(url_for('users'))

    @app.route('/users/<int:id>/toggle', methods=['POST'])
    @admin_required
    def user_toggle(id):
        user = db.session.get(User, id)
        if not user:
            abort(404)

        if user.id == current_user.id and user.is_active:
            flash('不能禁用当前登录账号', 'error')
        else:
            user.is_active = not user.is_active
            db.session.commit()
            flash('用户状态已更新', 'success')
        return redirect(url_for('users'))

    @app.route('/users/<int:id>/reset-password', methods=['POST'])
    @admin_required
    def user_reset_password(id):
        user = db.session.get(User, id)
        if not user:
            abort(404)

        password = request.form.get('password', '')
        password_error = validate_password(password)
        if password_error:
            flash(password_error, 'error')
        else:
            user.password_hash = hash_password(password)
            db.session.commit()
            flash('密码已重置', 'success')
        return redirect(url_for('users'))


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
