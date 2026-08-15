import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread

class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(b'Bot is alive and running!\n')

    # Suppress default request logging to keep the console clean
    def log_message(self, format, *args):
        return

def run_server():
    # Render automatically sets the PORT environment variable
    port = int(os.environ.get('PORT', 8080))
    server = HTTPServer(('0.0.0.0', port), KeepAliveHandler)
    print(f"[KeepAlive] Web server listening on port {port}")
    server.serve_forever()

def keep_alive():
    server_thread = Thread(target=run_server, daemon=True)
    server_thread.start()
