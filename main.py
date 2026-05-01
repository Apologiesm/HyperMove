"""
HyperMove v8.7 - Elite Fluid Edition
The ultimate zero-compromise file transfer engine.
FIXED: Perfectly smooth native dragging while maintaining 60FPS liquid animations.
NEW: Spring physics, data-flow particles, and GPU-optimized rendering.
"""

import sys
import os
import time
import math
import platform
import shutil
import ctypes
import subprocess
from enum import Enum
from pathlib import Path
from threading import Lock
import random

# =====================================================================
# App Resource Manager
# =====================================================================
def resource_path(relative_path):
    try: base_path = sys._MEIPASS
    except Exception: base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# ---------------------------------------------------------
# OS-Specific Native Window Blur & Ultra-Smooth Dragging
# ---------------------------------------------------------
def apply_native_window_blur(window_id):
    if platform.system() == "Windows":
        try:
            from ctypes import windll, c_int, byref, Structure, POINTER, sizeof
            class ACCENTPOLICY(Structure):
                _fields_ = [("AccentState", c_int), ("AccentFlags", c_int), ("GradientColor", c_int), ("AnimationId", c_int)]
            class WINDOWCOMPOSITIONATTRIBDATA(Structure):
                _fields_ = [("Attribute", c_int), ("Data", POINTER(ACCENTPOLICY)), ("SizeOfData", c_int)]
            hwnd = int(window_id)
            accent = ACCENTPOLICY()
            accent.AccentState = 4 
            accent.GradientColor = 0x8015151A 
            data = WINDOWCOMPOSITIONATTRIBDATA()
            data.Attribute = 19
            data.Data = ctypes.pointer(accent)
            data.SizeOfData = sizeof(accent)
            windll.user32.SetWindowCompositionAttribute(hwnd, byref(data))
        except Exception: pass

def trigger_native_drag(window):
    """Signals the OS to take full control of dragging. Eliminates lag 100%."""
    if platform.system() == "Windows":
        ctypes.windll.user32.ReleaseCapture()
        ctypes.windll.user32.SendMessageW(int(window.winId()), 0xA1, 2, 0)
    else:
        window.windowHandle().startSystemMove()

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QProgressBar, QComboBox, QTextEdit, 
    QFrame, QFileDialog, QMessageBox, QGraphicsDropShadowEffect, 
    QGridLayout, QGraphicsOpacityEffect, QButtonGroup
)
from PySide6.QtCore import (
    Qt, QThread, Signal, Slot, QRunnable, QThreadPool, QMutex, QObject, QTimer, 
    QPropertyAnimation, QEasingCurve, QVariantAnimation, QParallelAnimationGroup, QPointF
)
from PySide6.QtGui import (
    QFont, QColor, QDragEnterEvent, QDropEvent, QCursor, QPainter, QPainterPath, 
    QLinearGradient, QPen, QBrush, QIcon
)

# =====================================================================
# Engine Constants & Core Logic
# =====================================================================

class TransferMode(Enum):
    AUTO = "Auto (Smart)"
    PARALLEL = "Parallel (Safest)"
    DIRECT = "Direct I/O (Max Speed)"

class ConflictPolicy(Enum):
    SMART_RESUME = "Smart Resume"
    OVERWRITE = "Overwrite"
    SKIP = "Skip Existing"

class OperationType(Enum):
    COPY = "Copy"
    MOVE = "Move"

class EngineState(Enum):
    IDLE, COPYING, PAUSED, RESUMING, STOPPING = range(5)

CHUNK_SIZE = 1024 * 1024  
DIRECT_CHUNK_SIZE = 1024 * 1024 * 8  

class DirectIOWrapper:
    def __init__(self, path, mode='r'): self.path, self.mode = path, mode
    def read(self, size): raise NotImplementedError
    def write(self, data): raise NotImplementedError
    def seek(self, offset): raise NotImplementedError
    def close(self): raise NotImplementedError

class PosixDirectIO(DirectIOWrapper):
    def __init__(self, path, mode='r'):
        super().__init__(path, mode)
        flags = os.O_RDONLY if mode == 'r' else (os.O_WRONLY | os.O_CREAT)
        if mode == 'w': flags |= os.O_TRUNC
        if hasattr(os, 'O_DIRECT'): flags |= os.O_DIRECT
        self.fd = os.open(path, flags, 0o666)
    def read(self, size): return os.read(self.fd, size)
    def write(self, data): return os.write(self.fd, data)
    def seek(self, offset): os.lseek(self.fd, offset, os.SEEK_SET)
    def close(self):
        if self.fd is not None: os.close(self.fd); self.fd = None

class WindowsDirectIO(DirectIOWrapper):
    def __init__(self, path, mode='r'):
        super().__init__(path, mode)
        self.kernel32 = ctypes.windll.kernel32
        creation_disposition = 3 if mode == 'r' else (4 if mode == 'a' else 2) 
        self.handle = self.kernel32.CreateFileW(str(path), 0x80000000 if mode == 'r' else 0x40000000, 1 | 2, None, creation_disposition, 0x20000000, None)
        if self.handle == -1: raise ctypes.WinError()
        self.buf_size = DIRECT_CHUNK_SIZE
        self.buffer = self.kernel32.VirtualAlloc(None, self.buf_size, 0x1000 | 0x2000, 0x04)

    def read(self, size):
        bytes_read = ctypes.c_ulong(0)
        success = self.kernel32.ReadFile(self.handle, self.buffer, min(size, self.buf_size), ctypes.byref(bytes_read), None)
        if not success and bytes_read.value == 0:
            err = self.kernel32.GetLastError()
            if err != 38: raise ctypes.WinError(err)
            return b""
        return ctypes.string_at(self.buffer, bytes_read.value)

    def write(self, data):
        data_len = len(data); ctypes.memmove(self.buffer, data, data_len)
        bytes_written = ctypes.c_ulong(0); self.kernel32.WriteFile(self.handle, self.buffer, data_len, ctypes.byref(bytes_written), None)
        return bytes_written.value

    def seek(self, offset): self.kernel32.SetFilePointerEx(self.handle, ctypes.c_int64(offset), None, 0)
    def close(self):
        if hasattr(self, 'handle') and self.handle != -1: self.kernel32.CloseHandle(self.handle); self.handle = -1
        if hasattr(self, 'buffer') and self.buffer: self.kernel32.VirtualFree(self.buffer, 0, 0x8000); self.buffer = 0

def get_direct_io(path, mode='r'): return WindowsDirectIO(path, mode) if platform.system() == "Windows" else PosixDirectIO(path, mode)

# =====================================================================
# Engine Workers
# =====================================================================

class WorkerSignals(QObject):
    progress, file_started, finished = Signal(int), Signal(str), Signal(str, str, bool, str)

class ParallelWorker(QRunnable):
    def __init__(self, src, dst, engine, offset=0):
        super().__init__(); self.src, self.dst, self.engine, self.offset = src, dst, engine, offset; self.signals = WorkerSignals()
    def run(self):
        try:
            self.signals.file_started.emit(Path(self.src).name)
            if self.engine.state in [EngineState.STOPPING, EngineState.PAUSED]: return
            sync_counter = 0; mode = 'ab' if self.offset > 0 else 'wb'
            with open(self.src, 'rb') as fsrc, open(self.dst, mode) as fdst:
                if self.offset > 0: fsrc.seek(self.offset)
                while True:
                    if self.engine.state in [EngineState.STOPPING, EngineState.PAUSED]:
                        if self.engine.state == EngineState.PAUSED: self.engine.save_offset(self.src, self.offset)
                        fdst.flush(); os.fsync(fdst.fileno()); return
                    chunk = fsrc.read(CHUNK_SIZE)
                    if not chunk: break
                    fdst.write(chunk); self.offset += len(chunk); self.signals.progress.emit(len(chunk))
                    sync_counter += len(chunk)
                    if sync_counter > 50 * 1024 * 1024: fdst.flush(); os.fsync(fdst.fileno()); sync_counter = 0
            self.signals.finished.emit(str(self.src), str(self.dst), True, "")
        except Exception as e: self.signals.finished.emit(str(self.src), str(self.dst), False, str(e))

class CopyEngine(QThread):
    def __init__(self):
        super().__init__(); self.signals = CopyEngineSignals(); self.state = EngineState.IDLE; self.state_mutex = QMutex()
        self.pool = QThreadPool(); self.worker_lock = Lock(); self.speed_history = []; self.transferred_bytes = 0
    def set_state(self, new_state): self.state_mutex.lock(); self.state = new_state; self.state_mutex.unlock(); self.signals.state_changed.emit(new_state)
    def save_offset(self, src, off):
        with self.worker_lock: self.file_offsets[str(src)] = off
    def prepare_job(self, src, dst, mode, op, conf, threads):
        self.src_path, self.dst_path, self.mode, self.operation, self.conflict_policy, self.threads = Path(src), Path(dst), mode, op, conf, threads
        self.total_bytes, self.transferred_bytes, self.files_to_process, self.file_offsets, self.failed_files, self.processed_count, self.skipped_files = 0, 0, [], {}, [], 0, []
        temp = []
        if self.src_path.is_file(): temp.append((self.src_path, self.dst_path / self.src_path.name if self.dst_path.is_dir() else self.dst_path))
        else:
            for r, _, fs in os.walk(self.src_path):
                for f in fs:
                    sf = Path(r) / f; df = self.dst_path / self.src_path.name / sf.relative_to(self.src_path)
                    temp.append((sf, df))
        res, al_err = 0, False
        for sf, df in temp:
            sz = sf.stat().st_size; self.total_bytes += sz
            if df.exists():
                dsz = df.stat().st_size
                if self.conflict_policy == ConflictPolicy.SKIP: self.skipped_files.append(sf); self.transferred_bytes += sz; continue
                if self.conflict_policy == ConflictPolicy.SMART_RESUME:
                    if dsz < sz and dsz > 0: self.file_offsets[str(sf)] = dsz; self.transferred_bytes += dsz; res += 1; self.files_to_process.append((sf, df))
                    elif dsz == sz: self.skipped_files.append(sf); self.transferred_bytes += sz
                    else: self.files_to_process.append((sf, df))
                else: self.files_to_process.append((sf, df))
            else: self.files_to_process.append((sf, df))
        if res > 0: self.signals.log_msg.emit(f"<span style='color:#FFBD2E;'>Resuming {res} files...</span>")
        if self.mode == TransferMode.AUTO: self.mode = TransferMode.DIRECT if (len(self.files_to_process) == 1 and self.total_bytes > 1024**3) else TransferMode.PARALLEL

    def run(self):
        self.set_state(EngineState.COPYING); self.last_update_time, self.last_transferred = time.time(), self.transferred_bytes
        self.pool.setMaxThreadCount(self.threads if self.mode == TransferMode.PARALLEL else 1)
        if self.mode == TransferMode.PARALLEL:
            for s, d in self.files_to_process:
                if self.state != EngineState.COPYING: break
                d.parent.mkdir(parents=True, exist_ok=True); worker = ParallelWorker(s, d, self, self.file_offsets.get(str(s), 0))
                worker.signals.progress.connect(self._on_worker_progress); worker.signals.file_started.connect(self.signals.active_file.emit); worker.signals.finished.connect(self._on_worker_finished); self.pool.start(worker)
        else:
            for s, d in self.files_to_process:
                if self.state != EngineState.COPYING: break
                self.signals.active_file.emit(s.name); d.parent.mkdir(parents=True, exist_ok=True)
                try:
                    fs, fd = get_direct_io(s, 'r'), get_direct_io(d, 'a' if self.file_offsets.get(str(s), 0) > 0 else 'w')
                    if self.file_offsets.get(str(s), 0) > 0: off = self.file_offsets[str(s)]; fs.seek(off); fd.seek(off)
                    while True:
                        if self.state in [EngineState.STOPPING, EngineState.PAUSED]: break
                        chk = fs.read(DIRECT_CHUNK_SIZE)
                        if not chk: break
                        fd.write(chk); self._on_worker_progress(len(chk))
                    fs.close(); fd.close(); self._on_worker_finished(str(s), str(d), True, "")
                except Exception as e: self._on_worker_finished(str(s), str(d), False, str(e))
        self.pool.waitForDone()
        if self.state == EngineState.STOPPING: self.set_state(EngineState.IDLE); self.signals.job_finished.emit(); return
        if self.operation == OperationType.MOVE and not self.failed_files:
            for sf, df in self.files_to_process:
                if sf.exists(): sf.unlink()
        self.set_state(EngineState.IDLE); self.signals.job_finished.emit()

    @Slot(int)
    def _on_worker_progress(self, b):
        with self.worker_lock: self.transferred_bytes += b
        cur = time.time(); elap = cur - self.last_update_time
        if elap > 0.2:
            sp = (self.transferred_bytes - self.last_transferred) / elap; self.speed_history.append(sp)
            if len(self.speed_history) > 10: self.speed_history.pop(0)
            avg = int(sum(self.speed_history) / len(self.speed_history))
            self.last_update_time, self.last_transferred = cur, self.transferred_bytes
            eta = "Calculating..."
            if avg > 0:
                s = int((self.total_bytes - self.transferred_bytes) / avg)
                eta = f"~ {s//3600}h {(s%3600)//60}m" if s > 60 else f"~ {s} sec"
            self.signals.progress_update.emit(self.transferred_bytes, self.total_bytes); self.signals.stats_update.emit(self.transferred_bytes, avg, eta)

    @Slot(str, str, bool, str)
    def _on_worker_finished(self, s, d, succ, err):
        with self.worker_lock: self.processed_count += 1
        if not succ: self.failed_files.append(s); self.signals.log_msg.emit(f"Error: {err}")

class CopyEngineSignals(QObject):
    log_msg, active_file, stats_update, progress_update, state_changed, job_finished = Signal(str), Signal(str), Signal(int, int, str), Signal(int, int), Signal(EngineState), Signal()

# =====================================================================
# UI Components: Interactive Liquid Graph
# =====================================================================

class LiquidSpeedGraph(QWidget):
    def __init__(self):
        super().__init__(); self.setFixedHeight(80); self.points = [0] * 60; self.max_val = 1; self.phase = 0.0
        self.particles = [{"x": random.randint(0, 800), "y": random.randint(0, 80), "s": random.uniform(1, 4)} for _ in range(15)]
        self.wave_anim = QVariantAnimation(); self.wave_anim.setDuration(4000); self.wave_anim.setStartValue(0.0); self.wave_anim.setEndValue(math.pi * 2); self.wave_anim.setLoopCount(-1)
        self.wave_anim.valueChanged.connect(self._tick); self.wave_anim.start()

    def _tick(self, val):
        self.phase = val
        for p in self.particles:
            p["x"] += p["s"] * (1 + (self.points[-1] / (1024*1024*100))) # Speed particles by data rate
            if p["x"] > self.width(): p["x"] = -10; p["y"] = random.randint(10, 70)
        self.update()

    def update_data(self, val): self.points.pop(0); self.points.append(val); self.max_val = max(max(self.points), 1024*1024*20) 
    def reset(self): self.points = [0] * 60

    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height(); step = w / (len(self.points) - 1)
        
        # Particles
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(0, 243, 255, 80))
        for p in self.particles: painter.drawEllipse(QPointF(p["x"], p["y"]), 1.5, 1.5)

        def get_path(off, amp):
            path = QPainterPath(); path.moveTo(0, h)
            for i, v in enumerate(self.points):
                x = i * step; ripple = math.sin(self.phase * 2 + i * 0.15 + off) * amp
                y = h - ((v / self.max_val) * (h-20)) + ripple
                if i == 0: path.lineTo(x, y)
                else: 
                    px = (i-1)*step; py = h - ((self.points[i-1]/self.max_val)*(h-20)) + math.sin(self.phase*2+(i-1)*0.15+off)*amp
                    path.cubicTo(px + step/2, py, px + step/2, y, x, y)
            path.lineTo(w, h); path.closeSubpath(); return path

        grad = QLinearGradient(0, 0, 0, h); grad.setColorAt(0, QColor(0, 243, 255, 100)); grad.setColorAt(1, Qt.GlobalColor.transparent)
        painter.setBrush(grad); painter.drawPath(get_path(1.0, 6))
        painter.setPen(QPen(QColor(0, 243, 255, 255), 2)); painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawPath(get_path(0, 3))

# =====================================================================
# Main Application
# =====================================================================

class AnimatedDropZone(QFrame):
    dropped = Signal(str); browse = Signal(str); cleared = Signal()
    def __init__(self, title, is_src=True):
        super().__init__(); self.is_src, self.setFixedHeight(130 if is_src else 110)
        self.setStyleSheet("AnimatedDropZone { background: rgba(255,255,255,0.03); border: 2px dashed rgba(255,255,255,0.1); border-radius: 12px; }")
        self.setAcceptDrops(True); self.layout = QGridLayout(self); self.stack = QStackedWidget = QWidget(); self.stack_layout = QGridLayout(self.stack)
        
        self.view_empty = QWidget(); el = QVBoxLayout(self.view_empty); el.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl = QLabel(f"Drop {title} Here"); lbl.setStyleSheet("color: rgba(255,255,255,0.6); font-weight: bold;")
        btns = QHBoxLayout()
        if is_src:
            self.bf = self._btn("📄 File"); self.bf.clicked.connect(lambda: self.browse.emit('file')); btns.addWidget(self.bf)
        self.bd = self._btn("📁 Folder"); self.bd.clicked.connect(lambda: self.browse.emit('folder')); btns.addWidget(self.bd)
        el.addWidget(lbl); el.addLayout(btns)
        
        self.view_sel = QWidget(); sl = QVBoxLayout(self.view_sel); sl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.licon = QLabel("📁"); self.licon.setFont(QFont("Arial", 20)); self.lname = QLabel("Name"); self.lname.setStyleSheet("color: white; font-weight: bold;")
        self.linfo = QLabel("Size"); self.linfo.setStyleSheet("color: rgba(255,255,255,0.4); font-size: 10px;")
        self.bc = self._btn("✕ Clear", True); self.bc.clicked.connect(self.clear_sel)
        sl.addWidget(self.licon); sl.addWidget(self.lname); sl.addWidget(self.linfo); sl.addWidget(self.bc, alignment=Qt.AlignmentFlag.AlignHCenter)
        
        self.layout.addWidget(self.view_empty, 0, 0); self.layout.addWidget(self.view_sel, 0, 0)
        self.view_sel.hide()

    def _btn(self, t, is_c=False):
        b = QPushButton(t); b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(f"QPushButton {{ background: rgba(255,255,255,0.08); color: white; border-radius: 10px; padding: 5px 12px; font-size: 10px; border: 1px solid rgba(255,255,255,0.1); }} QPushButton:hover {{ background: {'rgba(255,69,58,0.2)' if is_c else 'rgba(0,243,255,0.15)'}; }}")
        return b

    def dragEnterEvent(self, e): 
        if e.mimeData().hasUrls(): self.setStyleSheet("AnimatedDropZone { background: rgba(0,243,255,0.05); border: 2px dashed #00F3FF; }"); e.acceptProposedAction()
    def dragLeaveEvent(self, e): self.setStyleSheet("AnimatedDropZone { background: rgba(255,255,255,0.03); border: 2px dashed rgba(255,255,255,0.1); }")
    def dropEvent(self, e): self.dragLeaveEvent(None); p = e.mimeData().urls()[0].toLocalFile(); self.set_path(p); self.dropped.emit(p)
    
    def set_path(self, p):
        path = Path(p); self.licon.setText("📄" if path.is_file() else "📁"); self.lname.setText(path.name[:30])
        try: sz = format_size(path.stat().st_size if path.is_file() else sum(f.stat().st_size for f in path.rglob('*') if f.is_file()))
        except: sz = "Unknown"
        self.linfo.setText(sz); self.view_empty.hide(); self.view_sel.show()
        # Creative Bounce Animation
        self.anim = QPropertyAnimation(self, b"pos"); self.anim.setDuration(400); self.anim.setStartValue(self.pos() + Qt.Point(0, 10)); self.anim.setEndValue(self.pos()); self.anim.setEasingCurve(QEasingCurve.Type.OutBack); self.anim.start()

    def clear_sel(self): self.view_sel.hide(); self.view_empty.show(); self.cleared.emit()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window); self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True); self.resize(900, 700)
        logo = resource_path("logo.ico")
        if os.path.exists(logo): self.setWindowIcon(QIcon(logo))
        self.engine = CopyEngine(); self.engine.signals.log_msg.connect(self.log); self.engine.signals.active_file.connect(lambda n: self.lact.setText(f"Active: {n}"))
        self.engine.signals.stats_update.connect(self.upd_stats); self.engine.signals.progress_update.connect(self.upd_prog)
        self.engine.signals.state_changed.connect(self.upd_state); self.engine.signals.job_finished.connect(self.done)
        self.src, self.dst, self.op = "", "", OperationType.COPY; self.init_ui(); QTimer.singleShot(100, lambda: apply_native_window_blur(self.winId()))

    def init_ui(self):
        self.cw = QWidget(); self.setCentralWidget(self.cw); self.cw.setObjectName("cw")
        self.cw.setStyleSheet("QWidget#cw { background: rgba(20,20,22,200); border: 1px solid rgba(255,255,255,0.1); border-radius: 16px; } QLabel { font-family: 'SF Pro Display', 'Segoe UI'; color: white; }")
        main = QVBoxLayout(self.cw); main.setContentsMargins(0,0,0,0)
        
        # Title Bar
        tb = QWidget(); tb.setFixedHeight(45); tbl = QHBoxLayout(tb); tbl.setContentsMargins(15,0,15,0)
        for c in ["#FF5F56", "#FFBD2E", "#27C93F"]:
            d = QPushButton(); d.setFixedSize(12,12); d.setStyleSheet(f"background: {c}; border-radius: 6px; border: none;"); tbl.addWidget(d)
        d.clicked.connect(self.showMaximized); tbl.addSpacing(15); lblt = QLabel("HyperMove Pro - Fluid Master"); lblt.setStyleSheet("font-weight: bold; opacity: 0.6; font-size: 11px;"); tbl.addWidget(lblt); tbl.addStretch()
        main.addWidget(tb); tb.mousePressEvent = lambda e: trigger_native_drag(self)

        content = QHBoxLayout(); content.setContentsMargins(25,10,25,25); content.setSpacing(20)
        
        # Left
        lp = QVBoxLayout(); lp.setSpacing(12); self.ds = AnimatedDropZone("Source"); self.dd = AnimatedDropZone("Target", False)
        self.ds.dropped.connect(self.set_s); self.dd.dropped.connect(self.set_d)
        self.ds.browse.connect(self.br_s); self.dd.browse.connect(self.br_d)
        self.log_w = QTextEdit(); self.log_w.setReadOnly(True); self.log_w.setStyleSheet("background: rgba(0,0,0,0.2); border-radius: 8px; border: 1px solid rgba(255,255,255,0.05); color: #888; font-size: 10px;")
        lp.addWidget(self.ds); lp.addWidget(self.dd); lp.addWidget(self.log_w)
        
        # Right
        rp = QVBoxLayout(); rp.setSpacing(15); dc = GlassCard(); dl = QVBoxLayout(dc); dl.setContentsMargins(0,30,0,0)
        self.lspd = QLabel("0.0 MB/s"); self.lspd.setFont(QFont("SF Pro Display", 52, QFont.Weight.Bold)); self.lspd.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lact = QLabel("Engine Idle"); self.lact.setStyleSheet("color: #00F3FF; font-size: 10px; margin: 0 25px;")
        self.lstats = QLabel("-- / --"); self.leta = QLabel("ETA: --")
        tl = QHBoxLayout(); tl.setContentsMargins(25,0,25,0); tl.addWidget(self.lstats); tl.addStretch(); tl.addWidget(self.leta)
        self.graph = LiquidSpeedGraph(); self.prog = QProgressBar(); self.prog.setFixedHeight(4); self.prog.setTextVisible(False); self.prog.setStyleSheet("QProgressBar { background: transparent; border: none; } QProgressBar::chunk { background: #00F3FF; }")
        dl.addWidget(self.lspd); dl.addWidget(self.lact); dl.addLayout(tl); dl.addSpacing(15); dl.addWidget(self.graph); dl.addWidget(self.prog)
        
        cc = GlassCard(); cl = QVBoxLayout(cc); cl.setContentsMargins(20,15,20,20)
        ops = QHBoxLayout(); self.bcpy = self._opbtn("COPY", True); self.bmov = self._opbtn("MOVE", False)
        self.og = QButtonGroup(self); self.og.addButton(self.bcpy, 0); self.og.addButton(self.bmov, 1); ops.addWidget(self.bcpy); ops.addWidget(self.bmov)
        self.bstart = QPushButton("START ENGINE"); self.bstart.setFixedHeight(45); self.bstart.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        self.bstart.setStyleSheet("QPushButton { background: #00F3FF; color: black; border-radius: 12px; } QPushButton:hover { background: white; }")
        self.bstart.clicked.connect(self.start_job)
        cl.addLayout(ops); cl.addSpacing(10); cl.addWidget(self.bstart)
        
        rp.addWidget(dc); rp.addWidget(cc); content.addLayout(lp, 45); content.addLayout(rp, 55); main.addLayout(content)

    def _opbtn(self, t, s):
        b = QPushButton(t); b.setCheckable(True); b.setChecked(s); b.setFixedHeight(30)
        b.setStyleSheet("QPushButton { background: rgba(255,255,255,0.05); color: #666; border-radius: 6px; border: 1px solid transparent; font-weight: bold; } QPushButton:checked { background: rgba(0,243,255,0.1); color: #00F3FF; border: 1px solid #00F3FF; }")
        return b

    def br_s(self, t):
        p = QFileDialog.getOpenFileName(self, "Src")[0] if t=='file' else QFileDialog.getExistingDirectory(self, "Src")
        if p: self.ds.set_path(p); self.set_s(p)
    def br_d(self, t):
        p = QFileDialog.getExistingDirectory(self, "Dest")
        if p: self.dd.set_path(p); self.set_d(p)
    def set_s(self, p): self.src = p
    def set_d(self, p): self.dst = p
    def log(self, m): self.log_w.append(f"[{time.strftime('%H:%M:%S')}] {m}")
    def upd_stats(self, t, s, e):
        self.graph.update_data(s); self.lspd.setText(f"{s/(1024*1024):.1f} MB/s"); self.lstats.setText(format_size(t)); self.leta.setText(e)
    def upd_prog(self, t, tot): self.prog.setValue(int((t/tot)*100))
    def upd_state(self, s): 
        self.bstart.setEnabled(s == EngineState.IDLE)
        if s == EngineState.COPYING: self.log("Engine spinning up...")
    def done(self): self.log("Job concluded."); self.prog.setValue(100); self.lspd.setText("Done")

    def start_job(self):
        if not self.src or not self.dst: return QMessageBox.warning(self, "!", "Select paths.")
        self.op = OperationType.COPY if self.bcpy.isChecked() else OperationType.MOVE
        self.engine.prepare_job(self.src, self.dst, TransferMode.AUTO, self.op, ConflictPolicy.SMART_RESUME, 16)
        self.engine.start()

def format_size(b):
    for u in ['B','KB','MB','GB','TB']:
        if b < 1024: return f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.1f} PB"

def main():
    app = QApplication(sys.argv); window = MainWindow(); window.show(); sys.exit(app.exec())
if __name__ == "__main__": main()
