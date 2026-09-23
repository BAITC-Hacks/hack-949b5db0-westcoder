import argparse
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from .dataset import Dataset, ROOT, DEFAULT_DATASET
from .demos import build_demos
from .models import ValidationError
from .semantic import SemanticMatcher
from .service import RecommendationService


def load_env():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def make_server(host="127.0.0.1", port=8000, service=None):
    service = service or RecommendationService()
    metadata = service.dataset.metadata()
    metadata["demos"] = build_demos(service.dataset)
    static = {"/": ("index.html", "text/html"), "/styles.css": ("styles.css", "text/css"),
              "/app.js": ("app.js", "text/javascript"), "/favicon.svg": ("favicon.svg", "image/svg+xml")}

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def send(self, code, body, content_type="application/json"):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/api/health":
                return self.send(200, {"status": "ok", "profiles": metadata["total"]})
            if path == "/api/meta":
                return self.send(200, metadata)
            if path in static:
                filename, mime = static[path]
                return self.send(200, (ROOT / "frontend" / filename).read_bytes(), mime)
            return self.send(404, {"error": "Не найдено."})

        def do_POST(self):
            if urlsplit(self.path).path != "/api/recommend":
                return self.send(404, {"error": "Не найдено."})
            if self.headers.get_content_type() != "application/json":
                return self.send(415, {"error": "Нужен Content-Type: application/json."})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 16384:
                    return self.send(413, {"error": "Размер запроса должен быть от 1 до 16384 байт."})
                payload = json.loads(self.rfile.read(size))
                self.send(200, service.recommend(payload))
            except ValidationError as error:
                self.send(422, {"error": str(error), "fields": error.errors})
            except (ValueError, UnicodeError):
                self.send(400, {"error": "Некорректный JSON."})
            except Exception:
                logging.exception("Recommendation request failed")
                self.send(500, {"error": "Не удалось выполнить подбор. Повторите запрос."})

    return ThreadingHTTPServer((host, port), Handler)


def main():
    load_env()
    parser = argparse.ArgumentParser(description="EventMatch MVP")
    parser.add_argument("--host", default=os.getenv("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    args = parser.parse_args()
    dataset = Dataset(os.getenv("DATASET_PATH", str(DEFAULT_DATASET)))
    semantic = SemanticMatcher(os.getenv("CACHE_DIR", str(ROOT / ".cache")),
                               enabled=os.getenv("ENABLE_EMBEDDINGS", "false").lower() == "true")
    server = make_server(args.host, args.port, RecommendationService(dataset, semantic))
    print(f"EventMatch: http://{args.host}:{args.port} | {len(dataset.contractors)} profiles", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
