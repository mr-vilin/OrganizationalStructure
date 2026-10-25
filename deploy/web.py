"""为管理前端提供同源静态资源，不将不存在的 API 伪装成网页。"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse


def mount_frontend(app: FastAPI, directory: Path) -> bool:
    directory = directory.resolve()
    index = directory / 'index.html'
    if not index.is_file():
        return False
    @app.api_route('/{page:path}', methods=['GET', 'HEAD'], include_in_schema=False)
    def frontend(page: str):
        if page.split('/')[0] in {'admin', 'api', 'auth', 'health', 'internal', 'docs', 'redoc', 'openapi.json'}:
            raise HTTPException(404, detail={'code': 'NOT_FOUND', 'message': '接口不存在'})
        resource = (directory / page).resolve()
        if not resource.is_relative_to(directory) or '\\' in page or any(part.startswith('.') for part in Path(page).parts):
            raise HTTPException(404)
        if resource.is_file():
            # 未带内容哈希的入口和元信息每次重新校验，避免跨构建缓存。
            return FileResponse(resource, headers={'Cache-Control': 'no-cache'})
        if page.split('/')[0] == 'assets' or (Path(page).suffix and not page.startswith('employees/')):
            raise HTTPException(404, detail={'code': 'NOT_FOUND', 'message': '资源不存在'})
        return FileResponse(index, headers={'Cache-Control': 'no-cache'})

    return True
