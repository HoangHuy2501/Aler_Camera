"""Local helper for a one-time OAuth exchange; not a web application route."""
import argparse
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        request = urlsplit(self.path)
        if request.path != self.server.callback_path:
            self.send_error(404)
            return
        values = parse_qs(request.query)
        code = values.get("code", [""])[0]
        if code and len(code) <= 4096 and code.isprintable():
            print(f"OAuth code: {code}", flush=True)

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(b"Callback received. Check the local terminal for the authorization code.")

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Nhận mã Imou OAuth để thử kết nối.")
    parser.add_argument("--path", required=True, help="Đường dẫn callback bí mật, bắt đầu bằng '/'.")
    args = parser.parse_args()
    if not re.fullmatch(r"/[A-Za-z0-9_-]{24,100}", args.path):
        parser.error("Đường dẫn cần có ít nhất 24 ký tự chữ, số, gạch ngang hoặc gạch dưới.")
    with HTTPServer(("127.0.0.1", 8765), CallbackHandler) as server:
        server.callback_path = args.path
        print("Đang chờ mã OAuth tại http://127.0.0.1:8765", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
