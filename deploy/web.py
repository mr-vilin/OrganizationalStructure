"""为管理前端提供同源静态资源，不将不存在的 API 伪装成网页。"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def mount_frontend(app: FastAPI, directory: Path) -> bool:
    index = directory / 'index.html'
    if not index.is_file():
        return False
    assets = directory / 'assets'
    if assets.is_dir():
        app.mount('/assets', StaticFiles(directory=assets), name='assets')

    @app.get('/{page:path}', include_in_schema=False)
    def frontend(page: str):
        if page.split('/')[0] in {'admin', 'api', 'health', 'assets', 'docs', 'redoc', 'openapi.json'}:
            raise HTTPException(404, detail={'code': 'NOT_FOUND', 'message': '接口不存在'})
        return FileResponse(index, headers={'Cache-Control': 'no-cache'})

    return True
