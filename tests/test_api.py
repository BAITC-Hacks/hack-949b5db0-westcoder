import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from backend.server import make_server


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(port=0)
        cls.thread = threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, path, body=None, content_type="application/json"):
        data = None if body is None else body if isinstance(body,bytes) else json.dumps(body).encode()
        request = Request(self.base + path,data=data,headers={"Content-Type":content_type})
        try:
            with urlopen(request,timeout=5) as response:
                return response.status, response.read(), response.headers
        except HTTPError as error:
            with error:
                return error.code,error.read(),error.headers

    def test_metadata_and_recommendation(self):
        status, raw, _ = self.request('/api/meta')
        self.assertEqual(status,200)
        meta = json.loads(raw)
        self.assertEqual(meta['total'],66)
        status, raw, _ = self.request('/api/recommend',meta['demos'][0]['request'])
        self.assertEqual(status,200)
        self.assertEqual(len(json.loads(raw)['recommendations']),3)

    def test_invalid_requests(self):
        for body, expected in (({},422),(None,404),(b'{broken',400),([],422),(b'x'*17000,413)):
            self.assertEqual(self.request('/api/recommend',body)[0],expected)
        self.assertEqual(self.request('/api/recommend',{},'text/plain')[0],415)

    def test_extreme_input_does_not_return_500(self):
        meta = json.loads(self.request('/api/meta')[1])
        payload = {**meta['demos'][0]['request'], 'budget_kzt':10**400}
        self.assertEqual(self.request('/api/recommend',payload)[0],422)
        self.assertIn(self.request('/api/recommend',b'['*1500 + b']'*1500)[0], (400,422))

    def test_only_frontend_files_are_public(self):
        for path in ('/.env','/data/contractors.csv','/backend/server.py','/../README.md','/.git/config'):
            self.assertEqual(self.request(path)[0],404)
        for path in ('/','/app.js','/styles.css','/favicon.svg'):
            status, body, headers = self.request(path)
            self.assertEqual(status,200)
            self.assertGreater(len(body),0)
            self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])


if __name__ == '__main__':
    unittest.main()
