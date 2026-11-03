"""生产同源入口；开发时前端由 Umi Max 提供。"""
from pathlib import Path

from app.main import app
from deploy.web import mount_frontend

mount_frontend(app, Path(__file__).resolve().parents[1] / 'frontend' / 'dist')
