import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from deploy.web import mount_frontend


class FrontendServingTests(unittest.TestCase):
    def test_spa_navigation_and_assets_work_but_unknown_api_stays_404(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'assets').mkdir()
            (root / 'index.html').write_text('<html>organization app</html>', encoding='utf-8')
            (root / 'assets' / 'app.js').write_text('export const app = true', encoding='utf-8')
            app = FastAPI()
            mount_frontend(app, root)
            with TestClient(app) as client:
                self.assertIn('organization app', client.get('/organization').text)
                self.assertEqual(client.get('/assets/app.js').status_code, 200)
                self.assertEqual(client.get('/api/v1/missing').status_code, 404)
                self.assertEqual(client.get('/admin/api/missing').status_code, 404)
                self.assertEqual(client.get('/health/missing').status_code, 404)

    def test_absent_build_does_not_claim_to_serve_app(self):
        app = FastAPI()
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(mount_frontend(app, Path(directory)))

    def test_root_chunks_metadata_and_missing_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'index.html').write_text('<html>app</html>', encoding='utf-8')
            (root / 'umi.js').write_text('console.log("app")', encoding='utf-8')
            (root / 'page.async.js').write_text('export default {}', encoding='utf-8')
            (root / 'umi.css').write_text('body{margin:0}', encoding='utf-8')
            (root / 'build-info.json').write_text('{"version":"0.1.0"}', encoding='utf-8')
            app = FastAPI()
            mount_frontend(app, root)
            with TestClient(app) as client:
                script = client.get('/umi.js')
                self.assertIn('javascript', script.headers['content-type'])
                self.assertEqual(script.text, 'console.log("app")')
                self.assertIn('javascript', client.get('/page.async.js').headers['content-type'])
                self.assertIn('text/css', client.get('/umi.css').headers['content-type'])
                self.assertEqual(client.get('/build-info.json').json(), {'version': '0.1.0'})
                self.assertIn('no-cache', client.get('/build-info.json').headers['cache-control'])
                for path in ['/missing.js', '/nested/missing.woff2', '/auth/missing', '/api/missing', '/assets/missing']:
                    self.assertEqual(client.get(path).status_code, 404, path)
                self.assertIn('<html>app</html>', client.get('/employees/e1').text)

    def test_resources_cannot_escape_build_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / 'dist'
            root.mkdir()
            (root / 'index.html').write_text('<html>app</html>', encoding='utf-8')
            (parent / 'secret.txt').write_text('private', encoding='utf-8')
            app = FastAPI()
            mount_frontend(app, root)
            with TestClient(app) as client:
                self.assertEqual(client.get('/%2e%2e/secret.txt').status_code, 404)
                self.assertEqual(client.get('/..%5csecret.txt').status_code, 404)


if __name__ == '__main__':
    unittest.main()
