# Todo Manager

一个基于 Flask + SQLAlchemy + SQLite 的 B/S 待办事项管理项目。

## 功能

- 待办新增、编辑、完成、归档、恢复、逻辑删除
- 分类新增、编辑、删除
- 首页按标题、描述、分类模糊搜索
- 卡片、列表、时间轴三种展示方式
- 已完成事项报告，按分类和优先级汇总

## 启动

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

访问 `http://127.0.0.1:5000`。
