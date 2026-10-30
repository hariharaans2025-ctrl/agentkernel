"""Loopback-only dashboard; keys remain in the Python controller."""
import argparse
import asyncio
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from agentkernel.config import load_env_file
from agentkernel.telemetry.redaction import redact
from .service import BusyError, DashboardService

ASSETS = Path(__file__).with_name('static')


def make_server(service, port=8766):
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, data, kind='application/json'):
            body = json.dumps(redact(data)).encode() if kind == 'application/json' else data
            self.send_response(status)
            self.send_header('Content-Type', kind + '; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def trusted_host(self):
            return self.headers.get('Host') in {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}

        def do_GET(self):
            if not self.trusted_host():
                self.send(403, {'error': 'Loopback access only'})
                return
            path = urlsplit(self.path).path
            try:
                if path == '/api/config':
                    self.send(200, {**service.configuration(), 'csrf': token})
                elif path == '/api/runs':
                    self.send(200, service.list_runs())
                elif path == '/api/v4':
                    self.send(200, service.v4_results())
                elif path == '/api/benchmark/combined':
                    report = service.root/'reports/combined-view-20261004/combined-benchmark.json'
                    self.send(200, json.loads(report.read_text(encoding='utf-8')) if report.exists() else {'status':'unavailable','rows':[]})
                elif path.startswith('/api/benchmark/events/'):
                    parts = path.split('/')
                    allowed = {item['id'] for item in service.configuration()['fixtures']}
                    if len(parts) != 6 or parts[4] not in ('nano_only','super_only','ultra_only','adaptive') or parts[5] not in allowed:
                        self.send(404, {'error':'Unknown benchmark job'})
                        return
                    mode, fixture = parts[4:]
                    root = service.root/'reports'
                    if mode in ('ultra_only','adaptive'):
                        root = root/'continuation-20261004T104857Z'
                    events = root/(fixture+'-'+mode+'.jsonl')
                    self.send(200, {'events':[json.loads(line) for line in events.read_text(encoding='utf-8').splitlines()] if events.exists() else []})
                elif path.startswith('/api/benchmark/source/'):
                    import hashlib
                    fixture = path.rsplit('/', 1)[-1]
                    allowed = {item['id'] for item in service.configuration()['fixtures']}
                    if fixture not in allowed:
                        self.send(404, {'error': 'Unknown fixture'})
                        return
                    source = service.root/'benchmarks'/fixture/'main.c'
                    data = source.read_bytes()
                    self.send(200, {'file':'main.c', 'source':data.decode('utf-8'), 'sha256':hashlib.sha256(data).hexdigest()})
                elif path == '/api/benchmark':
                    report = service.root/'reports/final-benchmark.json'
                    self.send(200, json.loads(report.read_text(encoding='utf-8')) if report.exists() else {'status':'not_run','rows':[]})
                elif path.startswith('/api/runs/'):
                    self.send(200, service.get(path.split('/')[-1]))
                elif path in ('/', '/app.js', '/style.css'):
                    name = 'index.html' if path == '/' else path[1:]
                    kind = {'index.html': 'text/html', 'app.js': 'text/javascript', 'style.css': 'text/css'}[name]
                    self.send(200, (ASSETS/name).read_bytes(), kind)
                else:
                    self.send(404, {'error': 'Not found'})
            except KeyError:
                self.send(404, {'error': 'Run not found'})

        def do_POST(self):
            origins = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
            if (not self.trusted_host() or self.headers.get('Origin') not in origins | {None}
                    or not secrets.compare_digest(self.headers.get('X-CSRF-Token',''), token)):
                self.send(403, {'error': 'Request rejected; reload the dashboard'})
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 4096:
                    raise ValueError('Invalid request size')
                request = json.loads(self.rfile.read(size))
                path = urlsplit(self.path).path
                if path == '/api/runs':
                    self.send(202, service.start(request))
                elif path == '/api/check':
                    self.send(200, asyncio.run(service.check_connection()))
                elif path.startswith('/api/runs/') and path.endswith('/stop'):
                    self.send(200, service.stop(path.split('/')[-2]))
                else:
                    self.send(404, {'error': 'Not found'})
            except BusyError as exc:
                self.send(409, {'error': str(exc)})
            except (ValueError, TypeError) as exc:
                self.send(400, {'error': str(exc)})
            except KeyError:
                self.send(404, {'error': 'Run not found'})
            except Exception:
                self.send(500, {'error': 'Controller error; no automatic retry was made'})

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def main():
    parser = argparse.ArgumentParser(description='AgentKernel comparison dashboard; execution stays in Nebius Sandbox')
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    root = args.root.resolve()
    env = args.env_file or root/'.env'
    if env.is_file():
        load_env_file(env)
    server = make_server(DashboardService(root), args.port)
    print(f'AgentKernel dashboard: http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
