"""
HyperMove v8.4 - Elite Precision Edition
The ultimate zero-compromise file transfer engine.
UPDATED: Ultra-smooth native Windows dragging and Snap-Layout support.
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
    sys_name = platform.system()
    if sys_name == "Windows":
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
    """Triggers native OS window dragging to prevent lag and support snapping."""
    if platform.system() == "Windows":
        # Professional Windows API call for HTCAPTION drag
        ctypes.windll.user32.ReleaseCapture()
        ctypes.windll.user32.SendMessageW(window.winId(), 0xA1, 2, 0)
    else:
        # Mac/Linux fallback
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
# Engine Constants & Direct I/O
# =====================================================================

class TransferMode(Enum):
    AUTO = "Auto (Smart)"
    PARALLEL = "Parallel (Safest/Stable)"
    DIRECT = "Direct I/O (Extreme Speed)"

class ConflictPolicy(Enum):
    SMART_RESUME = "Smart Resume (Fastest)"
    OVERWRITE = "Overwrite (Replace All)"
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

CHUNK_SIZE = 1024 * 1024  
DIRECT_CHUNK_SIZE = 1024 * 1024 * 8  

class DirectIOWrapper:
    def __init__(self, path, mode='r'):
        self.path, self.mode = path, mode
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
        self.handle = self.kernel32.CreateFileW(
            str(path), 0x80000000 if mode == 'r' else 0x40000000, 1 | 2,
            None, creation_disposition, 0x20000000, None
        )
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
        data_len = len(data)
        ctypes.memmove(self.buffer, data, data_len)
        bytes_written = ctypes.c_ulong(0)
        self.kernel32.WriteFile(self.handle, self.buffer, data_len, ctypes.byref(bytes_written), None)
        return bytes_written.value

    def seek(self, offset):
        self.kernel32.SetFilePointerEx(self.handle, ctypes.c_int64(offset), None, 0)

    def close(self):
        if hasattr(self, 'handle') and self.handle != -1: self.kernel32.CloseHandle(self.handle); self.handle = -1
        if hasattr(self, 'buffer') and self.buffer: self.kernel32.VirtualFree(self.buffer, 0, 0x8000); self.buffer = 0

def get_direct_io(path, mode='r'):
    return WindowsDirectIO(path, mode) if platform.system() == "Windows" else PosixDirectIO(path, mode)

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
        self.src, self.dst, self.engine, self.offset = src, dst, engine, offset
        self.signals = WorkerSignals()

    def run(self):
        try:
            self.signals.file_started.emit(Path(self.src).name)
            if self.engine.state in [EngineState.STOPPING, EngineState.PAUSED]:
                if self.engine.state == EngineState.PAUSED: self.engine.save_offset(self.src, self.offset)
                return
            sync_counter = 0
            mode = 'ab' if self.offset > 0 else 'wb'
            with open(self.src, 'rb') as fsrc, open(self.dst, mode) as fdst:
                if self.offset > 0: fsrc.seek(self.offset)
                while True:
                    if self.engine.state in [EngineState.STOPPING, EngineState.PAUSED]:
                        if self.engine.state == EngineState.PAUSED: self.engine.save_offset(self.src, self.offset)
                        fdst.flush()
                        os.fsync(fdst.fileno())
                        return
                    chunk = fsrc.read(CHUNK_SIZE)
                    if not chunk: break
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
        self.src_path, self.dst_path = "", ""
        self.mode = TransferMode.AUTO
        self.operation = OperationType.COPY
        self.conflict_policy = ConflictPolicy.SMART_RESUME
        self.threads = 16
        self.total_bytes, self.transferred_bytes = 0, 0
        self.files_to_process, self.file_offsets, self.failed_files = [], {}, []
        self.processed_count = 0
        self.skipped_files = [] 
        self.active_destinations = set()
        self.pool = QThreadPool()
        self.worker_lock = Lock()
        self.last_update_time = time.time()
        self.last_transferred = 0
        self.speed_history = []

    def set_state(self, new_state):
        self.state_mutex.lock()
        self.state = new_state
        self.state_mutex.unlock()
        self.signals.state_changed.emit(new_state)

    def save_offset(self, src_path, offset):
        with self.worker_lock: self.file_offsets[str(src_path)] = offset

    def prepare_job(self, src, dst, mode, operation, conflict, threads):
        self.src_path, self.dst_path = Path(src), Path(dst)
        self.mode, self.operation, self.conflict_policy, self.threads = mode, operation, conflict, threads
        self.total_bytes, self.transferred_bytes = 0, 0
        self.files_to_process.clear()
        self.file_offsets.clear()
        self.active_destinations.clear()
        self.failed_files.clear()
        self.skipped_files.clear()
        self.processed_count = 0
        self.speed_history.clear()

        temp_files = []
        if self.src_path.is_file():
            dst_file = self.dst_path / self.src_path.name if self.dst_path.is_dir() else self.dst_path
            temp_files.append((self.src_path, dst_file))
        else:
            for root, _, files in os.walk(self.src_path):
                for f in files:
                    src_f = Path(root) / f
                    dst_f = self.dst_path / self.src_path.name / src_f.relative_to(self.src_path)
                    temp_files.append((src_f, dst_f))
                    
        resumed_count = 0
        unaligned_resume_detected = False
        
        for src_f, dst_f in temp_files:
            src_size = src_f.stat().st_size
            self.total_bytes += src_size
            
            if dst_f.exists():
                dst_size = dst_f.stat().st_size
                if self.conflict_policy == ConflictPolicy.SKIP:
                    self.skipped_files.append(src_f); self.transferred_bytes += src_size; continue
                if self.conflict_policy == ConflictPolicy.SMART_RESUME:
                    if dst_size < src_size and dst_size > 0:
                        self.file_offsets[str(src_f)] = dst_size; self.transferred_bytes += dst_size; resumed_count += 1
                        if dst_size % 4096 != 0: unaligned_resume_detected = True
                        self.files_to_process.append((src_f, dst_f))
                    elif dst_size == src_size: self.skipped_files.append(src_f); self.transferred_bytes += src_size
                    else: self.files_to_process.append((src_f, dst_f))
                else: self.files_to_process.append((src_f, dst_f))
            else: self.files_to_process.append((src_f, dst_f))
                    
        if resumed_count > 0: self.signals.log_msg.emit(f"<span style='color:#FFBD2E;'>Power-Cut Recovery: Resuming {resumed_count} files.</span>")
        if len(self.skipped_files) > 0: self.signals.log_msg.emit(f"<span style='color:#00F3FF;'>Skipping {len(self.skipped_files)} existing files.</span>")

        if self.mode == TransferMode.AUTO:
            self.mode = TransferMode.DIRECT if (len(self.files_to_process) == 1 and self.total_bytes > 1024**3) else TransferMode.PARALLEL
        if self.mode == TransferMode.DIRECT and unaligned_resume_detected:
            self.mode = TransferMode.PARALLEL
            self.signals.log_msg.emit("<span style='color:#FFBD2E;'>Alignment mismatch detected. Using Parallel Mode for safety.</span>")

    def run(self):
        self.set_state(EngineState.COPYING if self.state != EngineState.RESUMING else EngineState.COPYING)
        self.last_update_time, self.last_transferred = time.time(), self.transferred_bytes
        self.pool.setMaxThreadCount(self.threads if self.mode == TransferMode.PARALLEL else 1)
        
        if self.mode == TransferMode.PARALLEL: self._run_parallel()
        else: self._run_direct()
        self.pool.waitForDone()
        
        if self.state == EngineState.STOPPING: self._cleanup_partials(); self.set_state(EngineState.IDLE); self.signals.job_finished.emit(); return
        if self.state == EngineState.PAUSED: return

        if self.operation == OperationType.MOVE and not self.failed_files:
            self.signals.log_msg.emit("Transfer complete. Finalizing Move...")
            try:
                for src_f, dst_f in self.files_to_process:
                    if src_f.exists(): src_f.unlink()
                if self.src_path.is_dir():
                    for root, dirs, files in os.walk(self.src_path, topdown=False):
                        for name in dirs:
                            try: os.rmdir(os.path.join(root, name))
                            except: pass
                    try: os.rmdir(self.src_path)
                    except: pass
                self.signals.log_msg.emit("Source files wiped. Move flawless.")
            except Exception as e: self.signals.log_msg.emit(f"<span style='color:#FF453A;'>Cleanup Error: {e}</span>")

        self.set_state(EngineState.IDLE)
        self.signals.job_finished.emit()

    def _run_parallel(self):
        for src, dst in self.files_to_process:
            if self.state != EngineState.COPYING: break
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
            if self.state != EngineState.COPYING: break
            self.signals.active_file.emit(src.name)
            offset = self.file_offsets.get(str(src), 0)
            dst.parent.mkdir(parents=True, exist_ok=True)
            self.active_destinations.add(str(dst))
            try:
                fsrc, fdst = get_direct_io(src, 'r'), get_direct_io(dst, 'a' if offset > 0 else 'w')
                if offset > 0: fsrc.seek(offset); fdst.seek(offset)
                while True:
                    if self.state in [EngineState.STOPPING, EngineState.PAUSED]:
                        if self.state == EngineState.PAUSED: self.save_offset(src, offset)
                        break
                    chunk = fsrc.read(DIRECT_CHUNK_SIZE)
                    if not chunk: break
                    fdst.write(chunk)
                    offset += len(chunk)
                    self._on_worker_progress(len(chunk))
                fsrc.close(); fdst.close()
                self._on_worker_finished(str(src), str(dst), True, "")
            except Exception as e: self._on_worker_finished(str(src), str(dst), False, str(e))

    def _cleanup_partials(self):
        with self.worker_lock:
            for dst_path in self.active_destinations:
                try: p = Path(dst_path); (p.unlink() if p.exists() else None)
                except: pass
            self.active_destinations.clear()

    @Slot(int)
    def _on_worker_progress(self, bytes_transferred):
        with self.worker_lock: self.transferred_bytes += bytes_transferred
        current_time = time.time()
        elapsed = current_time - self.last_update_time
        if elapsed > 0.2:
            instant_speed = (self.transferred_bytes - self.last_transferred) / elapsed
            self.speed_history.append(instant_speed)
            if len(self.speed_history) > 10: self.speed_history.pop(0)
            avg_speed = int(sum(self.speed_history) / len(self.speed_history))
            self.last_update_time, self.last_transferred = current_time, self.transferred_bytes
            eta = "Calculating..."
            if avg_speed > 0:
                secs = int((self.total_bytes - self.transferred_bytes) / avg_speed)
                if secs > 3600: eta = f"~ {secs//3600}h {(secs%3600)//60}m"
                elif secs > 60: eta = f"~ {secs//60} min"
                else: eta = f"~ {secs} sec"
            self.signals.progress_update.emit(self.transferred_bytes, self.total_bytes)
            self.signals.stats_update.emit(self.transferred_bytes, avg_speed, eta)

    @Slot(str, str, bool, str)
    def _on_worker_finished(self, src, dst, success, error_msg):
        with self.worker_lock:
            self.processed_count += 1
            if str(dst) in self.active_destinations: self.active_destinations.remove(str(dst))
            if not success: self.failed_files.append(src); self.signals.log_msg.emit(f"Error: {error_msg}")

# =====================================================================
# UI Components: Creative Liquid Live Graph
# =====================================================================

class LiquidSpeedGraph(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(70)
        self.points = [0] * 60  
        self.max_val = 1
        self.phase = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.wave_anim = QVariantAnimation()
        self.wave_anim.setDuration(3000)
        self.wave_anim.setStartValue(0.0)
        self.wave_anim.setEndValue(math.pi * 2)
        self.wave_anim.setLoopCount(-1)
        self.wave_anim.valueChanged.connect(self._update_phase)
        self.wave_anim.start()

    def _update_phase(self, val): self.phase = val; self.update()
    def update_data(self, val): self.points.pop(0); self.points.append(val); self.max_val = max(max(self.points), 1024*1024*10) 
    def reset(self): self.points = [0] * 60

    def _build_wave_path(self, w, h, step_x, phase_offset, amplitude_multiplier):
        path = QPainterPath(); path.moveTo(0, h)
        for i, val in enumerate(self.points):
            x = i * step_x
            ripple = math.sin(self.phase * 3 + i * 0.2 + phase_offset) * (4 * amplitude_multiplier)
            y = h - ((val / self.max_val) * h) + ripple
            y = max(2, min(h, y))
            if i == 0: path.lineTo(x, y)
            else:
                prev_x = (i - 1) * step_x
                prev_ripple = math.sin(self.phase * 3 + (i - 1) * 0.2 + phase_offset) * (4 * amplitude_multiplier)
                prev_y = h - ((self.points[i-1] / self.max_val) * h) + prev_ripple
                control_x = prev_x + (x - prev_x) / 2
                path.cubicTo(control_x, max(2, min(h, prev_y)), control_x, y, x, y)
        path.lineTo(w, h); path.closeSubpath(); return path

    def paintEvent(self, event):
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height(); step_x = w / (len(self.points) - 1)
        back_path = self._build_wave_path(w, h, step_x, 1.5, 1.2)
        grad_back = QLinearGradient(0, 0, 0, h); grad_back.setColorAt(0, QColor(0, 243, 255, 60)); grad_back.setColorAt(1, QColor(0, 243, 255, 0))
        painter.setBrush(QBrush(grad_back)); painter.setPen(Qt.PenStyle.NoPen); painter.drawPath(back_path)
        front_path = self._build_wave_path(w, h, step_x, 0, 0.8)
        grad_front = QLinearGradient(0, 0, 0, h); grad_front.setColorAt(0, QColor(0, 243, 255, 140)); grad_front.setColorAt(1, QColor(0, 243, 255, 0))
        painter.setBrush(QBrush(grad_front)); painter.setPen(QPen(QColor(0, 243, 255, 255), 2)); painter.drawPath(front_path)

# =====================================================================
# UI Components: Standard Elements
# =====================================================================

def format_size(bytes_size):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0: return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} PB"

class MacTitleBar(QWidget):
    def __init__(self, parent):
        super().__init__(parent); self.parent = parent; self.setFixedHeight(40)
        layout = QHBoxLayout(self); layout.setContentsMargins(16, 0, 16, 0)
        self.btn_close = self._create_dot("#FF5F56", "#E0443E"); self.btn_min = self._create_dot("#FFBD2E", "#DEA123"); self.btn_max = self._create_dot("#27C93F", "#1AAB29")
        self.btn_close.clicked.connect(self.parent.close); self.btn_min.clicked.connect(self.parent.showMinimized)
        layout.addWidget(self.btn_close); layout.addWidget(self.btn_min); layout.addWidget(self.btn_max); layout.addSpacing(15)
        
        logo_path = resource_path("logo.ico")
        if os.path.exists(logo_path):
            self.logo_lbl = QLabel(); self.logo_lbl.setPixmap(QIcon(logo_path).pixmap(18, 18)); layout.addWidget(self.logo_lbl); layout.addSpacing(5)
        
        self.title = QLabel("HyperMove - Elite Precision Edition")
        self.title.setFont(QFont("SF Pro Display", 11, QFont.Weight.Bold)); self.title.setStyleSheet("color: rgba(255, 255, 255, 0.7); letter-spacing: 1px;")
        layout.addWidget(self.title); layout.addStretch()

    def _create_dot(self, color, border_color):
        btn = QPushButton(); btn.setFixedSize(12, 12); btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setStyleSheet(f"QPushButton {{ background-color: {color}; border: 1px solid {border_color}; border-radius: 6px; }} QPushButton:hover {{ border: 1px solid rgba(255,255,255,0.5); }}")
        return btn

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton: 
            # Elite Native Smooth Dragging
            trigger_native_drag(self.parent)

class GlassCard(QFrame):
    def __init__(self): super().__init__(); self.setStyleSheet("GlassCard { background-color: rgba(255, 255, 255, 0.04); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 14px; }")

class AnimatedSmartDropZone(QFrame):
    path_dropped = Signal(str); browse_clicked = Signal(str); clear_clicked = Signal()
    def __init__(self, title, is_source=True):
        super().__init__(); self.is_source = is_source; self.setAcceptDrops(True); self.setFixedHeight(120 if is_source else 100)
        self.base_style = "AnimatedSmartDropZone { background-color: rgba(255, 255, 255, 0.02); border: 2px dashed rgba(255, 255, 255, 0.1); border-radius: 12px; }"
        self.setStyleSheet(self.base_style); self.layout = QGridLayout(self); self.view_empty = QWidget()
        empty_layout = QVBoxLayout(self.view_empty); empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl_prompt = QLabel(f"Drop {title} Here"); lbl_prompt.setFont(QFont("SF Pro Display", 11, QFont.Weight.Medium)); lbl_prompt.setStyleSheet("color: rgba(255,255,255,0.7);")
        btn_layout = QHBoxLayout(); btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if is_source:
            self.btn_file = self._create_btn("📄 File"); self.btn_file.clicked.connect(lambda: self.browse_clicked.emit('file')); btn_layout.addWidget(self.btn_file)
        self.btn_folder = self._create_btn("📁 Folder"); self.btn_folder.clicked.connect(lambda: self.browse_clicked.emit('folder')); btn_layout.addWidget(self.btn_folder)
        empty_layout.addWidget(lbl_prompt); empty_layout.addLayout(btn_layout)
        self.view_selected = QWidget(); sel_layout = QVBoxLayout(self.view_selected); sel_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_sel_icon = QLabel("📁"); self.lbl_sel_icon.setFont(QFont("SF Pro Display", 18)); self.lbl_sel_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_sel_name = QLabel("filename"); self.lbl_sel_name.setFont(QFont("SF Pro Text", 11, QFont.Weight.Bold)); self.lbl_sel_name.setStyleSheet("color: white;"); self.lbl_sel_name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_sel_info = QLabel("1.2 GB"); self.lbl_sel_info.setStyleSheet("color: rgba(255,255,255,0.5);"); self.lbl_sel_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_clear = self._create_btn("✕ Clear", is_clear=True); self.btn_clear.clicked.connect(self.clear_selection)
        sel_layout.addWidget(self.lbl_sel_icon); sel_layout.addWidget(self.lbl_sel_name); sel_layout.addWidget(self.lbl_sel_info); sel_layout.addWidget(self.btn_clear, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.layout.addWidget(self.view_empty, 0, 0); self.layout.addWidget(self.view_selected, 0, 0)
        self.eff_empty = QGraphicsOpacityEffect(self.view_empty); self.view_empty.setGraphicsEffect(self.eff_empty)
        self.eff_sel = QGraphicsOpacityEffect(self.view_selected); self.eff_sel.setOpacity(0.0); self.view_selected.setGraphicsEffect(self.eff_sel); self.view_selected.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.drag_pulse = QVariantAnimation(); self.drag_pulse.setDuration(500); self.drag_pulse.setStartValue(15); self.drag_pulse.setEndValue(70); self.drag_pulse.setLoopCount(-1); self.drag_pulse.valueChanged.connect(self._animate_drag_glow)

    def _create_btn(self, text, is_clear=False):
        btn = QPushButton(text); btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setStyleSheet(f"QPushButton {{ background-color: rgba(255,255,255,0.08); color: rgba(255,255,255,0.9); border: 1px solid rgba(255,255,255,0.15); border-radius: 12px; padding: 4px 14px; font-weight: 500; font-size:11px; }} QPushButton:hover {{ background-color: {'rgba(255,69,58,0.2)' if is_clear else 'rgba(0,243,255,0.15)'}; border: 1px solid {'rgba(255,69,58,0.5)' if is_clear else 'rgba(0,243,255,0.4)'}; }}")
        return btn

    def _animate_drag_glow(self, alpha): self.setStyleSheet(f"AnimatedSmartDropZone {{ background-color: rgba(0, 243, 255, {alpha/255.0}); border: 2px dashed rgba(0, 243, 255, {(alpha+80)/255.0}); border-radius: 12px; }}")
    def dragEnterEvent(self, event: QDragEnterEvent): 
        if event.mimeData().hasUrls(): self.drag_pulse.start(); event.acceptProposedAction()
    def dragLeaveEvent(self, event): self.drag_pulse.stop(); self.setStyleSheet(self.base_style)
    def dropEvent(self, event: QDropEvent):
        self.dragLeaveEvent(None); urls = event.mimeData().urls()
        if urls: self.set_path(urls[0].toLocalFile()); self.path_dropped.emit(urls[0].toLocalFile())

    def crossfade_view(self, show_selected):
        self.anim_group = QParallelAnimationGroup()
        a1 = QPropertyAnimation(self.eff_empty, b"opacity"); a1.setDuration(300); a1.setEndValue(0.0 if show_selected else 1.0)
        a2 = QPropertyAnimation(self.eff_sel, b"opacity"); a2.setDuration(300); a2.setEndValue(1.0 if show_selected else 0.0)
        self.anim_group.addAnimation(a1); self.anim_group.addAnimation(a2); self.anim_group.start()
        self.view_empty.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, show_selected); self.view_selected.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not show_selected)

    def set_path(self, path):
        p = Path(path); self.lbl_sel_icon.setText("📄" if p.is_file() else "📁"); self.lbl_sel_name.setText(p.name if len(p.name) < 35 else f"...{p.name[-30:]}")
        try:
            if self.is_source: self.lbl_sel_info.setText(format_size(p.stat().st_size if p.is_file() else sum(f.stat().st_size for f in p.rglob('*') if f.is_file())))
            else: self.lbl_sel_info.setText(f"Drive Free: {format_size(shutil.disk_usage(path).free)}")
        except: self.lbl_sel_info.setText("Size unknown")
        self.crossfade_view(True)

    def clear_selection(self): self.crossfade_view(False); self.clear_clicked.emit()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window); self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True); self.resize(880, 680)
        logo_path = resource_path("logo.ico")
        if os.path.exists(logo_path): self.setWindowIcon(QIcon(logo_path))
        self.setWindowOpacity(0.0); self.intro_anim = QPropertyAnimation(self, b"windowOpacity")
        self.intro_anim.setDuration(900); self.intro_anim.setStartValue(0.0); self.intro_anim.setEndValue(1.0); self.intro_anim.setEasingCurve(QEasingCurve.Type.OutCubic); self.intro_anim.start()
        self.engine = CopyEngine(); self.engine.signals.log_msg.connect(self.log_message); self.engine.signals.active_file.connect(self.update_active_file); self.engine.signals.progress_update.connect(self.update_progress); self.engine.signals.stats_update.connect(self.update_stats); self.engine.signals.state_changed.connect(self.on_state_changed); self.engine.signals.job_finished.connect(self.on_job_finished)
        self.src_path, self.dst_path = "", ""; self.current_operation = OperationType.COPY; self.init_ui()
        QTimer.singleShot(100, lambda: apply_native_window_blur(self.winId()))

    def init_ui(self):
        self.central_widget = QWidget(); self.setCentralWidget(self.central_widget); self.central_widget.setStyleSheet("QWidget#centralWidget { background-color: rgba(22, 22, 24, 185); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 16px; } QLabel { font-family: 'SF Pro Display', 'Segoe UI', Arial; }")
        self.central_widget.setObjectName("centralWidget"); shadow = QGraphicsDropShadowEffect(); shadow.setBlurRadius(60); shadow.setColor(QColor(0, 0, 0, 200)); shadow.setOffset(0, 25); self.central_widget.setGraphicsEffect(shadow)
        main_layout = QVBoxLayout(self.central_widget); main_layout.setContentsMargins(0, 0, 0, 0); self.title_bar = MacTitleBar(self); main_layout.addWidget(self.title_bar)
        content_layout = QHBoxLayout(); content_layout.setContentsMargins(25, 10, 25, 25); content_layout.setSpacing(20)
        left_panel = QVBoxLayout(); left_panel.setSpacing(12); self.src_drop = AnimatedSmartDropZone("Source Folder/Game"); self.src_drop.path_dropped.connect(self.set_source); self.src_drop.browse_clicked.connect(lambda t: self.browse_path(t, is_source=True)); self.src_drop.clear_clicked.connect(lambda: self.set_source(""))
        self.dst_drop = AnimatedSmartDropZone("Target Drive", is_source=False); self.dst_drop.path_dropped.connect(self.set_dest); self.dst_drop.browse_clicked.connect(lambda t: self.browse_path(t, is_source=False)); self.dst_drop.clear_clicked.connect(lambda: self.set_dest(""))
        self.log_text = QTextEdit(); self.log_text.setReadOnly(True); self.log_text.setStyleSheet("QTextEdit { background-color: rgba(0,0,0,0.15); border: 1px solid rgba(255,255,255,0.05); border-radius: 10px; color: rgba(255,255,255,0.6); font-family: 'SF Mono', 'Consolas', monospace; font-size: 10px; padding: 10px; }")
        left_panel.addWidget(self.src_drop); left_panel.addWidget(self.dst_drop); left_panel.addWidget(QLabel("SYSTEM LOG", styleSheet="color: rgba(255,255,255,0.3); font-size: 9px; font-weight: bold;")); left_panel.addWidget(self.log_text)
        right_panel = QVBoxLayout(); right_panel.setSpacing(15); dash_card = GlassCard(); dash_layout = QVBoxLayout(dash_card); dash_layout.setContentsMargins(0, 25, 0, 0) 
        self.lbl_speed = QLabel("0.0 MB/s"); self.lbl_speed.setFont(QFont("SF Pro Display", 48, QFont.Weight.Bold)); self.lbl_speed.setAlignment(Qt.AlignmentFlag.AlignCenter); self.lbl_speed.setStyleSheet("color: white; background: transparent;")
        self.speed_shadow = QGraphicsDropShadowEffect(); self.speed_shadow.setBlurRadius(20); self.speed_shadow.setColor(QColor(0, 243, 255, 60)); self.lbl_speed.setGraphicsEffect(self.speed_shadow)
        self.pulse_anim = QVariantAnimation(); self.pulse_anim.setDuration(800); self.pulse_anim.setStartValue(10.0); self.pulse_anim.setEndValue(40.0); self.pulse_anim.setLoopCount(-1); self.pulse_anim.valueChanged.connect(self.speed_shadow.setBlurRadius)
        
        # Telemetry Labels
        tel_layout = QGridLayout(); tel_layout.setContentsMargins(25, 0, 25, 0)
        self.lbl_active_file = QLabel("Ready to sync..."); self.lbl_active_file.setStyleSheet("color: #00F3FF; font-size: 10px; font-weight: 500;")
        self.lbl_transferred = QLabel("-- / --"); self.lbl_eta = QLabel("ETA: --")
        for lbl in [self.lbl_transferred, self.lbl_eta]: lbl.setFont(QFont("SF Pro Text", 11)); lbl.setStyleSheet("color: rgba(255, 255, 255, 0.6);")
        tel_layout.addWidget(self.lbl_active_file, 0, 0, 1, 2); tel_layout.addWidget(self.lbl_transferred, 1, 0); tel_layout.addWidget(self.lbl_eta, 1, 1, Qt.AlignmentFlag.AlignRight)
        
        self.graph = LiquidSpeedGraph(); self.progress_bar = QProgressBar(); self.progress_bar.setTextVisible(False); self.progress_bar.setFixedHeight(4); self.progress_bar.setStyleSheet("QProgressBar { background-color: rgba(255,255,255,0.05); border: none; } QProgressBar::chunk { background-color: #00F3FF; }")
        self.prog_anim = QPropertyAnimation(self.progress_bar, b"value"); self.prog_anim.setEasingCurve(QEasingCurve.Type.OutCubic); self.prog_anim.setDuration(400)
        dash_layout.addWidget(self.lbl_speed); dash_layout.addSpacing(10); dash_layout.addLayout(tel_layout); dash_layout.addSpacing(15); dash_layout.addWidget(self.graph); dash_layout.addWidget(self.progress_bar)
        
        controls_card = GlassCard(); controls_layout = QVBoxLayout(controls_card); controls_layout.setContentsMargins(20, 15, 20, 20)
        op_layout = QHBoxLayout(); self.btn_op_copy = QPushButton("COPY"); self.btn_op_move = QPushButton("MOVE")
        self.op_group = QButtonGroup(self); self.op_group.addButton(self.btn_op_copy, 0); self.op_group.addButton(self.btn_op_move, 1)
        for btn in [self.btn_op_copy, self.btn_op_move]:
            btn.setCheckable(True); btn.setFixedHeight(28); btn.setFont(QFont("SF Pro Text", 10, QFont.Weight.Bold)); btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn.setStyleSheet("QPushButton { background: rgba(255,255,255,0.05); color: rgba(255,255,255,0.4); border: 1px solid rgba(255,255,255,0.1); border-radius: 6px; } QPushButton:checked { background: rgba(0, 243, 255, 0.15); color: #00F3FF; border: 1px solid #00F3FF; }")
        self.btn_op_copy.setChecked(True); self.op_group.buttonClicked.connect(self.update_operation_mode); op_layout.addWidget(self.btn_op_copy); op_layout.addWidget(self.btn_op_move)
        
        settings_grid = QGridLayout(); lbl_conflict = QLabel("Conflict Handling:"); self.conflict_combo = QComboBox(); self.conflict_combo.addItems([c.value for c in ConflictPolicy])
        lbl_mode = QLabel("Hardware Profile:"); self.mode_combo = QComboBox(); self.mode_combo.addItems([m.value for m in TransferMode])
        for combo in [self.conflict_combo, self.mode_combo]: combo.setStyleSheet("QComboBox { background: rgba(0,0,0,0.2); color: white; border: 1px solid rgba(255,255,255,0.1); border-radius: 4px; padding: 2px 5px; font-size: 10px; }")
        settings_grid.addWidget(lbl_conflict, 0, 0); settings_grid.addWidget(self.conflict_combo, 0, 1); settings_grid.addWidget(lbl_mode, 1, 0); settings_grid.addWidget(self.mode_combo, 1, 1)

        btn_container = QWidget(); btn_container.setFixedHeight(45); btn_layout = QGridLayout(btn_container); btn_layout.setContentsMargins(0,0,0,0)
        self.btn_start = QPushButton("START COPY"); self.btn_start.setFont(QFont("SF Pro Text", 14, QFont.Weight.Bold)); self.btn_start.setCursor(QCursor(Qt.CursorShape.PointingHandCursor)); self.btn_start.setStyleSheet("QPushButton { background-color: #00F3FF; color: black; border-radius: 10px; } QPushButton:hover { background-color: #00D0FF; }")
        self.btn_open_dest = QPushButton("📂 Open Destination"); self.btn_open_dest.setFont(QFont("SF Pro Text", 13, QFont.Weight.Medium)); self.btn_open_dest.setStyleSheet("QPushButton { background-color: rgba(255,255,255,0.1); color: white; border-radius: 10px; border: 1px solid rgba(255,255,255,0.15); }")
        btn_layout.addWidget(self.btn_start, 0, 0); btn_layout.addWidget(self.btn_open_dest, 0, 0)
        self.eff_start = QGraphicsOpacityEffect(self.btn_start); self.btn_start.setGraphicsEffect(self.eff_start)
        self.eff_open = QGraphicsOpacityEffect(self.btn_open_dest); self.eff_open.setOpacity(0.0); self.btn_open_dest.setGraphicsEffect(self.eff_open); self.btn_open_dest.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        
        control_action_layout = QHBoxLayout(); self.btn_pause = self._make_sec_btn("Pause"); self.btn_resume = self._make_sec_btn("Resume"); self.btn_stop = self._make_sec_btn("Cancel", "#FF453A", "rgba(255,69,58,0.2)")
        for b in [self.btn_pause, self.btn_resume, self.btn_stop]: b.setEnabled(False); control_action_layout.addWidget(b)
        controls_layout.addLayout(op_layout); controls_layout.addSpacing(10); controls_layout.addLayout(settings_grid); controls_layout.addSpacing(15); controls_layout.addWidget(btn_container); controls_layout.addSpacing(10); controls_layout.addLayout(control_action_layout)
        right_panel.addWidget(dash_card); right_panel.addWidget(controls_card); content_layout.addLayout(left_panel, 45); content_layout.addLayout(right_panel, 55); main_layout.addLayout(content_layout)
        self.btn_start.clicked.connect(self.start_transfer); self.btn_open_dest.clicked.connect(self.open_destination); self.btn_pause.clicked.connect(lambda: self.engine.set_state(EngineState.PAUSED)); self.btn_resume.clicked.connect(lambda: [self.engine.set_state(EngineState.RESUMING), self.engine.start()]); self.btn_stop.clicked.connect(self.stop_transfer)

    def _make_sec_btn(self, text, hover_color="#ffffff", hover_bg="rgba(255,255,255,0.1)"):
        btn = QPushButton(text); btn.setFixedHeight(30); btn.setStyleSheet(f"QPushButton {{ background: rgba(255,255,255,0.05); color: rgba(255,255,255,0.8); border: 1px solid rgba(255,255,255,0.08); border-radius: 6px; font-size: 11px;}} QPushButton:hover {{ background: {hover_bg}; color: {hover_color}; }}"); return btn

    def browse_path(self, browse_type, is_source):
        path = QFileDialog.getOpenFileName(self, "Select Source")[0] if browse_type == 'file' else QFileDialog.getExistingDirectory(self, "Select Folder")
        if path: (self.src_drop if is_source else self.dst_drop).set_path(path); self.set_source(path) if is_source else self.set_dest(path)

    def set_source(self, path): self.src_path = path; self.reset_action_buttons()
    def set_dest(self, path): self.dst_path = path; self.reset_action_buttons()
    @Slot(str)
    def update_active_file(self, name): self.lbl_active_file.setText(f"Active: {name}")

    @Slot(str)
    def log_message(self, msg):
        ts = time.strftime("%H:%M:%S"); self.log_text.append(f"<span style='color:rgba(255,255,255,0.3);'>[{ts}]</span> {msg}"); self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    @Slot(int, int)
    def update_progress(self, transferred, total):
        if total > 0: self.prog_anim.setEndValue(int((transferred / total) * 100)); self.prog_anim.start(); self.lbl_transferred.setText(f"{format_size(transferred)} / {format_size(total)}")

    @Slot(int, int, str)
    def update_stats(self, transferred, speed, eta):
        self.graph.update_data(speed); mb_speed = speed / (1024*1024); self.lbl_speed.setText(f"{mb_speed/1024:.2f} GB/s" if mb_speed > 1024 else f"{mb_speed:.1f} MB/s"); self.lbl_eta.setText(f"ETA: {eta}")

    @Slot(EngineState)
    def on_state_changed(self, state):
        self.btn_start.setEnabled(state == EngineState.IDLE); self.btn_pause.setEnabled(state == EngineState.COPYING)
        self.btn_resume.setEnabled(state == EngineState.PAUSED); self.btn_stop.setEnabled(state in [EngineState.COPYING, EngineState.PAUSED, EngineState.RESUMING])
        self.src_drop.setEnabled(state == EngineState.IDLE); self.dst_drop.setEnabled(state == EngineState.IDLE)
        if state == EngineState.COPYING: self.graph.reset(); self.pulse_anim.start(); self.reset_action_buttons()
        elif state == EngineState.IDLE: self.pulse_anim.stop(); self.speed_shadow.setBlurRadius(20); self.lbl_active_file.setText("Engine Idle")

    @Slot()
    def on_job_finished(self):
        if self.engine.state != EngineState.STOPPING: self.prog_anim.setEndValue(100); self.prog_anim.start(); self.lbl_speed.setText("Done"); self.log_message(f"<span style='color:#00F3FF;'>Sync Complete: {self.current_operation.name} finished.</span>"); self.crossfade_main_buttons(show_open=True)

    def crossfade_main_buttons(self, show_open):
        self.main_btn_anim = QParallelAnimationGroup()
        a1 = QPropertyAnimation(self.eff_start, b"opacity"); a1.setDuration(400); a1.setEndValue(0.0 if show_open else 1.0)
        a2 = QPropertyAnimation(self.eff_open, b"opacity"); a2.setDuration(400); a2.setEndValue(1.0 if show_open else 0.0)
        self.main_btn_anim.addAnimation(a1); self.main_btn_anim.addAnimation(a2); self.main_btn_anim.start()
        self.btn_start.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, show_open); self.btn_open_dest.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not show_open)

    def update_operation_mode(self, btn):
        self.current_operation = OperationType.COPY if btn == self.btn_op_copy else OperationType.MOVE
        self.btn_start.setText(f"START {self.current_operation.name}")
        color = '#00F3FF' if self.current_operation == OperationType.COPY else '#FF2E93'
        self.btn_start.setStyleSheet(f"QPushButton {{ background-color: {color}; color: {'black' if self.current_operation == OperationType.COPY else 'white'}; border-radius: 10px; }}")

    def reset_action_buttons(self):
        if self.eff_start.opacity() < 1.0: self.crossfade_main_buttons(show_open=False)

    def open_destination(self):
        if not self.dst_path: return
        path = str(Path(self.dst_path).absolute())
        try:
            if sys.platform == 'win32': os.startfile(path)
            elif sys.platform == 'darwin': subprocess.Popen(['open', path])
            else: subprocess.Popen(['xdg-open', path])
        except Exception as e: self.log_message(f"Could not open: {e}")

    def start_transfer(self):
        if not self.src_path or not self.dst_path: return QMessageBox.warning(self, "Selection", "Select paths.")
        if os.path.abspath(self.src_path) == os.path.abspath(self.dst_path): return QMessageBox.warning(self, "Invalid", "Paths cannot match.")
        mode = next(m for m in TransferMode if m.value == self.mode_combo.currentText())
        conflict = next(c for c in ConflictPolicy if c.value == self.conflict_combo.currentText())
        self.progress_bar.setValue(0); self.engine.prepare_job(self.src_path, self.dst_path, mode, self.current_operation, conflict, 16); self.engine.start()

    def stop_transfer(self):
        if QMessageBox.question(self, "Cancel", "Abort?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes: self.engine.set_state(EngineState.STOPPING)

def main():
    app = QApplication(sys.argv)
    logo_path = resource_path("logo.ico")
    if os.path.exists(logo_path): app.setWindowIcon(QIcon(logo_path))
    window = MainWindow(); window.show(); sys.exit(app.exec())

if __name__ == "__main__":
    main()
