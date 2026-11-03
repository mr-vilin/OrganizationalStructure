"""产品构建元信息；与包版本、API 及数据库版本分别管理。"""
import json
from pathlib import Path


def product_build_info() -> dict:
    built = Path(__file__).with_name('_build_info.json')
    if built.is_file():
        return json.loads(built.read_text(encoding='utf-8'))
    # 源码开发模式没有打包元信息，不伪造提交、构建时间或发布日期。
    manifest = Path(__file__).resolve().parents[2] / 'version.json'
    version = json.loads(manifest.read_text(encoding='utf-8'))['version']
    return {'version': version, 'commit': 'unknown', 'dirty': None, 'builtAt': None,
            'stage': 'development', 'releaseDate': None}
