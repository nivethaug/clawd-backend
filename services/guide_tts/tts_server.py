"""Tiny local TTS service for the DreamStudio guide: Piper (GPL, server side only) with the en_US-amy-medium voice.

Run with Piper's own venv:  /root/piper/venv/bin/python tts_server.py   (pm2 name: guide-tts, 127.0.0.1:8005)
POST /tts  {"text": "..."}  ->  audio/wav.   Not exposed publicly: clawd-backend proxies it (api/guide_router.py /tts) and rate limits.
"""
import io
import json
import os
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from piper import PiperVoice

MODEL = os.getenv("PIPER_MODEL", "/root/piper/voices/en_US-amy-medium.onnx")
voice = PiperVoice.load(MODEL)
lock = threading.Lock()  # one synthesis at a time (2 CPU cores shared with the API)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        if self.path != "/tts":
            self.send_error(404)
            return
        try:
            n = int(self.headers.get("Content-Length", "0"))
            text = str(json.loads(self.rfile.read(min(n, 4096)) or b"{}").get("text", "")).strip()[:400]
            if not text:
                self.send_error(400)
                return
            buf = io.BytesIO()
            with lock, wave.open(buf, "wb") as w:
                voice.synthesize_wav(text, w)
            data = buf.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:  # keep the service alive
            self.send_error(500, str(e)[:100])

    def do_GET(self):
        self.send_response(200 if self.path == "/health" else 404)
        self.end_headers()


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8005), H).serve_forever()
