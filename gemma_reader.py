"""
production gemma 비전 판독기: 크롭을 원격 ollama 서버(gemma4:e4b)로 보내
7-seg 값 + 아이콘 상태(Charging=태양광패널, Discharging=전구)를 읽음.
크롭 JPEG를 stdin으로 SSH 전달 → 서버에서 base64+ollama 호출 → JSON 반환.
"""
import subprocess
import shlex
import re
import json
import cv2

import os
# 접속 정보는 git에서 제외된 gemma_secret.py 또는 환경변수에서 로드
try:
    from gemma_secret import SSH_HOST, SSH_PORT
except ImportError:
    SSH_HOST = os.environ.get("GEMMA_SSH_HOST", "user@host")
    SSH_PORT = os.environ.get("GEMMA_SSH_PORT", "22")
BLANK_STD = 6.0   # 그레이 std 이하면 빈 화면으로 보고 기권

PROMPT = (
    "This is a solar charge controller LCD. Answer with JSON only, no markdown. "
    "Format: {\"voltage\":\"the big 7-segment number as xx.x\","
    "\"charging\":true or false (a solar panel grid icon at the BOTTOM-LEFT is shown),"
    "\"discharging\":true or false (a light bulb icon at the BOTTOM-RIGHT is shown)}. "
    "If no clear 7-segment number is visible (blank or off screen), set voltage to an empty string."
)

# 서버에서 실행될 파이썬: stdin(JPEG) → base64 → ollama → response 출력
_REMOTE_PY = (
    "import sys,base64,json,urllib.request;"
    "b64=base64.b64encode(sys.stdin.buffer.read()).decode();"
    "req={'model':'gemma4:e4b','prompt':" + repr(PROMPT) + ",'images':[b64],"
    "'stream':False,'options':{'temperature':0}};"
    "r=urllib.request.urlopen('http://127.0.0.1:11434/api/generate',"
    "json.dumps(req).encode(),timeout=60);"
    "print(json.loads(r.read())['response'].strip())"
)

_VAL_RE = re.compile(r'(\d{1,2}\.\d)')
_OBJ_RE = re.compile(r'\{.*\}', re.S)


class GemmaReader:
    def __init__(self, host=SSH_HOST, port=SSH_PORT):
        self.cmd = ["ssh", host, "-p", port,
                    "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
                    "-o", "StrictHostKeyChecking=accept-new",
                    "python3 -c " + shlex.quote(_REMOTE_PY)]

    def read_frame(self, frame):
        """단일 프레임 → (값 'xx.x', {'charging':bool,'discharging':bool}) 또는 (None, {})"""
        # 빈/저대비 화면(디스플레이 꺼짐 등) → 즉시 기권 (gemma 환각·오기록 방지)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        if gray.std() < BLANK_STD:
            return None, {}
        ok, jpg = cv2.imencode(".jpg", frame)
        if not ok:
            return None, {}
        try:
            p = subprocess.run(self.cmd, input=jpg.tobytes(),
                               capture_output=True, timeout=75)
        except subprocess.TimeoutExpired:
            return None, {}
        out = p.stdout.decode(errors="ignore")
        m = _OBJ_RE.search(out)
        if not m:
            return None, {}
        try:
            d = json.loads(m.group(0))
        except Exception:
            return None, {}
        vm = _VAL_RE.search(str(d.get("voltage", "")))
        if not vm:
            return None, {}
        info = {"charging": bool(d.get("charging")),
                "discharging": bool(d.get("discharging"))}
        return vm.group(0), info

    def read_voted(self, frames):
        """gemma는 느리니 최신 1프레임만 사용."""
        if not frames:
            return None, 0, 0
        s, _ = self.read_frame(frames[-1])
        return (s, 1, 1) if s else (None, 0, 1)

    def extract_numbers(self, frame):
        s, _ = self.read_frame(frame)
        return [s] if s else []


if __name__ == "__main__":
    import sys
    r = GemmaReader()
    print(r.read_frame(cv2.imread(sys.argv[1])))
