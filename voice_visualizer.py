"""Audio-reactive 3D geometric Voice Avatar visualizer & autohide Full-Screen / Windowed stage."""
from __future__ import annotations

import math
import time
from typing import Any

import numpy as np
from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QGuiApplication,
    QImage,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
    QShortcut,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from voice_service import get_tts_audio_telemetry


AVATAR_MODES: list[tuple[str, str]] = [
    ("no_avatar", "No Avatar (Off)"),
    ("windowed", "Windowed (Floating)"),
    ("fullscreen", "Full Screen Stage"),
]

AVATAR_SHAPES: list[tuple[str, str]] = [
    ("neural_core", "Crystalline Neural Core"),
    ("tesseract", "4D Tesseract Hypercube"),
    ("astrolabe", "Celestial Astrolabe Gyro"),
    ("torus_knot", "Harmonic Torus Knot"),
    ("swarm", "Swarm Constellation"),
    ("mandala", "Acoustic Sacred Mandala"),
]

AVATAR_PALETTES: list[tuple[str, str]] = [
    ("tulsa_cyan", "Tulsa Cyan"),
    ("jarvis_amber", "JARVIS Amber"),
    ("emerald_holo", "Emerald Holo"),
    ("nebula_violet", "Nebula Violet"),
    ("theme_accent", "Match Active Theme"),
    ("auto_ai", "Auto-Tint by Active AI"),
]

_FIXED_PALETTES: dict[str, dict[str, str]] = {
    "tulsa_cyan": {
        "core": "#ecfeff",
        "primary": "#38e8ff",
        "secondary": "#0891b2",
        "glow": "#06b6d4",
        "bg": "#030608",
    },
    "jarvis_amber": {
        "core": "#fffbeb",
        "primary": "#ffb000",
        "secondary": "#d97706",
        "glow": "#f59e0b",
        "bg": "#060402",
    },
    "emerald_holo": {
        "core": "#ecfdf5",
        "primary": "#34d399",
        "secondary": "#059669",
        "glow": "#10b981",
        "bg": "#020705",
    },
    "nebula_violet": {
        "core": "#f5f3ff",
        "primary": "#c084fc",
        "secondary": "#7c3aed",
        "glow": "#a855f7",
        "bg": "#05030a",
    },
}


def resolve_avatar_palette(
    palette_id: str = "tulsa_cyan",
    theme_dict: dict[str, Any] | None = None,
    provider_color_hex: str = "",
) -> dict[str, str]:
    """Return concrete core/primary/secondary/glow/bg hex colors for the chosen avatar palette."""
    pid = (palette_id or "tulsa_cyan").strip().lower()
    if pid == "auto_ai" and provider_color_hex:
        c = QColor(str(provider_color_hex))
        if c.isValid():
            return {
                "core": c.lighter(155).name(),
                "primary": c.name(),
                "secondary": c.darker(150).name(),
                "glow": c.name(),
                "bg": "#030608",
            }
    if pid == "theme_accent" and isinstance(theme_dict, dict):
        acc = str(theme_dict.get("send_bg") or theme_dict.get("user_bubble_border") or "#38e8ff")
        c = QColor(acc)
        if c.isValid():
            return {
                "core": c.lighter(155).name(),
                "primary": c.name(),
                "secondary": c.darker(145).name(),
                "glow": c.name(),
                "bg": "#030608",
            }
    return dict(_FIXED_PALETTES.get(pid, _FIXED_PALETTES["tulsa_cyan"]))


def _rotation_matrix_xyz(ax: float, ay: float, az: float) -> np.ndarray:
    cx, sx = math.cos(ax), math.sin(ax)
    cy, sy = math.cos(ay), math.sin(ay)
    cz, sz = math.cos(az), math.sin(az)
    rx = np.array([[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]], dtype=np.float32)
    ry = np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]], dtype=np.float32)
    rz = np.array([[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]], dtype=np.float32)
    return (rz @ ry @ rx).astype(np.float32)


def _build_neural_core_geometry() -> dict[str, Any]:
    """Build deterministic multi-shell irregular crystalline web + rim spike clusters + corona rays."""
    rng = np.random.default_rng(19990406)
    pts: list[np.ndarray] = []

    # Fibonacci sphere samples across 3 density shells for crystalline volumetric depth
    shells = [(48, 0.28, 0.44), (92, 0.50, 0.78), (112, 0.80, 1.04)]
    golden = math.pi * (3.0 - math.sqrt(5.0))
    for count, r_lo, r_hi in shells:
        for i in range(count):
            y = 1.0 - (i / float(max(1, count - 1))) * 2.0
            rad_xy = math.sqrt(max(0.0, 1.0 - y * y))
            theta = golden * i + float(rng.uniform(-0.18, 0.18))
            r = float(rng.uniform(r_lo, r_hi))
            jitter = rng.normal(0.0, 0.055, size=3)
            v = np.array([math.cos(theta) * rad_xy, y, math.sin(theta) * rad_xy], dtype=np.float32) * r + jitter.astype(np.float32)
            pts.append(v)

    verts = np.vstack(pts).astype(np.float32)
    n = verts.shape[0]
    diff = verts[:, None, :] - verts[None, :, :]
    dist = np.linalg.norm(diff, axis=2)

    edges: set[tuple[int, int]] = set()
    # Connect each vertex to nearest local neighbors + a few long cross-lattice chords
    for i in range(n):
        order = np.argsort(dist[i])
        k_near = 4 if np.linalg.norm(verts[i]) > 0.72 else 3
        for j in order[1 : 1 + k_near]:
            if dist[i, j] <= 0.62:
                a, b = (int(i), int(j)) if i < j else (int(j), int(i))
                edges.add((a, b))
        # Subtle internal crystalline chords crossing the core
        if i % 3 == 0:
            j = int(order[min(n - 1, int(rng.integers(12, 34)))])
            if i != j:
                a, b = (int(i), int(j)) if i < j else (int(j), int(i))
                edges.add((a, b))

    edge_arr = np.array(sorted(edges), dtype=np.int32)
    radii = np.linalg.norm(verts, axis=1)
    # Corona rays around perimeter
    ray_angles = np.linspace(0.0, 2.0 * math.pi, 96, endpoint=False, dtype=np.float32)
    ray_weights = rng.uniform(0.55, 1.25, size=96).astype(np.float32)
    return {
        "verts": verts,
        "edges": edge_arr,
        "radii": radii,
        "ray_angles": ray_angles,
        "ray_weights": ray_weights,
    }


def _build_tesseract_geometry() -> dict[str, Any]:
    """16 vertices & 32 edges of a 4D hypercube plus outer octahedral crystalline shell."""
    verts4 = np.array(
        [[(1.0 if (i >> b) & 1 else -1.0) * 0.68 for b in range(4)] for i in range(16)],
        dtype=np.float32,
    )
    edges4: list[tuple[int, int]] = []
    for i in range(16):
        for b in range(4):
            j = i ^ (1 << b)
            if i < j:
                edges4.append((i, j))
    shell_verts = np.array(
        [
            [1.05, 0.0, 0.0], [-1.05, 0.0, 0.0],
            [0.0, 1.05, 0.0], [0.0, -1.05, 0.0],
            [0.0, 0.0, 1.05], [0.0, 0.0, -1.05],
        ],
        dtype=np.float32,
    )
    shell_edges = np.array(
        [
            (0, 2), (0, 3), (0, 4), (0, 5),
            (1, 2), (1, 3), (1, 4), (1, 5),
            (2, 4), (4, 3), (3, 5), (5, 2),
        ],
        dtype=np.int32,
    )
    return {
        "verts4": verts4,
        "edges4": np.array(edges4, dtype=np.int32),
        "shell_verts": shell_verts,
        "shell_edges": shell_edges,
    }


def _build_torus_knot_geometry() -> dict[str, Any]:
    """Precompute parametric (3, 5) torus knot + secondary phase strand."""
    t = np.linspace(0.0, 2.0 * math.pi, 180, endpoint=False, dtype=np.float32)
    return {"t": t}


def _build_swarm_geometry() -> dict[str, Any]:
    rng = np.random.default_rng(202604)
    n = 148
    golden = math.pi * (3.0 - math.sqrt(5.0))
    pts: list[list[float]] = []
    for i in range(n):
        y = 1.0 - (i / float(n - 1)) * 2.0
        r_xy = math.sqrt(max(0.0, 1.0 - y * y))
        th = golden * i
        r = float(rng.uniform(0.32, 0.96))
        pts.append([math.cos(th) * r_xy * r, y * r, math.sin(th) * r_xy * r])
    verts = np.array(pts, dtype=np.float32)
    phases = rng.uniform(0.0, 2.0 * math.pi, size=n).astype(np.float32)
    return {"verts": verts, "phases": phases}


class VoiceAvatarCanvas(QWidget):
    """60fps CPU-efficient PySide6 + NumPy 3D geometric voice avatar renderer."""

    hologram_clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(180, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._shape_id = "neural_core"
        self._palette_id = "tulsa_cyan"
        self._theme_dict: dict[str, Any] = {}
        self._provider_color = ""
        self._state = "idle"  # "idle" | "listening" | "thinking" | "speaking"
        self._muted = False
        self._mic_level = 0.0
        self._speech_detected = False
        self._mic_decay_ts = 0.0

        self._smooth_rms = 0.0
        self._smooth_mic = 0.0
        self._smooth_bands = np.zeros(16, dtype=np.float32)
        self._phase = 0.0
        self._last_tick = time.monotonic()

        self._geom_neural = _build_neural_core_geometry()
        self._geom_tesseract = _build_tesseract_geometry()
        self._geom_torus = _build_torus_knot_geometry()
        self._geom_swarm = _build_swarm_geometry()

        self._bloom_img = QImage(160, 160, QImage.Format.Format_ARGB32_Premultiplied)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._on_tick)

    def set_shape(self, shape_id: str) -> None:
        valid = {sid for sid, _ in AVATAR_SHAPES}
        self._shape_id = shape_id if shape_id in valid else "neural_core"
        self.update()

    def set_palette_config(self, palette_id: str, theme_dict: dict[str, Any] | None = None, provider_color_hex: str = "") -> None:
        self._palette_id = palette_id or "tulsa_cyan"
        if isinstance(theme_dict, dict):
            self._theme_dict = dict(theme_dict)
        if provider_color_hex is not None:
            self._provider_color = str(provider_color_hex or "")
        self.update()

    def set_interaction_state(
        self,
        state: str | None = None,
        *,
        mic_level: float | None = None,
        speech_detected: bool | None = None,
        muted: bool | None = None,
    ) -> None:
        if state in {"idle", "listening", "thinking", "speaking"}:
            self._state = state
        if mic_level is not None:
            self._mic_level = max(0.0, min(1.0, float(mic_level)))
            self._mic_decay_ts = time.monotonic()
        if speech_detected is not None:
            self._speech_detected = bool(speech_detected)
        if muted is not None:
            self._muted = bool(muted)

    def start_animation(self) -> None:
        self._last_tick = time.monotonic()
        if not self._timer.isActive():
            self._timer.start()

    def stop_animation(self) -> None:
        if self._timer.isActive():
            self._timer.stop()

    def showEvent(self, event):
        super().showEvent(event)
        self.start_animation()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.stop_animation()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            cx, cy = self.width() * 0.5, self.height() * 0.5
            r = min(self.width(), self.height()) * 0.42
            dx = event.position().x() - cx
            dy = event.position().y() - cy
            if (dx * dx + dy * dy) <= (r * r):
                self.hologram_clicked.emit()
                event.accept()
                return
        super().mousePressEvent(event)

    def step_simulation(self, dt: float | None = None, telemetry: dict[str, Any] | None = None) -> dict[str, Any]:
        """Advance smooth physics + FFT reactivity one frame; returns current active visual state."""
        now = time.monotonic()
        if dt is None:
            dt = max(0.004, min(0.06, now - self._last_tick))
        self._last_tick = now

        telem = telemetry if telemetry is not None else get_tts_audio_telemetry()
        tts_speaking = bool(telem.get("speaking"))
        target_rms = float(telem.get("rms") or 0.0) if tts_speaking else 0.0
        raw_bands = telem.get("bands") or [0.0] * 16
        target_bands = np.array(raw_bands[:16], dtype=np.float32) if tts_speaking else np.zeros(16, dtype=np.float32)
        if target_bands.size < 16:
            target_bands = np.pad(target_bands, (0, 16 - target_bands.size))

        mic_fresh = (now - self._mic_decay_ts) <= 0.35
        target_mic = 0.0 if (self._muted or not mic_fresh) else self._mic_level

        # Fast attack, smooth organic release (eliminates jitter without feeling sluggish)
        atk_rms = 0.42 if target_rms > self._smooth_rms else 0.14
        self._smooth_rms += (target_rms - self._smooth_rms) * atk_rms
        atk_mic = 0.36 if target_mic > self._smooth_mic else 0.12
        self._smooth_mic += (target_mic - self._smooth_mic) * atk_mic
        atk_bands = np.where(target_bands > self._smooth_bands, 0.44, 0.15).astype(np.float32)
        self._smooth_bands += (target_bands - self._smooth_bands) * atk_bands

        if tts_speaking or self._smooth_rms > 0.02:
            eff_state = "speaking"
            speed_mul = 1.15 + self._smooth_rms * 1.45
        elif self._state == "thinking":
            eff_state = "thinking"
            speed_mul = 2.05
        elif self._state == "listening" and not self._muted:
            eff_state = "listening"
            speed_mul = 0.72 + self._smooth_mic * 0.9
        else:
            eff_state = "idle"
            speed_mul = 0.45

        self._phase += dt * speed_mul
        return {
            "effective_state": eff_state,
            "rms": float(self._smooth_rms),
            "mic": float(self._smooth_mic),
        }

    def _on_tick(self) -> None:
        self.step_simulation()
        self.update()

    def render_frame(self, painter: QPainter, state_override: str | None = None) -> None:
        """Render one complete frame onto `painter` (used both by paintEvent and offscreen unit tests)."""
        pal = resolve_avatar_palette(self._palette_id, self._theme_dict, self._provider_color)
        w = max(1, self.width())
        h = max(1, self.height())
        painter.fillRect(0, 0, w, h, QColor(pal["bg"]))

        eff_state = state_override or (
            "speaking"
            if self._smooth_rms > 0.02
            else (self._state if self._state in {"thinking", "listening"} else "idle")
        )
        cx, cy = w * 0.5, h * 0.48
        scale = min(w, h) * 0.34

        c_core = QColor(pal["core"])
        c_pri = QColor(pal["primary"])
        c_sec = QColor(pal["secondary"])
        c_glow = QColor(pal["glow"])

        energy = float(self._smooth_rms)
        mic_e = float(self._smooth_mic) if not self._muted else 0.0
        bands = self._smooth_bands

        # 1. Soft radial bloom + directional corona bursts in a compact offscreen QImage
        self._draw_corona_bloom(painter, cx, cy, scale, c_core, c_pri, c_glow, energy, mic_e, eff_state, bands)

        # 2. Additive crystalline geometry layer
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)

        sid = self._shape_id
        if sid == "tesseract":
            self._paint_tesseract(painter, cx, cy, scale, c_core, c_pri, c_sec, energy, mic_e, eff_state, bands)
        elif sid == "astrolabe":
            self._paint_astrolabe(painter, cx, cy, scale, c_core, c_pri, c_sec, energy, mic_e, eff_state, bands)
        elif sid == "torus_knot":
            self._paint_torus_knot(painter, cx, cy, scale, c_core, c_pri, c_sec, energy, mic_e, eff_state, bands)
        elif sid == "swarm":
            self._paint_swarm(painter, cx, cy, scale, c_core, c_pri, c_sec, energy, mic_e, eff_state, bands)
        elif sid == "mandala":
            self._paint_mandala(painter, cx, cy, scale, c_core, c_pri, c_sec, energy, mic_e, eff_state, bands)
        else:
            self._paint_neural_core(painter, cx, cy, scale, c_core, c_pri, c_sec, energy, mic_e, eff_state, bands)
        painter.restore()

    def paintEvent(self, event):
        painter = QPainter(self)
        self.render_frame(painter)
        painter.end()

    def _draw_corona_bloom(
        self,
        painter: QPainter,
        cx: float,
        cy: float,
        scale: float,
        c_core: QColor,
        c_pri: QColor,
        c_glow: QColor,
        energy: float,
        mic_e: float,
        eff_state: str,
        bands: np.ndarray,
    ) -> None:
        bw = self._bloom_img.width()
        bh = self._bloom_img.height()
        self._bloom_img.fill(Qt.GlobalColor.transparent)
        bp = QPainter(self._bloom_img)
        bp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)

        bc = bw * 0.5
        br = bw * 0.44 * (1.0 + 0.14 * energy + 0.06 * mic_e)
        grad = QRadialGradient(bc, bc, br)
        alpha_mid = int(min(185, 58 + energy * 105 + mic_e * 35))
        grad.setColorAt(0.0, QColor(c_core.red(), c_core.green(), c_core.blue(), min(220, alpha_mid + 40)))
        grad.setColorAt(0.45, QColor(c_pri.red(), c_pri.green(), c_pri.blue(), alpha_mid))
        grad.setColorAt(0.80, QColor(c_glow.red(), c_glow.green(), c_glow.blue(), max(14, alpha_mid // 4)))
        grad.setColorAt(1.0, QColor(c_glow.red(), c_glow.green(), c_glow.blue(), 0))
        bp.setBrush(grad)
        bp.setPen(Qt.PenStyle.NoPen)
        bp.drawEllipse(QPointF(bc, bc), br, br)

        # Volumetric soft angular light streaks radiating outward with 16-band FFT
        angles = self._geom_neural["ray_angles"]
        weights = self._geom_neural["ray_weights"]
        t = self._phase
        n_rays = len(angles)
        for i in range(n_rays):
            ang = float(angles[i]) + t * 0.12
            b_idx = i % 16
            band_e = float(bands[b_idx])
            if eff_state == "speaking":
                ray_len = br * (0.76 + 0.34 * band_e + 0.14 * energy) * float(weights[i])
                a_ray = int(min(92, 18 + band_e * 72))
            elif eff_state == "thinking":
                pulse = 0.5 + 0.5 * math.sin(ang * 4.0 - t * 4.5)
                ray_len = br * (0.70 + 0.18 * pulse) * float(weights[i])
                a_ray = int(14 + 34 * pulse)
            elif eff_state == "listening":
                ray_len = br * (0.72 + 0.20 * mic_e) * float(weights[i])
                a_ray = int(14 + 36 * mic_e)
            else:
                breath = 0.5 + 0.5 * math.sin(t * 1.4 + ang * 2.0)
                ray_len = br * (0.64 + 0.10 * breath) * float(weights[i])
                a_ray = int(12 + 12 * breath)
            x0 = bc + math.cos(ang) * (br * 0.42)
            y0 = bc + math.sin(ang) * (br * 0.42)
            x1 = bc + math.cos(ang) * ray_len
            y1 = bc + math.sin(ang) * ray_len
            pen = QPen(QColor(c_pri.red(), c_pri.green(), c_pri.blue(), a_ray), 2.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            bp.setPen(pen)
            bp.drawLine(QPointF(x0, y0), QPointF(x1, y1))
        bp.end()

        span = scale * 2.95
        target_rect = QRectF(cx - span * 0.5, cy - span * 0.5, span, span)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(target_rect, self._bloom_img)
        painter.restore()

    def _project(self, pts: np.ndarray, cx: float, cy: float, scale: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        z = pts[:, 2]
        persp = 3.2 / np.maximum(0.85, 3.2 - z)
        sx = cx + pts[:, 0] * scale * persp
        sy = cy + pts[:, 1] * scale * persp
        return sx, sy, z

    def _paint_neural_core(
        self,
        painter: QPainter,
        cx: float,
        cy: float,
        scale: float,
        c_core: QColor,
        c_pri: QColor,
        c_sec: QColor,
        energy: float,
        mic_e: float,
        eff_state: str,
        bands: np.ndarray,
    ) -> None:
        t = self._phase
        verts = self._geom_neural["verts"]
        edges = self._geom_neural["edges"]
        radii = self._geom_neural["radii"]

        rot = _rotation_matrix_xyz(t * 0.24, t * 0.37, t * 0.13)
        r_pts = verts @ rot.T

        if eff_state == "speaking":
            band_idx = (np.arange(r_pts.shape[0]) % 16)
            disp = 1.0 + bands[band_idx] * 0.26 * (0.4 + radii) + energy * 0.14
            r_pts = r_pts * disp[:, None]
        elif eff_state == "thinking":
            squeeze = 0.86 + 0.06 * math.sin(t * 4.2)
            r_pts = r_pts * squeeze
        elif eff_state == "listening":
            ripple = 1.0 - 0.08 * mic_e + 0.07 * mic_e * np.sin(radii * 6.0 - t * 6.0)
            r_pts = r_pts * ripple[:, None]
        else:
            breath = 1.0 + 0.035 * math.sin(t * 1.6)
            r_pts = r_pts * breath

        sx, sy, sz = self._project(r_pts, cx, cy, scale)

        # Draw chords with depth-weighted cyan/ice-white additive blending
        i0 = edges[:, 0]
        i1 = edges[:, 1]
        z_mid = (sz[i0] + sz[i1]) * 0.5
        for idx in range(edge_arr_len := edges.shape[0]):
            a = int(i0[idx])
            b = int(i1[idx])
            zm = float(z_mid[idx])
            depth_t = max(0.0, min(1.0, (zm + 1.05) * 0.48))
            if eff_state == "thinking":
                wave = 0.5 + 0.5 * math.sin(idx * 0.17 - t * 8.0)
                alpha = int(34 + depth_t * 78 + wave * 64)
            else:
                alpha = int(min(175, 28 + depth_t * 88 + energy * 52 + mic_e * 24))
            if depth_t > 0.72:
                col = QColor(c_core.red(), c_core.green(), c_core.blue(), alpha)
                pw = 1.15
            else:
                col = QColor(c_pri.red(), c_pri.green(), c_pri.blue(), alpha)
                pw = 0.85
            painter.setPen(QPen(col, pw))
            painter.drawLine(QPointF(float(sx[a]), float(sy[a])), QPointF(float(sx[b]), float(sy[b])))

        # Crisp sparkling vertex nodes around rim & crystal junctions
        painter.setPen(Qt.PenStyle.NoPen)
        for v_i in range(0, len(sx), 2):
            depth_t = max(0.0, min(1.0, (float(sz[v_i]) + 1.0) * 0.5))
            if radii[v_i] < 0.52 and depth_t < 0.6:
                continue
            alpha = int(min(220, 65 + depth_t * 110 + energy * 55))
            rad = 1.3 + depth_t * 1.4 + float(bands[v_i % 16]) * 1.4
            painter.setBrush(QColor(c_core.red(), c_core.green(), c_core.blue(), alpha))
            painter.drawEllipse(QPointF(float(sx[v_i]), float(sy[v_i])), rad, rad)

    def _paint_tesseract(
        self,
        painter: QPainter,
        cx: float,
        cy: float,
        scale: float,
        c_core: QColor,
        c_pri: QColor,
        c_sec: QColor,
        energy: float,
        mic_e: float,
        eff_state: str,
        bands: np.ndarray,
    ) -> None:
        t = self._phase
        v4 = self._geom_tesseract["verts4"].copy()
        a_xw = t * (0.95 if eff_state != "thinking" else 1.8)
        a_yw = t * 0.62
        a_zw = t * (0.45 + float(bands[4]) * 0.35)

        # Rotate in 4D planes (XW, YW, ZW)
        cxw, sxw = math.cos(a_xw), math.sin(a_xw)
        x_new = v4[:, 0] * cxw - v4[:, 3] * sxw
        w_new = v4[:, 0] * sxw + v4[:, 3] * cxw
        v4[:, 0], v4[:, 3] = x_new, w_new

        cyw, syw = math.cos(a_yw), math.sin(a_yw)
        y_new = v4[:, 1] * cyw - v4[:, 3] * syw
        w_new = v4[:, 1] * syw + v4[:, 3] * cyw
        v4[:, 1], v4[:, 3] = y_new, w_new

        czw, szw = math.cos(a_zw), math.sin(a_zw)
        z_new = v4[:, 2] * czw - v4[:, 3] * szw
        w_new = v4[:, 2] * szw + v4[:, 3] * czw
        v4[:, 2], v4[:, 3] = z_new, w_new

        # 4D -> 3D stereographic projection + energy scaling
        w_scale = 2.4 / np.maximum(0.85, 2.5 - v4[:, 3] * (0.75 + energy * 0.25))
        pts3 = v4[:, :3] * w_scale[:, None] * (0.86 + energy * 0.22 - mic_e * 0.06)
        rot = _rotation_matrix_xyz(t * 0.28, t * 0.41, t * 0.16)
        pts3 = pts3 @ rot.T
        sx, sy, sz = self._project(pts3, cx, cy, scale)

        # Outer octahedron shell
        sh3 = self._geom_tesseract["shell_verts"] @ _rotation_matrix_xyz(-t * 0.18, -t * 0.26, t * 0.12).T
        sh3 = sh3 * (1.06 + float(bands[1]) * 0.16 + mic_e * 0.06)
        ssx, ssy, _ = self._project(sh3, cx, cy, scale)
        painter.setPen(QPen(QColor(c_sec.red(), c_sec.green(), c_sec.blue(), 110), 1.3))
        for a, b in self._geom_tesseract["shell_edges"]:
            painter.drawLine(QPointF(float(ssx[a]), float(ssy[a])), QPointF(float(ssx[b]), float(ssy[b])))

        # Inner hypercube edges
        for idx, (a, b) in enumerate(self._geom_tesseract["edges4"]):
            depth_t = max(0.0, min(1.0, (float(sz[a] + sz[b]) * 0.5 + 1.0) * 0.5))
            b_boost = float(bands[idx % 16])
            alpha = int(min(245, 110 + depth_t * 90 + b_boost * 65))
            col = c_core if (b_boost > 0.45 or depth_t > 0.72) else c_pri
            painter.setPen(QPen(QColor(col.red(), col.green(), col.blue(), alpha), 1.6 + b_boost * 1.5))
            painter.drawLine(QPointF(float(sx[a]), float(sy[a])), QPointF(float(sx[b]), float(sy[b])))

        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(16):
            rad = 2.6 + float(bands[i]) * 2.8
            painter.setBrush(QColor(c_core.red(), c_core.green(), c_core.blue(), 220))
            painter.drawEllipse(QPointF(float(sx[i]), float(sy[i])), rad, rad)

    def _paint_astrolabe(
        self,
        painter: QPainter,
        cx: float,
        cy: float,
        scale: float,
        c_core: QColor,
        c_pri: QColor,
        c_sec: QColor,
        energy: float,
        mic_e: float,
        eff_state: str,
        bands: np.ndarray,
    ) -> None:
        t = self._phase
        theta = np.linspace(0.0, 2.0 * math.pi, 72, endpoint=False, dtype=np.float32)
        ring_specs = [
            (0.98, 0.32 * t, 0.51 * t, 0.18 * t, c_pri, 1.8),
            (0.84, -0.45 * t, 0.27 * t, 0.40 * t, c_core, 1.5),
            (0.68, 0.58 * t, -0.39 * t, -0.25 * t, c_sec, 1.4),
            (0.50, -0.72 * t, -0.61 * t, 0.53 * t, c_core, 1.2),
        ]
        for r_idx, (rad_base, ax, ay, az, col, lw) in enumerate(ring_specs):
            b_val = float(bands[(r_idx * 3) % 16])
            rad = rad_base * (1.0 + 0.14 * b_val + 0.08 * energy - 0.05 * mic_e)
            ring = np.stack([np.cos(theta) * rad, np.sin(theta) * rad, np.zeros_like(theta)], axis=1)
            pts = ring @ _rotation_matrix_xyz(ax, ay, az).T
            sx, sy, _ = self._project(pts, cx, cy, scale)
            path = QPainterPath()
            path.moveTo(float(sx[0]), float(sy[0]))
            for i in range(1, len(sx)):
                path.lineTo(float(sx[i]), float(sy[i]))
            path.closeSubpath()
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(col.red(), col.green(), col.blue(), int(145 + 90 * b_val)), lw + b_val))
            painter.drawPath(path)

            # Outward FFT ticks on outer ring
            if r_idx == 0:
                for k in range(0, 72, 2):
                    be = float(bands[(k // 2) % 16])
                    out = 1.0 + 0.04 + 0.24 * be
                    p_out = ring[k : k + 1] * out
                    p_out = p_out @ _rotation_matrix_xyz(ax, ay, az).T
                    ox, oy, _ = self._project(p_out, cx, cy, scale)
                    painter.setPen(QPen(QColor(c_core.red(), c_core.green(), c_core.blue(), int(110 + 130 * be)), 1.4))
                    painter.drawLine(QPointF(float(sx[k]), float(sy[k])), QPointF(float(ox[0]), float(oy[0])))

        core_r = scale * (0.16 + 0.10 * energy + 0.04 * mic_e)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(c_core.red(), c_core.green(), c_core.blue(), 190))
        painter.drawEllipse(QPointF(cx, cy), core_r, core_r)

    def _paint_torus_knot(
        self,
        painter: QPainter,
        cx: float,
        cy: float,
        scale: float,
        c_core: QColor,
        c_pri: QColor,
        c_sec: QColor,
        energy: float,
        mic_e: float,
        eff_state: str,
        bands: np.ndarray,
    ) -> None:
        t_param = self._geom_torus["t"]
        ph = self._phase
        rot = _rotation_matrix_xyz(ph * 0.31, ph * 0.47, ph * 0.21)
        for ribbon_idx in range(3):
            phase_off = ribbon_idx * (2.0 * math.pi / 3.0)
            b_idx = (np.arange(t_param.size) % 16)
            mod = 0.24 + 0.08 * energy + 0.14 * bands[b_idx] * (1.0 if eff_state == "speaking" else 0.25)
            r = 0.62 + mod * np.cos(5.0 * t_param + ph * 2.2 + phase_off)
            x = r * np.cos(3.0 * t_param + phase_off * 0.5)
            y = r * np.sin(3.0 * t_param + phase_off * 0.5)
            z = (mod * 1.15) * np.sin(5.0 * t_param + ph * 2.2 + phase_off)
            pts = np.stack([x, y, z], axis=1).astype(np.float32) @ rot.T
            sx, sy, sz = self._project(pts, cx, cy, scale)
            col = [c_core, c_pri, c_sec][ribbon_idx]
            n_pts = len(sx)
            for i in range(n_pts):
                j = (i + 1) % n_pts
                depth_t = max(0.0, min(1.0, (float(sz[i]) + 0.9) * 0.55))
                alpha = int(min(230, 55 + depth_t * 115 + energy * 55))
                painter.setPen(QPen(QColor(col.red(), col.green(), col.blue(), alpha), 1.3 + depth_t * 1.3))
                painter.drawLine(QPointF(float(sx[i]), float(sy[i])), QPointF(float(sx[j]), float(sy[j])))

    def _paint_swarm(
        self,
        painter: QPainter,
        cx: float,
        cy: float,
        scale: float,
        c_core: QColor,
        c_pri: QColor,
        c_sec: QColor,
        energy: float,
        mic_e: float,
        eff_state: str,
        bands: np.ndarray,
    ) -> None:
        t = self._phase
        verts = self._geom_swarm["verts"]
        phases = self._geom_swarm["phases"]
        n = verts.shape[0]
        if eff_state == "speaking":
            b_idx = np.arange(n) % 16
            wave = 1.0 + 0.26 * bands[b_idx] * np.sin(t * 7.5 + phases) + energy * 0.12
            pts = verts * wave[:, None]
        elif eff_state == "thinking":
            pts = verts * (0.74 + 0.08 * np.sin(t * 5.0 + phases)[:, None])
        elif eff_state == "listening":
            pts = verts * (0.94 - 0.10 * mic_e + 0.06 * mic_e * np.cos(t * 4.0 + phases)[:, None])
        else:
            pts = verts * (1.0 + 0.05 * np.sin(t * 1.8 + phases)[:, None])

        rot = _rotation_matrix_xyz(t * 0.26, t * 0.44, -t * 0.14)
        r_pts = pts.astype(np.float32) @ rot.T
        sx, sy, sz = self._project(r_pts, cx, cy, scale)

        # Nearest neighbor constellation chords on projected 3D points
        diff = r_pts[:, None, :] - r_pts[None, :, :]
        dist2 = np.sum(diff * diff, axis=2)
        thresh2 = 0.24 if eff_state != "thinking" else 0.18
        painter.setPen(QPen(QColor(c_pri.red(), c_pri.green(), c_pri.blue(), int(70 + energy * 95)), 0.9))
        ii, jj = np.where((dist2 > 1e-5) & (dist2 < thresh2))
        mask = ii < jj
        for a, b in zip(ii[mask], jj[mask]):
            painter.drawLine(QPointF(float(sx[a]), float(sy[a])), QPointF(float(sx[b]), float(sy[b])))

        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(n):
            depth_t = max(0.0, min(1.0, (float(sz[i]) + 1.0) * 0.5))
            rad = 1.6 + depth_t * 1.7 + float(bands[i % 16]) * 1.8
            col = c_core if depth_t > 0.65 else c_pri
            painter.setBrush(QColor(col.red(), col.green(), col.blue(), int(110 + 120 * depth_t)))
            painter.drawEllipse(QPointF(float(sx[i]), float(sy[i])), rad, rad)

    def _paint_mandala(
        self,
        painter: QPainter,
        cx: float,
        cy: float,
        scale: float,
        c_core: QColor,
        c_pri: QColor,
        c_sec: QColor,
        energy: float,
        mic_e: float,
        eff_state: str,
        bands: np.ndarray,
    ) -> None:
        t = self._phase
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # 5 concentric harmonic interference rings + sacred rotated polygons
        for ring_i in range(5):
            r_base = scale * (0.28 + ring_i * 0.17)
            steps = 72
            path = QPainterPath()
            rot_dir = 1.0 if ring_i % 2 == 0 else -1.0
            for s in range(steps + 1):
                ang = (2.0 * math.pi * s) / steps + t * 0.25 * rot_dir
                b = float(bands[(s + ring_i * 3) % 16])
                harmonic = math.cos((6 + ring_i * 2) * ang - t * 2.8 * rot_dir)
                r = r_base * (1.0 + 0.08 * harmonic + (0.22 * b + 0.06 * energy) * (0.6 + 0.1 * ring_i) - 0.05 * mic_e)
                px = cx + math.cos(ang) * r
                py = cy + math.sin(ang) * r
                if s == 0:
                    path.moveTo(px, py)
                else:
                    path.lineTo(px, py)
            col = c_core if ring_i in (1, 3) else (c_pri if ring_i < 4 else c_sec)
            alpha = int(min(235, 110 + energy * 90 + float(bands[ring_i * 3 % 16]) * 50))
            painter.setPen(QPen(QColor(col.red(), col.green(), col.blue(), alpha), 1.5))
            painter.drawPath(path)


class VoiceAvatarStageWindow(QWidget):
    """Optional Windowed or Full-Screen Voice Avatar stage with autohide slide-up bottom bar."""

    mode_changed = Signal(str)
    settings_changed = Signal(dict)
    mute_toggled = Signal(bool)
    stop_speaking_requested = Signal()
    end_talk_requested = Signal()
    open_settings_requested = Signal()
    return_to_chat_requested = Signal()

    HOTZONE_PX = 48

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("voiceAvatarStageWindow")
        self._stage_mode = "windowed"  # "windowed" | "fullscreen"
        self._shape_id = "neural_core"
        self._palette_id = "tulsa_cyan"
        self._always_on_top = True
        self._show_activity = True
        self._muted = False
        self._menu_open = False
        self._programmatic_close = False

        self.setWindowTitle("Fairybread — Voice Avatar")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet("QWidget#voiceAvatarStageWindow { background: #030608; }")

        self.canvas = VoiceAvatarCanvas(self)
        self.canvas.installEventFilter(self)
        self.canvas.hologram_clicked.connect(self.stop_speaking_requested.emit)

        # Subtle glowing 2px bottom handle indicator shown in full screen while dock is hidden
        self._edge_hint = QFrame(self)
        self._edge_hint.setObjectName("voiceAvatarEdgeHint")
        self._edge_hint.setFixedSize(76, 3)
        self._edge_hint.setStyleSheet(
            "QFrame#voiceAvatarEdgeHint { background: rgba(56, 232, 255, 0.42); border-radius: 2px; }"
        )

        # Optional Activity & Live Caption bar above the bottom dock
        self._activity_bar = QFrame(self)
        self._activity_bar.setObjectName("voiceAvatarActivityBar")
        self._activity_bar.setStyleSheet(
            "QFrame#voiceAvatarActivityBar { background: rgba(10, 16, 22, 0.78); "
            "border: 1px solid rgba(56, 232, 255, 0.26); border-radius: 10px; }"
        )
        act_lay = QHBoxLayout(self._activity_bar)
        act_lay.setContentsMargins(12, 6, 12, 6)
        act_lay.setSpacing(10)

        self.state_pill = QLabel("● Idle")
        self.state_pill.setStyleSheet("color: #38e8ff; font-size: 11.5px; font-weight: 700; background: transparent;")
        act_lay.addWidget(self.state_pill)

        self.caption_label = QLabel("Listening when Voice Mode is active — click the shape anytime to stop speaking.")
        self.caption_label.setStyleSheet("color: #c9d1d9; font-size: 12px; background: transparent;")
        self.caption_label.setWordWrap(False)
        act_lay.addWidget(self.caption_label, 1)

        self.visual_chip_btn = QPushButton("🖼 Visual Reply ↗")
        self.visual_chip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.visual_chip_btn.setStyleSheet(
            "QPushButton { background: #132238; color: #7dd3fc; border: 1px solid #3b82f6; "
            "border-radius: 6px; padding: 3px 9px; font-size: 11px; font-weight: 600; }"
            "QPushButton:hover { background: #1f3556; color: #ffffff; }"
        )
        self.visual_chip_btn.clicked.connect(self.return_to_chat_requested.emit)
        self.visual_chip_btn.hide()
        act_lay.addWidget(self.visual_chip_btn)

        # Floating / Slide-Up Bottom Option Dock
        self._dock_frame = QFrame(self)
        self._dock_frame.setObjectName("voiceAvatarDock")
        self._dock_frame.installEventFilter(self)
        self._dock_frame.setMouseTracking(True)
        self._dock_frame.setStyleSheet(
            "QFrame#voiceAvatarDock { background: rgba(13, 19, 27, 0.93); "
            "border: 1px solid rgba(56, 232, 255, 0.36); border-radius: 12px; }"
            "QFrame#voiceAvatarDock QPushButton { background: #161f29; color: #e6edf3; border: 1px solid #2b3847; "
            "border-radius: 7px; padding: 4px 8px; font-size: 11.5px; font-weight: 600; }"
            "QFrame#voiceAvatarDock QPushButton:hover { background: #213040; border-color: #38e8ff; color: #ffffff; }"
            "QFrame#voiceAvatarDock QPushButton:checked { background: #112a36; border-color: #38e8ff; color: #7dd3fc; }"
        )
        dock_lay = QHBoxLayout(self._dock_frame)
        dock_lay.setContentsMargins(8, 6, 8, 6)
        dock_lay.setSpacing(5)

        self.dock_avatar_btn = QPushButton("◎ Avatar ▾")
        self.dock_avatar_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dock_avatar_btn.setToolTip("Switch geometric avatar shape, color palette, or Windowed / Full Screen mode")
        self.dock_avatar_btn.clicked.connect(self._show_avatar_menu)
        dock_lay.addWidget(self.dock_avatar_btn)

        self.dock_activity_btn = QPushButton("💬 Activity")
        self.dock_activity_btn.setCheckable(True)
        self.dock_activity_btn.setChecked(True)
        self.dock_activity_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dock_activity_btn.setToolTip("Show or hide live captions and state strip")
        self.dock_activity_btn.toggled.connect(self._on_activity_toggled)
        dock_lay.addWidget(self.dock_activity_btn)

        self.dock_cost_label = QLabel("💵 $0.000")
        self.dock_cost_label.setToolTip("Live Voice Mode spend this conversation")
        self.dock_cost_label.setStyleSheet(
            "font-family: Consolas, monospace; font-size: 11px; font-weight: 700; color: #90d7c1; "
            "background: #0e2422; border: 1px solid #14b8a6; border-radius: 6px; padding: 4px 8px;"
        )
        dock_lay.addWidget(self.dock_cost_label)

        self.dock_mute_btn = QPushButton("🔇 Mute")
        self.dock_mute_btn.setCheckable(True)
        self.dock_mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dock_mute_btn.toggled.connect(self._on_mute_clicked)
        dock_lay.addWidget(self.dock_mute_btn)

        self.dock_stop_btn = QPushButton("■ Stop")
        self.dock_stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dock_stop_btn.setToolTip("Stop AI speech immediately")
        self.dock_stop_btn.clicked.connect(self.stop_speaking_requested.emit)
        dock_lay.addWidget(self.dock_stop_btn)

        self.dock_screen_btn = QPushButton("⛶ Full Screen")
        self.dock_screen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dock_screen_btn.clicked.connect(self._toggle_window_vs_fullscreen)
        dock_lay.addWidget(self.dock_screen_btn)

        self.dock_settings_btn = QPushButton("⚙ Settings")
        self.dock_settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dock_settings_btn.clicked.connect(self.open_settings_requested.emit)
        dock_lay.addWidget(self.dock_settings_btn)

        self.dock_chat_btn = QPushButton("← Chat (Esc)")
        self.dock_chat_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dock_chat_btn.setToolTip("Return to chat while keeping Live Voice running (Esc)")
        self.dock_chat_btn.clicked.connect(self.return_to_chat_requested.emit)
        dock_lay.addWidget(self.dock_chat_btn)

        self.dock_end_btn = QPushButton("✕ End")
        self.dock_end_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dock_end_btn.setStyleSheet(
            "QPushButton { background: #3d1414; color: #ff6b6b; border: 1px solid #ef4444; "
            "border-radius: 7px; padding: 4px 8px; font-size: 11.5px; font-weight: 700; }"
            "QPushButton:hover { background: #5c1919; color: #ffffff; }"
        )
        self.dock_end_btn.clicked.connect(self.end_talk_requested.emit)
        dock_lay.addWidget(self.dock_end_btn)

        self._dock_revealed = True
        self._dock_anim = QPropertyAnimation(self._dock_frame, b"pos", self)
        self._dock_anim.setDuration(200)
        self._dock_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self._hide_dock_timer = QTimer(self)
        self._hide_dock_timer.setSingleShot(True)
        self._hide_dock_timer.setInterval(1250)
        self._hide_dock_timer.timeout.connect(self._maybe_auto_hide_dock)

        self._esc_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._esc_shortcut.activated.connect(self.return_to_chat_requested.emit)

        self.resize(420, 400)
        self.setMinimumSize(360, 320)
        self._sync_dock_compact_buttons()
        self._layout_overlays()

    def apply_settings(
        self,
        *,
        mode: str | None = None,
        shape_id: str | None = None,
        palette_id: str | None = None,
        theme_dict: dict[str, Any] | None = None,
        provider_color_hex: str | None = None,
        always_on_top: bool | None = None,
        show_activity: bool | None = None,
    ) -> None:
        if shape_id is not None:
            self._shape_id = shape_id
            self.canvas.set_shape(shape_id)
        if palette_id is not None or theme_dict is not None or provider_color_hex is not None:
            if palette_id is not None:
                self._palette_id = palette_id
            self.canvas.set_palette_config(
                self._palette_id,
                theme_dict=theme_dict,
                provider_color_hex="" if provider_color_hex is None else provider_color_hex,
            )
        if always_on_top is not None:
            self._always_on_top = bool(always_on_top)
        if show_activity is not None:
            self._show_activity = bool(show_activity)
            self.dock_activity_btn.blockSignals(True)
            self.dock_activity_btn.setChecked(self._show_activity)
            self.dock_activity_btn.blockSignals(False)
            self._activity_bar.setVisible(self._show_activity)
        if mode in {"windowed", "fullscreen"}:
            self._stage_mode = mode
        self._sync_dock_compact_buttons()
        self._layout_overlays()

    def present_in_mode(self, mode: str) -> None:
        """Show the avatar window cleanly in `'windowed'` or `'fullscreen'` mode."""
        target = "fullscreen" if mode == "fullscreen" else "windowed"
        prev = self._stage_mode
        self._stage_mode = target
        flags = Qt.WindowType.Window
        if target == "windowed" and self._always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        if self.windowFlags() != flags:
            was_vis = self.isVisible()
            self.setWindowFlags(flags)
            if was_vis:
                self.show()

        if target == "fullscreen":
            self.dock_screen_btn.setText("◫ Windowed")
            self._sync_dock_compact_buttons()
            self._dock_revealed = False
            self.showFullScreen()
            self._layout_overlays()
            # Snap dock cleanly off the bottom edge on first Full Screen entry
            self._dock_frame.move(self._dock_hidden_pos())
            self._edge_hint.setVisible(True)
        else:
            self.dock_screen_btn.setText("⛶ Full Screen")
            if self.isFullScreen():
                self.showNormal()
            w = max(560, min(680, self.width() if prev == "windowed" else 580))
            h = max(400, min(500, self.height() if prev == "windowed" else 440))
            self.resize(w, h)
            self._position_windowed_safe()
            self._sync_dock_compact_buttons()
            self._dock_revealed = True
            self._edge_hint.setVisible(False)
            self.show()
            self.raise_()
            self._layout_overlays()

    def _position_windowed_safe(self) -> None:
        screen = QGuiApplication.screenAt(self.geometry().center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        ww = min(self.width(), max(320, avail.width() - 40))
        hh = min(self.height(), max(280, avail.height() - 40))
        if (ww, hh) != (self.width(), self.height()):
            self.resize(ww, hh)
        x = avail.right() - ww - 24
        y = avail.bottom() - hh - 28
        self.move(max(avail.left() + 12, x), max(avail.top() + 12, y))

    def set_voice_status(
        self,
        *,
        state: str | None = None,
        mic_level: float | None = None,
        speech_detected: bool | None = None,
        muted: bool | None = None,
        caption: str | None = None,
        cost_text: str | None = None,
        has_visual_reply: bool | None = None,
    ) -> None:
        self.canvas.set_interaction_state(
            state,
            mic_level=mic_level,
            speech_detected=speech_detected,
            muted=muted,
        )
        if muted is not None:
            self._muted = bool(muted)
            self.dock_mute_btn.blockSignals(True)
            self.dock_mute_btn.setChecked(self._muted)
            self.dock_mute_btn.setText("🎙 Unmute" if self._muted else "🔇 Mute")
            self.dock_mute_btn.blockSignals(False)
        if state is not None:
            lbl_map = {
                "idle": ("● Idle", "#8b949e"),
                "listening": ("🎙 Listening", "#22c55e"),
                "thinking": ("⏳ Thinking", "#eab308"),
                "speaking": ("🔊 Speaking", "#38e8ff"),
            }
            txt, col = lbl_map.get(state, ("● Active", "#38e8ff"))
            if self._muted:
                txt, col = ("🔇 Muted", "#eab308")
            self.state_pill.setText(txt)
            self.state_pill.setStyleSheet(f"color: {col}; font-size: 11.5px; font-weight: 700; background: transparent;")
        if caption is not None:
            clean = " ".join(str(caption).split())
            self.caption_label.setText((clean[:135] + "…") if len(clean) > 138 else clean)
        if cost_text is not None:
            self.dock_cost_label.setText(str(cost_text))
        if has_visual_reply is not None:
            self.visual_chip_btn.setVisible(bool(has_visual_reply))

    def _sync_dock_compact_buttons(self) -> None:
        """Ensure buttons fit comfortably in both Windowed and Full-Screen without clipping."""
        is_full = (self._stage_mode == "fullscreen")
        w = self.width()
        full_set = is_full or w >= 760
        med_set = is_full or w >= 520
        self.dock_screen_btn.setText("◫ Windowed" if is_full else ("⛶ Full" if w < 640 else "⛶ Full Screen"))
        self.dock_chat_btn.setText("← Chat (Esc)" if is_full else "← Chat")
        for widget in (self.dock_avatar_btn, self.dock_mute_btn, self.dock_screen_btn, self.dock_end_btn):
            widget.setVisible(True)
        for widget in (self.dock_activity_btn, self.dock_cost_label, self.dock_settings_btn):
            widget.setVisible(full_set)
        for widget in (self.dock_stop_btn, self.dock_chat_btn):
            widget.setVisible(med_set)

    def _dock_shown_pos(self) -> QPoint:
        dw = self._dock_frame.sizeHint().width()
        dh = self._dock_frame.sizeHint().height()
        x = max(8, (self.width() - dw) // 2)
        y = max(8, self.height() - dh - 14)
        return QPoint(x, y)

    def _dock_hidden_pos(self) -> QPoint:
        dw = self._dock_frame.sizeHint().width()
        x = max(8, (self.width() - dw) // 2)
        return QPoint(x, self.height() + 8)

    def reveal_dock(self, animate: bool = True) -> None:
        self._hide_dock_timer.stop()
        self._dock_revealed = True
        self._edge_hint.setVisible(False)
        target = self._dock_shown_pos()
        self._dock_frame.resize(self._dock_frame.sizeHint())
        if not animate:
            self._dock_anim.stop()
            self._dock_frame.move(target)
        elif self._dock_frame.pos() != target:
            self._dock_anim.stop()
            self._dock_anim.setStartValue(self._dock_frame.pos())
            self._dock_anim.setEndValue(target)
            self._dock_anim.start()

    def hide_dock(self, animate: bool = True) -> None:
        if self._stage_mode != "fullscreen" or self._menu_open:
            return
        self._dock_revealed = False
        target = self._dock_hidden_pos()
        if not animate:
            self._dock_anim.stop()
            self._dock_frame.move(target)
        elif self._dock_frame.pos() != target:
            self._dock_anim.stop()
            self._dock_anim.setStartValue(self._dock_frame.pos())
            self._dock_anim.setEndValue(target)
            self._dock_anim.start()
        self._edge_hint.setVisible(True)

    def _maybe_auto_hide_dock(self) -> None:
        if self._stage_mode != "fullscreen" or self._menu_open:
            return
        local_pos = self.mapFromGlobal(QCursor.pos())
        if self._is_cursor_activating_dock(local_pos):
            self._hide_dock_timer.start()
            return
        self.hide_dock(animate=True)

    def _is_cursor_activating_dock(self, local_pos: QPoint) -> bool:
        if local_pos.y() >= max(0, self.height() - self.HOTZONE_PX) and 0 <= local_pos.x() <= self.width():
            return True
        if self._dock_revealed and self._dock_frame.geometry().adjusted(-10, -10, 10, 10).contains(local_pos):
            return True
        return False

    def handle_pointer_position(self, local_pos: QPoint) -> None:
        if self._stage_mode != "fullscreen":
            return
        if self._is_cursor_activating_dock(local_pos):
            if not self._dock_revealed:
                self.reveal_dock(animate=True)
            else:
                self._hide_dock_timer.stop()
        else:
            if self._dock_revealed and not self._hide_dock_timer.isActive() and not self._menu_open:
                self._hide_dock_timer.start()

    def eventFilter(self, obj, event):
        if obj in (self.canvas, self._dock_frame) and event.type() == QEvent.Type.MouseMove:
            gp = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else QCursor.pos()
            self.handle_pointer_position(self.mapFromGlobal(gp))
        return super().eventFilter(obj, event)

    def mouseMoveEvent(self, event):
        self.handle_pointer_position(event.position().toPoint())
        super().mouseMoveEvent(event)

    def _layout_overlays(self) -> None:
        w, h = max(1, self.width()), max(1, self.height())
        self.canvas.setGeometry(0, 0, w, h)
        self._dock_frame.adjustSize()
        self._dock_frame.resize(min(w - 16, self._dock_frame.sizeHint().width()), self._dock_frame.sizeHint().height())
        if self._stage_mode == "fullscreen":
            if self._dock_revealed:
                self._dock_frame.move(self._dock_shown_pos())
            else:
                self._dock_frame.move(self._dock_hidden_pos())
            self._edge_hint.move(max(0, (w - self._edge_hint.width()) // 2), max(0, h - 7))
        else:
            self._dock_frame.move(self._dock_shown_pos())

        act_w = min(760, max(240, w - 32))
        act_h = max(34, self._activity_bar.sizeHint().height())
        dock_top = h - self._dock_frame.height() - 22
        self._activity_bar.setGeometry((w - act_w) // 2, max(12, dock_top - act_h - 8), act_w, act_h)
        self._activity_bar.setVisible(self._show_activity and h >= 320)
        self._dock_frame.raise_()
        self._activity_bar.raise_()
        self._edge_hint.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_dock_compact_buttons()
        self._layout_overlays()

    def _on_mute_clicked(self, checked: bool) -> None:
        self.mute_toggled.emit(bool(checked))

    def _on_activity_toggled(self, checked: bool) -> None:
        self._show_activity = bool(checked)
        self._activity_bar.setVisible(self._show_activity)
        self.settings_changed.emit({"voice_avatar_show_activity": self._show_activity})
        self._layout_overlays()

    def _toggle_window_vs_fullscreen(self) -> None:
        nxt = "windowed" if self._stage_mode == "fullscreen" else "fullscreen"
        self.mode_changed.emit(nxt)

    def _show_avatar_menu(self) -> None:
        self._menu_open = True
        self._hide_dock_timer.stop()
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #161922; color: #e6edf3; border: 1px solid #2b313e; padding: 6px; border-radius: 8px; } "
            "QMenu::item { padding: 6px 14px; border-radius: 5px; font-size: 12.5px; } "
            "QMenu::item:selected { background: #232938; }"
        )
        m_sub = menu.addMenu("Display Mode")
        for mid, mlabel in AVATAR_MODES:
            act = m_sub.addAction(("✓ " if self._stage_mode == mid else "   ") + mlabel)
            act.triggered.connect(lambda _c=False, mode_val=mid: self.mode_changed.emit(mode_val))

        s_sub = menu.addMenu("Geometric Avatar")
        for sid, slabel in AVATAR_SHAPES:
            act = s_sub.addAction(("✓ " if self._shape_id == sid else "   ") + slabel)
            act.triggered.connect(lambda _c=False, s_val=sid: self._pick_shape(s_val))

        p_sub = menu.addMenu("Color Palette")
        for pid, plabel in AVATAR_PALETTES:
            act = p_sub.addAction(("✓ " if self._palette_id == pid else "   ") + plabel)
            act.triggered.connect(lambda _c=False, p_val=pid: self._pick_palette(p_val))

        menu.addSeparator()
        top_act = menu.addAction(("✓ " if self._always_on_top else "   ") + "Always on Top (Windowed)")
        top_act.triggered.connect(self._toggle_always_on_top)

        pos = self.dock_avatar_btn.mapToGlobal(QPoint(0, -menu.sizeHint().height() - 4))
        if pos.y() < 20:
            pos = self.dock_avatar_btn.mapToGlobal(QPoint(0, self.dock_avatar_btn.height() + 4))
        try:
            menu.exec(pos)
        finally:
            self._menu_open = False
            if self._stage_mode == "fullscreen":
                self._hide_dock_timer.start()

    def _pick_shape(self, shape_id: str) -> None:
        self._shape_id = shape_id
        self.canvas.set_shape(shape_id)
        self.settings_changed.emit({"voice_avatar_shape": shape_id})

    def _pick_palette(self, palette_id: str) -> None:
        self._palette_id = palette_id
        self.canvas.set_palette_config(palette_id)
        self.settings_changed.emit({"voice_avatar_palette": palette_id})

    def _toggle_always_on_top(self) -> None:
        self._always_on_top = not self._always_on_top
        self.settings_changed.emit({"voice_avatar_always_on_top": self._always_on_top})
        if self._stage_mode == "windowed" and self.isVisible():
            self.present_in_mode("windowed")

    def close_programmatically(self) -> None:
        self._programmatic_close = True
        self.canvas.stop_animation()
        if self.isFullScreen():
            self.showNormal()
        self.hide()
        self._programmatic_close = False

    def closeEvent(self, event):
        self.canvas.stop_animation()
        if not self._programmatic_close:
            self.return_to_chat_requested.emit()
        super().closeEvent(event)
