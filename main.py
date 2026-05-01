"""
HyperMove v10.0 - Complete Restoration Edition
The ultimate zero-compromise file transfer engine.
RESTORED: Full code readability (no more 1-line minification).
RESTORED: Data Verification, CSV Logging, Mac Direct I/O, and Global Hotkeys.
"""

import sys
import os
import time
import math
import platform
import shutil
import ctypes
import subprocess
import csv
import logging
from enum import Enum
from pathlib import Path
from queue import Queue
from threading import Lock
import random

# =====================================================================
# Optional Global Hotkey Support (Restored from v1.0)
# =====================================================================
try:
    from pynput import keyboard
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False

# =====================================================================
# App Resource Manager for PyInstaller / GitHub Actions
# =====================================================================
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for compiled EXE """
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# ---------------------------------------------------------
# OS-Specific Native Window Blur & Dragging
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
        except Exception:
            pass

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
    QGridLayout, QGraphicsOpacityEffect, QButtonGroup, QCheckBox
)
from PySide6.QtCore import (
    Qt, QThread, Signal, Slot, QRunnable, QThreadPool, QMutex, QObject, QTimer, 
    QPropertyAnimation, QEasingCurve, QVariantAnimation, QParallelAnimationGroup, QPointF, QPoint
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
    IDLE = 0
    COPYING = 1
    PAUSED = 2
    RESUMING = 3
    STOPPING = 4
    VERIFYING = 5  # Restored Verification State

CHUNK_SIZE = 1024 * 1024  
VERIFY_CHUNK_SIZE = 64 * 1024  # Restored from v1.0
DIRECT_CHUNK_SIZE = 1024 * 1024 * 8  

class DirectIOWrapper:
    def __init__(self, path, mode='r'):
        self.path = path
        self.mode = mode
    def read(self, size): raise NotImplementedError
    def write(self, data): raise NotImplementedError
    def seek(self, offset): raise NotImplementedError
    def close(self): raise NotImplementedError

class PosixDirectIO(DirectIOWrapper):
    def __init__(self, path, mode='r'):
        super().__init__(path, mode)
        flags = os.O_RDONLY if mode == 'r' else (os.O_WRONLY | os.O_CREAT)
        if mode == 'w': 
            flags |= os.O_TRUNC
        if hasattr(os, 'O_DIRECT'): 
            flags |= os.O_DIRECT
        self.fd = os.open(path, flags, 0o666)

    def read(self, size): 
        return os.read(self.fd, size)

    def write(self, data): 
        return os.write(self.fd, data)

    def seek(self, offset): 
        os.lseek(self.fd, offset, os.SEEK_SET)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

class MacDirectIO(DirectIOWrapper):
    """ Restored from original v1.0 """
    def __init__(self, path, mode='r'):
        super().__init__(path, mode)
        import fcntl
        flags = os.O_RDONLY if mode == 'r' else (os.O_WRONLY | os.O_CREAT)
        self.fd = os.open(path, flags, 0o666)
        try: 
            fcntl.fcntl(self.fd, fcntl.F_NOCACHE, 1)
        except Exception: 
            pass

    def read(self, size): 
        return os.read(self.fd, size)

    def write(self, data): 
        return os.write(self.fd, data)

    def seek(self, offset): 
        os.lseek(self.fd, offset, os.SEEK_SET)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

class WindowsDirectIO(DirectIOWrapper):
    def __init__(self, path, mode='r'):
        super().__init__(path, mode)
        self.kernel32 = ctypes.windll.kernel32
        creation = 3 if mode == 'r' else (4 if mode == 'a' else 2) 
        self.handle = self.kernel32.CreateFileW(
            str(path), 
            0x80000000 if mode == 'r' else 0x40000000, 
            1 | 2, 
            None, 
            creation, 
            0x20000000, 
            None
        )
        if self.handle == -1: 
            raise ctypes.WinError()
        self.buf_size = DIRECT_CHUNK_SIZE
        self.buffer = self.kernel32.VirtualAlloc(None, self.buf_size, 0x1000 | 0x2000, 0x04)

    def read(self, size):
        bytes_read = ctypes.c_ulong(0)
        success = self.kernel32.ReadFile(self.handle, self.buffer, min(size, self.buf_size), ctypes.byref(bytes_read), None)
        if not success and bytes_read.value == 0:
            err = self.kernel32.GetLastError()
            if err != 38: 
                raise ctypes.WinError(err)
            return b""
        return ctypes.string_at(self.buffer, bytes_read.value)

    def write(self, data):
        data_len = len(data)
        ctypes.memmove(self.buffer, data, data_len)
        bytes_written = ctypes.c_ulong(0)
        self.kernel32.WriteFile(self.handle, self.buffer, data_len, ctypes.byref(bytes_written), None)
        return bytes_written.value

    def seek(self, offset): 
        self.kernel32.SetFilePointerEx(self.handle, ctypes.c_int64(offset), None, 0)

    def close(self):
        if hasattr(self, 'handle') and self.handle != -1: 
            self.kernel32.CloseHandle(self.handle)
            self.handle = -1
        if hasattr(self, 'buffer') and self.buffer: 
            self.kernel32.VirtualFree(self.buffer, 0, 0x8000)
            self.buffer = 0

def get_direct_io(path, mode='r'): 
    sys_name = platform.system()
    if sys_name == "Windows":
        return WindowsDirectIO(path, mode)
    elif sys_name == "Darwin":
        return MacDirectIO(path, mode)
    else:
        return PosixDirectIO(path, mode)

# =====================================================================
# Engine Workers
# =====================================================================

class WorkerSignals(QObject):
    progress = Signal(int)
    file_started = Signal(str)
    finished = Signal(str, str, bool, str)

class ParallelWorker(QRunnable):
    def __init__(self, src, dst, engine, offset=0):
        super().__init__()
        self.src = src
        self.dst = dst
        self.engine = engine
        self.offset = offset
        self.signals = WorkerSignals()

    def run(self):
        try:
            self.signals.file_started.emit(Path(self.src).name)
            if self.engine.state in [EngineState.STOPPING, EngineState.PAUSED]: 
                return
            
            sync_counter = 0
            mode = 'ab' if self.offset > 0 else 'wb'
            
            with open(self.src, 'rb') as fsrc, open(self.dst, mode) as fdst:
                if self.offset > 0: 
                    fsrc.seek(self.offset)
                
                while True:
                    if self.engine.state in [EngineState.STOPPING, EngineState.PAUSED]:
                        if self.engine.state == EngineState.PAUSED: 
                            self.engine.save_offset(self.src, self.offset)
                        fdst.flush()
                        os.fsync(fdst.fileno())
                        return
                    
                    chunk = fsrc.read(CHUNK_SIZE)
                    if not chunk: 
                        break
                    
                    fdst.write(chunk)
                    self.offset += len(chunk)
                    self.signals.progress.emit(len(chunk))
                    
                    sync_counter += len(chunk)
                    if sync_counter > 50 * 1024 * 1024: 
                        fdst.flush()
                        os.fsync(fdst.fileno())
                        sync_counter = 0
            
            self.signals.finished.emit(str(self.src), str(self.dst), True, "")
        except Exception as e: 
            self.signals.finished.emit(str(self.src), str(self.dst), False, str(e))

class CopyEngineSignals(QObject):
    log_msg = Signal(str)
    active_file = Signal(str)
    file_progress = Signal(int, int)
    stats_update = Signal(int, int, str)
    progress_update = Signal(int, int)
    state_changed = Signal(EngineState)
    job_finished = Signal()

class CopyEngine(QThread):
    def __init__(self):
        super().__init__()
        self.signals = CopyEngineSignals()
        self.state = EngineState.IDLE
        self.state_mutex = QMutex()
        
        self.src_path = ""
        self.dst_path = ""
        self.mode = TransferMode.AUTO
        self.operation = OperationType.COPY
        self.conflict_policy = ConflictPolicy.SMART_RESUME
        self.threads = 16
        
        # Restored Features
        self.verify_data = False
        self.log_to_csv = False
        self.csv_path = ""
        
        self.total_bytes = 0
        self.transferred_bytes = 0
        self.files_to_process = []
        self.file_offsets = {}
        self.failed_files = []
        self.processed_count = 0
        self.skipped_files = [] 
        self.active_destinations = set()
        
        self.pool = QThreadPool()
        self.worker_lock = Lock()
        self.speed_history = []
        self.last_update_time = 0
        self.last_transferred = 0
        self.start_time = 0

    def set_state(self, new_state): 
        self.state_mutex.lock()
        self.state = new_state
        self.state_mutex.unlock()
        self.signals.state_changed.emit(new_state)

    def save_offset(self, src, off):
        with self.worker_lock: 
            self.file_offsets[str(src)] = off

    def prepare_job(self, src, dst, mode, op, conf, threads, verify, log_csv, csv_path):
        self.src_path = Path(src)
        self.dst_path = Path(dst)
        self.mode = mode
        self.operation = op
        self.conflict_policy = conf
        self.threads = threads
        
        self.verify_data = verify
        self.log_to_csv = log_csv
        self.csv_path = csv_path
        
        self.total_bytes = 0
        self.transferred_bytes = 0
        self.files_to_process.clear()
        self.file_offsets.clear()
        self.active_destinations.clear()
        self.failed_files.clear()
        self.skipped_files.clear()
        self.processed_count = 0
        self.speed_history.clear()
        self.start_time = time.time()
        
        temp = []
        if self.src_path.is_file(): 
            temp.append((self.src_path, self.dst_path / self.src_path.name if self.dst_path.is_dir() else self.dst_path))
        else:
            for r, _, fs in os.walk(self.src_path):
                for f in fs:
                    sf = Path(r) / f
                    df = self.dst_path / self.src_path.name / sf.relative_to(self.src_path)
                    temp.append((sf, df))
                    
        res = 0
        unaligned_resume_detected = False
        
        for sf, df in temp:
            sz = sf.stat().st_size
            self.total_bytes += sz
            if df.exists():
                dsz = df.stat().st_size
                if self.conflict_policy == ConflictPolicy.SKIP: 
                    self.skipped_files.append(sf)
                    self.transferred_bytes += sz
                    continue
                if self.conflict_policy == ConflictPolicy.SMART_RESUME:
                    if dsz < sz and dsz > 0: 
                        self.file_offsets[str(sf)] = dsz
                        self.transferred_bytes += dsz
                        res += 1
                        if dsz % 4096 != 0: 
                            unaligned_resume_detected = True
                        self.files_to_process.append((sf, df))
                    elif dsz == sz: 
                        self.skipped_files.append(sf)
                        self.transferred_bytes += sz
                    else: 
                        self.files_to_process.append((sf, df))
                else: 
                    self.files_to_process.append((sf, df))
            else: 
                self.files_to_process.append((sf, df))
                
        if res > 0: 
            self.signals.log_msg.emit(f"<span style='color:#FFBD2E;'>Power-Cut Recovery: Resuming {res} files...</span>")
            
        if self.mode == TransferMode.AUTO: 
            self.mode = TransferMode.DIRECT if (len(self.files_to_process) == 1 and self.total_bytes > 1024**3) else TransferMode.PARALLEL

        if self.mode == TransferMode.DIRECT and unaligned_resume_detected:
            self.mode = TransferMode.PARALLEL
            self.signals.log_msg.emit("<span style='color:#FFBD2E;'>Alignment mismatch detected. Using safe Parallel Mode.</span>")

    def run(self):
        self.set_state(EngineState.COPYING if self.state != EngineState.RESUMING else EngineState.COPYING)
        self.last_update_time = time.time()
        self.last_transferred = self.transferred_bytes
        self.pool.setMaxThreadCount(self.threads if self.mode == TransferMode.PARALLEL else 1)
        
        if self.mode == TransferMode.PARALLEL: 
            self._run_parallel()
        else: 
            self._run_direct()
            
        self.pool.waitForDone()
        
        if self.state == EngineState.STOPPING: 
            self._cleanup_partials()
            self.set_state(EngineState.IDLE)
            self.signals.job_finished.emit()
            return
            
        if self.state == EngineState.PAUSED: 
            return

        # Restored Data Integrity Verification
        if self.verify_data and not self.failed_files:
            self.set_state(EngineState.VERIFYING)
            self.signals.log_msg.emit("<span style='color:#00F3FF;'>Verifying data integrity...</span>")
            if not self._verify_files():
                self.set_state(EngineState.IDLE)
                self.signals.job_finished.emit()
                return
            self.signals.log_msg.emit("<span style='color:#00FF00;'>Data integrity verified. Match 100%.</span>")

        if self.operation == OperationType.MOVE and not self.failed_files:
            self.signals.log_msg.emit("Finalizing move. Wiping sources...")
            try:
                for sf, df in self.files_to_process:
                    if sf.exists(): 
                        sf.unlink()
                if self.src_path.is_dir():
                    for root, dirs, files in os.walk(self.src_path, topdown=False):
                        for name in dirs:
                            try: os.rmdir(os.path.join(root, name))
                            except: pass
                    try: os.rmdir(self.src_path)
                    except: pass
                self.signals.log_msg.emit("Source files successfully wiped.")
            except Exception as e: 
                self.signals.log_msg.emit(f"<span style='color:#FF453A;'>Cleanup Error: {e}</span>")

        self.set_state(EngineState.IDLE)
        self.signals.job_finished.emit()

    def _run_parallel(self):
        for src, dst in self.files_to_process:
            if self.state != EngineState.COPYING: 
                break
            offset = self.file_offsets.get(str(src), 0)
            dst.parent.mkdir(parents=True, exist_ok=True)
            self.active_destinations.add(str(dst))
            
            worker = ParallelWorker(src, dst, self, offset)
            worker.signals.progress.connect(self._on_worker_progress)
            worker.signals.file_started.connect(self.signals.active_file.emit)
            worker.signals.finished.connect(self._on_worker_finished)
            self.pool.start(worker)

    def _run_direct(self):
        for src, dst in self.files_to_process:
            if self.state != EngineState.COPYING: 
                break
            self.signals.active_file.emit(src.name)
            offset = self.file_offsets.get(str(src), 0)
            dst.parent.mkdir(parents=True, exist_ok=True)
            self.active_destinations.add(str(dst))
            
            try:
                current_file_total = src.stat().st_size
                fs = get_direct_io(src, 'r')
                fd = get_direct_io(dst, 'a' if offset > 0 else 'w')
                
                if offset > 0: 
                    fs.seek(offset)
                    fd.seek(offset)
                
                while True:
                    if self.state in [EngineState.STOPPING, EngineState.PAUSED]:
                        if self.state == EngineState.PAUSED: 
                            self.save_offset(src, offset)
                        break
                    
                    chunk = fs.read(DIRECT_CHUNK_SIZE)
                    if not chunk: 
                        break
                    
                    fd.write(chunk)
                    offset += len(chunk)
                    self._on_worker_progress(len(chunk))
                    self.signals.file_progress.emit(offset, current_file_total)
                    
                fs.close()
                fd.close()
                self._on_worker_finished(str(src), str(dst), True, "")
            except Exception as e: 
                self._on_worker_finished(str(src), str(dst), False, str(e))

    def _verify_files(self):
        """ Restored from original v1.0 """
        for src, dst in self.files_to_process:
            if self.state == EngineState.STOPPING: 
                return False
            try:
                with open(src, 'rb') as f1, open(dst, 'rb') as f2:
                    while True:
                        if self.state == EngineState.STOPPING: 
                            return False
                        c1 = f1.read(VERIFY_CHUNK_SIZE)
                        c2 = f2.read(VERIFY_CHUNK_SIZE)
                        if c1 != c2: 
                            self.failed_files.append(src)
                            self.signals.log_msg.emit(f"<span style='color:#FF453A;'>Verification failed for {Path(src).name}</span>")
                            return False
                        if not c1: 
                            break
            except Exception as e:
                self.signals.log_msg.emit(f"<span style='color:#FF453A;'>Verification Error: {e}</span>")
                return False
        return True

    def _cleanup_partials(self):
        with self.worker_lock:
            for dst_path in self.active_destinations:
                try: 
                    p = Path(dst_path)
                    if p.exists(): 
                        p.unlink()
                except Exception: 
                    pass
            self.active_destinations.clear()

    @Slot(int)
    def _on_worker_progress(self, b):
        with self.worker_lock: 
            self.transferred_bytes += b
        cur = time.time()
        elap = cur - self.last_update_time
        
        if elap > 0.2:
            sp = (self.transferred_bytes - self.last_transferred) / elap
            self.speed_history.append(sp)
            if len(self.speed_history) > 10: 
                self.speed_history.pop(0)
            
            avg = int(sum(self.speed_history) / len(self.speed_history))
            self.last_update_time = cur
            self.last_transferred = self.transferred_bytes
            
            eta = "Calculating..."
            if avg > 0:
                s = int((self.total_bytes - self.transferred_bytes) / avg)
                if s > 3600:
                    eta = f"~ {s//3600}h {(s%3600)//60}m"
                elif s > 60:
                    eta = f"~ {s//60} min"
                else:
                    eta = f"~ {s} sec"
                    
            self.signals.progress_update.emit(self.transferred_bytes, self.total_bytes)
            self.signals.stats_update.emit(self.transferred_bytes, avg, eta)

    @Slot(str, str, bool, str)
    def _on_worker_finished(self, s, d, succ, err):
        with self.worker_lock: 
            self.processed_count += 1
            if str(d) in self.active_destinations: 
                self.active_destinations.remove(str(d))
            if not succ: 
                self.failed_files.append(s)
                self.signals.log_msg.emit(f"<span style='color:#FF453A;'>Error: {err}</span>")
            
            # Restored CSV Logging
            if self.log_to_csv and self.csv_path:
                try:
                    with open(self.csv_path, 'a', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        status = "Success" if succ else f"Failed: {err}"
                        writer.writerow([time.strftime('%Y-%m-%d %H:%M:%S'), s, d, status])
                except Exception:
                    pass

# =====================================================================
# UI Components: Interactive Liquid Graph
# =====================================================================

class LiquidSpeedGraph(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(80)
        self.points = [0] * 60  
        self.max_val = 1
        self.phase = 0.0
        self.accent = QColor(0, 243, 255)
        
        self.particles = [{"x": random.randint(0, 800), "y": random.randint(0, 80), "s": random.uniform(1, 4)} for _ in range(15)]
        
        self.wave_anim = QVariantAnimation()
        self.wave_anim.setDuration(4000)
        self.wave_anim.setStartValue(0.0)
        self.wave_anim.setEndValue(math.pi * 2)
        self.wave_anim.setLoopCount(-1)
        self.wave_anim.valueChanged.connect(self._tick)
        self.wave_anim.start()

    def set_accent(self, color): 
        self.accent = color

    def _tick(self, val):
        self.phase = val
        for p in self.particles:
            p["x"] += p["s"] * (1 + (self.points[-1] / (1024*1024*100))) 
            if p["x"] > self.width(): 
                p["x"] = -10
                p["y"] = random.randint(10, 70)
        self.update()

    def update_data(self, val): 
        self.points.pop(0)
        self.points.append(val)
        self.max_val = max(max(self.points), 1024*1024*20) 

    def reset(self): 
        self.points = [0] * 60

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        w = self.width()
        h = self.height()
        step = w / (len(self.points) - 1)
        
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(self.accent.red(), self.accent.green(), self.accent.blue(), 60))
        for p in self.particles: 
            painter.drawEllipse(QPointF(p["x"], p["y"]), 1.5, 1.5)

        def get_path(off, amp):
            path = QPainterPath()
            path.moveTo(0, h)
            for i, v in enumerate(self.points):
                x = i * step
                ripple = math.sin(self.phase * 2 + i * 0.15 + off) * amp
                y = h - ((v / self.max_val) * (h-20)) + ripple
                if i == 0: 
                    path.lineTo(x, y)
                else: 
                    px = (i-1)*step
                    py = h - ((self.points[i-1]/self.max_val)*(h-20)) + math.sin(self.phase*2+(i-1)*0.15+off)*amp
                    path.cubicTo(px + step/2, py, px + step/2, y, x, y)
            path.lineTo(w, h)
            path.closeSubpath()
            return path

        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0, QColor(self.accent.red(), self.accent.green(), self.accent.blue(), 100))
        grad.setColorAt(1, Qt.GlobalColor.transparent)
        
        painter.setBrush(grad)
        painter.drawPath(get_path(1.0, 6))
        
        painter.setPen(QPen(self.accent, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(get_path(0, 3))

# =====================================================================
# Main Application Components
# =====================================================================

def format_size(bytes_size):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0: 
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} PB"

class GlassCard(QFrame):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("GlassCard { background-color: rgba(255, 255, 255, 0.04); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 14px; }")

class AnimatedDropZone(QFrame):
    dropped = Signal(str)
    browse = Signal(str)
    cleared = Signal()

    def __init__(self, title, is_src=True):
        super().__init__()
        self.is_src = is_src
        self.setFixedHeight(130 if is_src else 110)
        self.base_style = "AnimatedDropZone { background: rgba(255,255,255,0.03); border: 2px dashed rgba(255,255,255,0.1); border-radius: 12px; }"
        self.setStyleSheet(self.base_style)
        self.setAcceptDrops(True)
        self.layout = QGridLayout(self)
        
        self.view_empty = QWidget()
        el = QVBoxLayout(self.view_empty)
        el.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        lbl = QLabel(f"Drop {title} Here")
        lbl.setStyleSheet("color: rgba(255,255,255,0.6); font-weight: bold;")
        btns = QHBoxLayout()
        
        if is_src:
            self.bf = self._btn("📄 File")
            self.bf.clicked.connect(lambda: self.browse.emit('file'))
            btns.addWidget(self.bf)
            
        self.bd = self._btn("📁 Folder")
        self.bd.clicked.connect(lambda: self.browse.emit('folder'))
        btns.addWidget(self.bd)
        
        el.addWidget(lbl)
        el.addLayout(btns)
        
        self.view_sel = QWidget()
        sl = QVBoxLayout(self.view_sel)
        sl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.licon = QLabel("📁")
        self.licon.setFont(QFont("Arial", 20))
        self.lname = QLabel("Name")
        self.lname.setStyleSheet("color: white; font-weight: bold;")
        self.linfo = QLabel("Size")
        self.linfo.setStyleSheet("color: rgba(255,255,255,0.4); font-size: 10px;")
        
        self.bc = self._btn("✕ Clear", True)
        self.bc.clicked.connect(self.clear_sel)
        
        sl.addWidget(self.licon)
        sl.addWidget(self.lname)
        sl.addWidget(self.linfo)
        sl.addWidget(self.bc, alignment=Qt.AlignmentFlag.AlignHCenter)
        
        self.layout.addWidget(self.view_empty, 0, 0)
        self.layout.addWidget(self.view_sel, 0, 0)
        self.view_sel.hide()

    def _btn(self, t, is_c=False):
        b = QPushButton(t)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(f"QPushButton {{ background: rgba(255,255,255,0.08); color: white; border-radius: 10px; padding: 5px 12px; font-size: 10px; border: 1px solid rgba(255,255,255,0.1); }} QPushButton:hover {{ background: {'rgba(255,69,58,0.2)' if is_c else 'rgba(255,255,255,0.15)'}; }}")
        return b

    def dragEnterEvent(self, e): 
        if e.mimeData().hasUrls(): 
            self.setStyleSheet("AnimatedDropZone { background: rgba(255,255,255,0.05); border: 2px dashed #00F3FF; }")
            e.acceptProposedAction()

    def dragLeaveEvent(self, e): 
        self.setStyleSheet("AnimatedDropZone { background: rgba(255,255,255,0.03); border: 2px dashed rgba(255,255,255,0.1); }")

    def dropEvent(self, e): 
        self.dragLeaveEvent(None)
        urls = e.mimeData().urls()
        if urls: 
            p = urls[0].toLocalFile()
            self.set_path(p)
            self.dropped.emit(p)
    
    def set_path(self, p):
        path = Path(p)
        self.licon.setText("📄" if path.is_file() else "📁")
        self.lname.setText(path.name[:30])
        try:
            if path.is_file(): 
                sz_val = path.stat().st_size
            else: 
                sz_val = sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
            sz = format_size(sz_val)
        except Exception: 
            sz = "Unknown"
            
        self.linfo.setText(sz)
        self.view_empty.hide()
        self.view_sel.show()
        
        self.anim = QPropertyAnimation(self, b"pos")
        self.anim.setDuration(500)
        self.anim.setStartValue(self.pos() + QPoint(0, 15))
        self.anim.setEndValue(self.pos())
        self.anim.setEasingCurve(QEasingCurve.Type.OutBack)
        self.anim.start()

    def clear_sel(self): 
        self.view_sel.hide()
        self.view_empty.show()
        self.cleared.emit()

class MainWindow(QMainWindow):
    show_window_signal = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.resize(920, 780) # Made slightly taller to fit restored checkboxes
        
        logo = resource_path("logo.ico")
        if os.path.exists(logo): 
            self.setWindowIcon(QIcon(logo))
            
        self.engine = CopyEngine()
        self.engine.signals.log_msg.connect(self.log)
        self.engine.signals.active_file.connect(self.update_active_file)
        self.engine.signals.stats_update.connect(self.upd_stats)
        self.engine.signals.progress_update.connect(self.upd_prog)
        self.engine.signals.file_progress.connect(self.upd_file_prog)
        self.engine.signals.state_changed.connect(self.upd_state)
        self.engine.signals.job_finished.connect(self.done)
        
        self.src = ""
        self.dst = ""
        self.op = OperationType.COPY
        self.init_ui()
        self.setup_global_hotkey() # Restored from v1.0
        
        QTimer.singleShot(100, lambda: apply_native_window_blur(self.winId()))

    def init_ui(self):
        self.cw = QWidget()
        self.setCentralWidget(self.cw)
        self.cw.setObjectName("cw")
        self.cw.setStyleSheet("QWidget#cw { background: rgba(18,18,20,210); border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; } QLabel { font-family: 'SF Pro Display', 'Segoe UI'; color: white; }")
        
        main = QVBoxLayout(self.cw)
        main.setContentsMargins(0,0,0,0)
        
        # Title Bar
        tb = QWidget()
        tb.setFixedHeight(45)
        tbl = QHBoxLayout(tb)
        tbl.setContentsMargins(15,0,15,0)
        
        for c in ["#FF5F56", "#FFBD2E", "#27C93F"]:
            d = QPushButton()
            d.setFixedSize(12,12)
            d.setStyleSheet(f"background: {c}; border-radius: 6px; border: none;")
            tbl.addWidget(d)
            
        tbl.addSpacing(15)
        self.lblt = QLabel("HyperMove Pro - Complete Restoration")
        self.lblt.setStyleSheet("font-weight: bold; opacity: 0.6; font-size: 11px;")
        tbl.addWidget(self.lblt)
        tbl.addStretch()
        
        main.addWidget(tb)
        tb.mousePressEvent = lambda e: trigger_native_drag(self)

        content = QHBoxLayout()
        content.setContentsMargins(25,10,25,25)
        content.setSpacing(20)
        
        # Left Panel
        lp = QVBoxLayout()
        lp.setSpacing(12)
        
        self.ds = AnimatedDropZone("Source")
        self.ds.dropped.connect(self.set_s)
        self.ds.browse.connect(lambda t: self.br_s(t))
        self.ds.cleared.connect(lambda: self.set_s(""))
        
        self.dd = AnimatedDropZone("Target", False)
        self.dd.dropped.connect(self.set_d)
        self.dd.browse.connect(lambda t: self.br_d(t))
        self.dd.cleared.connect(lambda: self.set_d(""))
        
        self.log_w = QTextEdit()
        self.log_w.setReadOnly(True)
        self.log_w.setStyleSheet("background: rgba(0,0,0,0.15); border-radius: 10px; border: 1px solid rgba(255,255,255,0.05); color: #777; font-size: 10px; padding: 10px;")
        
        lp.addWidget(self.ds)
        lp.addWidget(self.dd)
        lp.addWidget(QLabel("TELEMETRY LOG", styleSheet="color:rgba(255,255,255,0.3); font-size:9px; font-weight:bold; margin-top:5px;"))
        lp.addWidget(self.log_w)
        
        # Right Panel
        rp = QVBoxLayout()
        rp.setSpacing(15)
        
        dc = GlassCard()
        dl = QVBoxLayout(dc)
        dl.setContentsMargins(0,25,0,0) 
        
        self.lspd = QLabel("0.0 MB/s")
        self.lspd.setFont(QFont("SF Pro Display", 56, QFont.Weight.Bold))
        self.lspd.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lspd.setStyleSheet("color: white; background: transparent;")
        
        self.lact = QLabel("Engine Idle")
        self.lact.setStyleSheet("color: #00F3FF; font-size: 10px; margin: 0 25px;")
        
        self.lstats = QLabel("-- / --")
        self.leta = QLabel("ETA: --")
        
        tl = QHBoxLayout()
        tl.setContentsMargins(25,0,25,0)
        tl.addWidget(self.lstats)
        tl.addStretch()
        tl.addWidget(self.leta)
        
        self.graph = LiquidSpeedGraph()
        
        self.prog = QProgressBar()
        self.prog.setFixedHeight(4)
        self.prog.setTextVisible(False)
        self.prog.setStyleSheet("QProgressBar { background: rgba(255,255,255,0.05); border: none; } QProgressBar::chunk { background: #00F3FF; }")
        
        self.file_prog = QProgressBar()
        self.file_prog.setFixedHeight(2)
        self.file_prog.setTextVisible(False)
        self.file_prog.setStyleSheet("QProgressBar { background: transparent; border: none; } QProgressBar::chunk { background: rgba(255,255,255,0.2); }")
        
        dl.addWidget(self.lspd)
        dl.addWidget(self.lact)
        dl.addLayout(tl)
        dl.addSpacing(10)
        dl.addWidget(self.file_prog)
        dl.addWidget(self.graph)
        dl.addWidget(self.prog)
        
        cc = GlassCard()
        cl = QVBoxLayout(cc)
        cl.setContentsMargins(20,15,20,20)
        
        ops = QHBoxLayout()
        self.bcpy = self._opbtn("COPY", True)
        self.bmov = self._opbtn("MOVE", False)
        
        self.og = QButtonGroup(self)
        self.og.addButton(self.bcpy, 0)
        self.og.addButton(self.bmov, 1)
        self.og.buttonClicked.connect(self.sync_theme)
        
        ops.addWidget(self.bcpy)
        ops.addWidget(self.bmov)
        
        # Restored Features Settings Row
        settings_grid = QGridLayout()
        lbl_conflict = QLabel("Conflict Handling:")
        self.conflict_combo = QComboBox()
        self.conflict_combo.addItems([c.value for c in ConflictPolicy])
        
        lbl_mode = QLabel("Hardware Profile:")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([m.value for m in TransferMode])
        
        for combo in [self.conflict_combo, self.mode_combo]: 
            combo.setStyleSheet("QComboBox { background: rgba(0,0,0,0.2); color: white; border: 1px solid rgba(255,255,255,0.1); border-radius: 4px; padding: 2px 5px; font-size: 10px; }")
            
        settings_grid.addWidget(lbl_conflict, 0, 0)
        settings_grid.addWidget(self.conflict_combo, 0, 1)
        settings_grid.addWidget(lbl_mode, 1, 0)
        settings_grid.addWidget(self.mode_combo, 1, 1)

        # Restored from v1.0 Checkboxes
        self.chk_verify = QCheckBox("Verify Data Integrity")
        self.chk_verify.setStyleSheet("QCheckBox { color: rgba(255,255,255,0.7); font-size: 11px; }")
        
        self.chk_csv = QCheckBox("Export Log to CSV")
        self.chk_csv.setStyleSheet("QCheckBox { color: rgba(255,255,255,0.7); font-size: 11px; }")
        
        settings_grid.addWidget(self.chk_verify, 2, 0)
        settings_grid.addWidget(self.chk_csv, 2, 1)

        self.bstart = QPushButton("START ENGINE")
        self.bstart.setFixedHeight(48)
        self.bstart.setFont(QFont("SF Pro Display", 14, QFont.Weight.Bold))
        self.bstart.setStyleSheet("QPushButton { background: #00F3FF; color: black; border-radius: 12px; } QPushButton:hover { background: white; }")
        self.bstart.clicked.connect(self.start_job)
        
        control_action_layout = QHBoxLayout()
        self.btn_pause = self._make_sec_btn("Pause")
        self.btn_resume = self._make_sec_btn("Resume")
        self.btn_stop = self._make_sec_btn("Cancel", "#FF453A", "rgba(255,69,58,0.2)")
        
        for b in [self.btn_pause, self.btn_resume, self.btn_stop]: 
            b.setEnabled(False)
            control_action_layout.addWidget(b)
            
        cl.addLayout(ops)
        cl.addSpacing(10)
        cl.addLayout(settings_grid)
        cl.addSpacing(15)
        cl.addWidget(self.bstart)
        cl.addSpacing(10)
        cl.addLayout(control_action_layout)
        
        rp.addWidget(dc)
        rp.addWidget(cc)
        
        content.addLayout(lp, 45)
        content.addLayout(rp, 55)
        main.addLayout(content)

        self.btn_pause.clicked.connect(lambda: self.engine.set_state(EngineState.PAUSED))
        self.btn_resume.clicked.connect(lambda: [self.engine.set_state(EngineState.RESUMING), self.engine.start()])
        self.btn_stop.clicked.connect(self.stop_transfer)

    # Restored from v1.0 - Global Hotkey
    def setup_global_hotkey(self):
        self.show_window_signal.connect(self.bring_to_front)
        if PYNPUT_AVAILABLE:
            def on_activate(): 
                self.show_window_signal.emit()
            try:
                self.hotkey = keyboard.GlobalHotKeys({'<ctrl>+<cmd>+m': on_activate, '<ctrl>+<win>+m': on_activate})
                self.hotkey.start()
            except Exception: 
                pass

    @Slot()
    def bring_to_front(self):
        self.setWindowState((self.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive)
        self.raise_()
        self.activateWindow()

    def sync_theme(self):
        is_copy = self.bcpy.isChecked()
        color = "#00F3FF" if is_copy else "#FF2E93"
        self.lact.setStyleSheet(f"color: {color}; font-size: 10px; margin: 0 25px;")
        self.prog.setStyleSheet(f"QProgressBar {{ background: rgba(255,255,255,0.05); border: none; }} QProgressBar::chunk {{ background: {color}; }}")
        self.bstart.setStyleSheet(f"QPushButton {{ background: {color}; color: {'black' if is_copy else 'white'}; border-radius: 12px; }} QPushButton:hover {{ background: white; color: black; }}")
        self.graph.set_accent(QColor(color))

    def _opbtn(self, t, s):
        b = QPushButton(t)
        b.setCheckable(True)
        b.setChecked(s)
        b.setFixedHeight(30)
        b.setStyleSheet("QPushButton { background: rgba(255,255,255,0.05); color: #666; border-radius: 6px; border: 1px solid transparent; font-weight: bold; } QPushButton:checked { background: rgba(255,255,255,0.08); color: white; border: 1px solid rgba(255,255,255,0.15); }")
        return b

    def _make_sec_btn(self, text, hover_color="#ffffff", hover_bg="rgba(255,255,255,0.1)"):
        btn = QPushButton(text)
        btn.setFixedHeight(30)
        btn.setStyleSheet(f"QPushButton {{ background: rgba(255,255,255,0.05); color: rgba(255,255,255,0.8); border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; font-size: 11px;}} QPushButton:hover {{ background: {hover_bg}; color: {hover_color}; }}")
        return btn

    def br_s(self, t):
        p = QFileDialog.getOpenFileName(self, "Src")[0] if t=='file' else QFileDialog.getExistingDirectory(self, "Src")
        if p: 
            self.ds.set_path(p)
            self.set_s(p)

    def br_d(self, t):
        p = QFileDialog.getExistingDirectory(self, "Dest")
        if p: 
            self.dd.set_path(p)
            self.set_d(p)

    def set_s(self, p): 
        self.src = p

    def set_d(self, p): 
        self.dst = p

    @Slot(str)
    def update_active_file(self, name): 
        trunc = name if len(name) < 40 else f"...{name[-37:]}"
        self.lact.setText(f"Active: {trunc}")

    @Slot(str)
    def log(self, msg):
        ts = time.strftime("%H:%M:%S")
        self.log_w.append(f"<span style='color:rgba(255,255,255,0.3);'>[{ts}]</span> {msg}")
        self.log_w.verticalScrollBar().setValue(self.log_w.verticalScrollBar().maximum())

    @Slot(int, int)
    def upd_prog(self, transferred, total):
        if total > 0: 
            self.prog.setValue(int((transferred / total) * 100))
            self.lstats.setText(f"{format_size(transferred)} / {format_size(total)}")

    @Slot(int, int, str)
    def upd_stats(self, transferred, speed, eta):
        self.graph.update_data(speed)
        mb_speed = speed / (1024*1024)
        self.lspd.setText(f"{mb_speed/1024:.2f} GB/s" if mb_speed > 1024 else f"{mb_speed:.1f} MB/s")
        self.leta.setText(f"ETA: {eta}")

    @Slot(int, int)
    def upd_file_prog(self, current, total): 
        if total > 0:
            self.file_prog.setValue(int((current / total) * 100))

    @Slot(EngineState)
    def upd_state(self, state): 
        self.bstart.setEnabled(state == EngineState.IDLE)
        self.btn_pause.setEnabled(state == EngineState.COPYING)
        self.btn_resume.setEnabled(state == EngineState.PAUSED)
        self.btn_stop.setEnabled(state in [EngineState.COPYING, EngineState.PAUSED, EngineState.RESUMING, EngineState.VERIFYING])
        
        self.ds.setEnabled(state == EngineState.IDLE)
        self.dd.setEnabled(state == EngineState.IDLE)
        
        if state == EngineState.COPYING: 
            self.log("<span style='color:#00F3FF;'>Engine spinning up...</span>")
            self.file_prog.setValue(0)
        elif state == EngineState.IDLE: 
            self.lact.setText("Engine Idle")

    @Slot()
    def done(self): 
        dur = time.time() - self.engine.start_time
        dur = max(dur, 1) 
        avg_spd = self.engine.total_bytes / dur
        
        self.log("<span style='color:#00FF00;'>Operation Complete.</span>")
        self.prog.setValue(100)
        self.lspd.setText("Done")
        
        summary = (f"Sync Finished Successfully!\n\n"
                   f"Total Data: {format_size(self.engine.total_bytes)}\n"
                   f"Average Speed: {format_size(avg_spd)}/s\n"
                   f"Total Time: {int(dur)} seconds\n\n"
                   f"Operation: {self.op.name}")
        QMessageBox.information(self, "HyperMove Master Report", summary)

    def start_job(self):
        if not self.src or not self.dst: 
            return QMessageBox.warning(self, "!", "Drop files first.")
            
        src_path = Path(self.src)
        if src_path.is_file(): 
            src_size = src_path.stat().st_size
        else: 
            src_size = sum(f.stat().st_size for f in src_path.rglob('*') if f.is_file())
            
        dest_free = shutil.disk_usage(self.dst).free
        if src_size > dest_free:
            return QMessageBox.critical(self, "Low Space", f"Not enough room! Required: {format_size(src_size)}, Free: {format_size(dest_free)}")
            
        self.op = OperationType.COPY if self.bcpy.isChecked() else OperationType.MOVE
        mode = next(m for m in TransferMode if m.value == self.mode_combo.currentText())
        conflict = next(c for c in ConflictPolicy if c.value == self.conflict_combo.currentText())
        
        # Prepare CSV Logging path if checked
        csv_path_str = ""
        if self.chk_csv.isChecked():
            csv_path_str = os.path.join(str(Path(self.dst)), f"HyperMove_Log_{int(time.time())}.csv")
            try:
                with open(csv_path_str, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(["Timestamp", "Source", "Destination", "Status"])
            except Exception as e:
                self.log(f"Failed to create CSV: {e}")
                csv_path_str = ""
        
        self.progress_bar.setValue(0)
        self.engine.prepare_job(
            src=self.src, 
            dst=self.dst, 
            mode=mode, 
            op=self.op, 
            conf=conflict, 
            threads=16,
            verify=self.chk_verify.isChecked(),
            log_csv=self.chk_csv.isChecked(),
            csv_path=csv_path_str
        )
        self.engine.start()

    def stop_transfer(self):
        if QMessageBox.question(self, "Cancel", "Abort?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes: 
            self.engine.set_state(EngineState.STOPPING)

def main():
    app = QApplication(sys.argv)
    logo_path = resource_path("logo.ico")
    if os.path.exists(logo_path): 
        app.setWindowIcon(QIcon(logo_path))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
