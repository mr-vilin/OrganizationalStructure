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


if __name__ == '__main__':
    unittest.main()
