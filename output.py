import csv
import glob
from datetime import datetime
from pathlib import Path

MAX_CSV_FILES = 300   # 일일 CSV 최대 보관 개수
HEADER = ["timestamp", "value", "Charging", "Discharging"]


class CSVWriter:
    """일일 단위로 output_YYYYMMDD.csv에 기록(value/Charging/Discharging).
    CSV 파일이 300개 넘으면 오래된 것부터 삭제."""

    def __init__(self, filepath):
        p = Path(filepath)
        self.dir = p.parent if str(p.parent) else Path(".")
        self.stem = p.stem
        self.suffix = p.suffix or ".csv"
        self._cur_date = None
        self._cur_path = None

    def _daily_path(self, dt):
        return self.dir / f"{self.stem}_{dt.strftime('%Y%m%d')}{self.suffix}"

    def _ensure(self, dt):
        d = dt.strftime("%Y%m%d")
        if d != self._cur_date:
            self._cur_date = d
            self._cur_path = self._daily_path(dt)
            if not self._cur_path.exists():
                with open(self._cur_path, "w", newline="") as f:
                    csv.writer(f).writerow(HEADER)
            self._prune()

    def _prune(self):
        files = sorted(self.dir.glob(f"{self.stem}_*{self.suffix}"))
        if len(files) > MAX_CSV_FILES:
            for old in files[:-MAX_CSV_FILES]:
                try:
                    old.unlink()
                    print(f"오래된 CSV 삭제: {old.name}")
                except OSError:
                    pass

    @staticmethod
    def _yn(v):
        if v is None:
            return ""
        return "Y" if v else "N"

    def write(self, timestamp, value, charging=None, discharging=None):
        """value: 'xx.x' 문자열(또는 리스트). charging/discharging: bool."""
        if isinstance(value, (list, tuple)):
            value = ",".join(value)
        dt = datetime.fromtimestamp(timestamp)
        self._ensure(dt)
        ts_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        with open(self._cur_path, "a", newline="") as f:
            csv.writer(f).writerow([ts_str, value, self._yn(charging), self._yn(discharging)])
        print(f"[{ts_str}] {value} (C={self._yn(charging)} D={self._yn(discharging)})")
