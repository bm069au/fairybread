"""Audio-reactive 3D geometric Voice Avatar visualizer & autohide Full-Screen / Windowed stage."""
from __future__ import annotations

import ctypes
import math
import os
from pathlib import Path
import subprocess
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
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QRadialGradient,
    QShortcut,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from voice_service import DEFAULT_CARTOON_AVATAR_CONFIG, get_tts_audio_telemetry


AVATAR_MODES: list[tuple[str, str]] = [
    ("no_avatar", "No Avatar (Off)"),
    ("windowed", "Windowed (Floating)"),
    ("fullscreen", "Full Screen Stage"),
]

AVATAR_SHAPES: list[tuple[str, str]] = [
    ("cartoon_character", "🎭 Animated Cartoon Character (Customizable)"),
    ("neural_core", "Crystalline Neural Core"),
    ("tesseract", "4D Tesseract Hypercube"),
    ("astrolabe", "Celestial Astrolabe Gyro"),
    ("torus_knot", "Harmonic Torus Knot"),
    ("swarm", "Swarm Constellation"),
    ("mandala", "Acoustic Sacred Mandala"),
]

CARTOON_SKIN_TONES: dict[str, tuple[str, str, str, str]] = {
    "fair": ("Fair Porcelain", "#fde2d2", "#eebda6", "#f4a298"),
    "warm_light": ("Warm Peach / Light", "#f5cba7", "#d99f76", "#e5897d"),
    "olive": ("Medium Olive", "#e0ac7e", "#ba8356", "#cc7468"),
    "tan": ("Golden Tan", "#c68b59", "#9b6539", "#b55d52"),
    "warm_brown": ("Warm Chestnut Brown", "#8d5524", "#663a14", "#8a3e38"),
    "deep_dark": ("Deep Espresso", "#523018", "#361d0c", "#5e2824"),
}

CARTOON_HAIR_COLORS: dict[str, tuple[str, str, str]] = {
    "chestnut": ("Warm Chestnut", "#5c3317", "#8b5a2b"),
    "blonde": ("Golden Blonde", "#d4a843", "#f3d37a"),
    "auburn": ("Ginger / Auburn", "#8c3318", "#c2522e"),
    "dark_brown": ("Espresso Dark Brown", "#2c1b12", "#4a3022"),
    "jet_black": ("Jet Black", "#14161d", "#2c3242"),
    "silver": ("Platinum Silver", "#94a3b8", "#e2e8f0"),
    "cyber_violet": ("Cyber Neon Violet", "#6d28d9", "#c084fc"),
}

CARTOON_HAIR_STYLES: list[tuple[str, str]] = [
    ("cozy_bun", "Cozy Top Bun & Soft Strands"),
    ("long_wavy", "Long Wavy Flowing"),
    ("curly", "Full Curly Halo"),
    ("short_crop", "Short Textured Crop"),
    ("side_part", "Classic Side Part"),
    ("spiky", "Modern Spiky"),
]

CARTOON_EYE_COLORS: dict[str, tuple[str, str]] = {
    "hazel": ("Warm Hazel", "#7c5828"),
    "brown": ("Deep Brown", "#452712"),
    "blue": ("Ocean Blue", "#2563eb"),
    "emerald": ("Emerald Green", "#10b981"),
    "amber": ("Golden Amber", "#d97706"),
    "violet": ("Amethyst Violet", "#8b5cf6"),
}

CARTOON_OUTFIT_COLORS: dict[str, tuple[str, str, str]] = {
    "cream": ("Cozy Cream Sweater", "#e7dfd3", "#c8bca9"),
    "navy_hoodie": ("Midnight Navy Hoodie", "#1e293b", "#0f172a"),
    "emerald": ("Forest Emerald Knit", "#065f46", "#064e3b"),
    "crimson": ("Warm Crimson Sweater", "#7f1d1d", "#450a0a"),
    "charcoal": ("Charcoal Tech Jacket", "#27272a", "#18181b"),
}

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


AVATAR_PORTRAIT_PRESETS: dict[str, dict[str, Any]] = {
    "pixar_3d_female": {
        "label": "3D Pixar Studio — Female (Mockup #2)",
        "engine_mode": "studio_3d",
        "gender": "female",
        "filename": "pixar_3d_female.png",
        "eye_l": (0.35, 0.37, 0.13, 0.08),
        "eye_r": (0.53, 0.35, 0.13, 0.08),
        "mouth": (0.41, 0.50, 0.22, 0.08),
        "jaw": (0.33, 0.50, 0.38, 0.16),
        "max_drop": 0.055,
    },
    "pixar_3d_male": {
        "label": "3D Pixar Studio — Male (Bearded)",
        "engine_mode": "studio_3d",
        "gender": "male",
        "filename": "pixar_3d_male.png",
        "eye_l": (0.36, 0.27, 0.11, 0.06),
        "eye_r": (0.52, 0.26, 0.11, 0.06),
        "mouth": (0.40, 0.41, 0.22, 0.07),
        "jaw": (0.34, 0.41, 0.34, 0.18),
        "max_drop": 0.058,
    },
    "lifelike_girl": {
        "label": "Lifelike Human — Bedroom Portrait (Female)",
        "engine_mode": "lifelike_portrait",
        "gender": "female",
        "filename": "lifelike_girl.jpg",
        "eye_l": (0.41, 0.17, 0.11, 0.06),
        "eye_r": (0.58, 0.20, 0.11, 0.06),
        "mouth": (0.44, 0.34, 0.18, 0.08),
        "jaw": (0.36, 0.34, 0.32, 0.16),
        "max_drop": 0.052,
    },
    "lifelike_male": {
        "label": "Lifelike Human — Home Study Portrait (Male)",
        "engine_mode": "lifelike_portrait",
        "gender": "male",
        "filename": "lifelike_male.png",
        "eye_l": (0.43, 0.32, 0.11, 0.05),
        "eye_r": (0.59, 0.34, 0.11, 0.05),
        "mouth": (0.46, 0.49, 0.19, 0.07),
        "jaw": (0.38, 0.49, 0.34, 0.18),
        "max_drop": 0.055,
    },
    "brick_movie_male": {
        "label": "3D Brick Movie Minifig — Male (Beard & Hoodie)",
        "engine_mode": "voxel_3d",
        "gender": "male",
        "filename": "brick_movie_male.png",
        "eye_l": (0.41, 0.35, 0.075, 0.055),
        "eye_r": (0.51, 0.35, 0.075, 0.055),
        "mouth": (0.43, 0.43, 0.14, 0.055),
        "jaw": (0.37, 0.43, 0.26, 0.10),
        "max_drop": 0.042,
    },
    "brick_movie_female": {
        "label": "3D Brick Movie Minifig — Female (Top Bun & Knit Sweater)",
        "engine_mode": "voxel_3d",
        "gender": "female",
        "filename": "brick_movie_female.png",
        "eye_l": (0.38, 0.42, 0.10, 0.08),
        "eye_r": (0.52, 0.43, 0.10, 0.08),
        "mouth": (0.42, 0.54, 0.17, 0.075),
        "jaw": (0.35, 0.54, 0.30, 0.12),
        "max_drop": 0.045,
    },
}

_SYSTEM_GPU_CACHE: dict[str, Any] | None = None


def detect_system_gpu_and_power(force_refresh: bool = False) -> dict[str, Any]:
    """Detect Windows GPU adapters, dedicated NVIDIA vs integrated GPU, VRAM, refresh rate, and AC/Battery state."""
    global _SYSTEM_GPU_CACHE
    ac_online = True
    battery_pct = 100
    try:
        class _SYSTEM_POWER_STATUS(ctypes.Structure):
            _fields_ = [
                ("ACLineStatus", ctypes.c_byte),
                ("BatteryFlag", ctypes.c_byte),
                ("BatteryLifePercent", ctypes.c_byte),
                ("SystemStatusFlag", ctypes.c_byte),
                ("BatteryLifeTime", ctypes.c_ulong),
                ("BatteryFullLifeTime", ctypes.c_ulong),
            ]
        sps = _SYSTEM_POWER_STATUS()
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(sps)):
            ac_online = (int(sps.ACLineStatus) != 0)
            if 0 <= int(sps.BatteryLifePercent) <= 100:
                battery_pct = int(sps.BatteryLifePercent)
    except Exception:
        pass

    if _SYSTEM_GPU_CACHE is not None and not force_refresh:
        out = dict(_SYSTEM_GPU_CACHE)
        out["ac_online"] = ac_online
        out["on_battery"] = not ac_online
        out["battery_pct"] = battery_pct
        return out

    gpu_name = "Standard Display Adapter"
    driver_ver = ""
    vram_mb = 1024
    is_nvidia = False
    is_amd_dedicated = False
    is_software = False
    try:
        # Query Windows WMI VideoController fast
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion | ConvertTo-Json -Compress",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=3.0, creationflags=0x08000000)
        if res.returncode == 0 and res.stdout.strip():
            import json as _json
            raw = _json.loads(res.stdout.strip())
            items = raw if isinstance(raw, list) else [raw]
            # Prefer NVIDIA or dedicated GPU on dual-GPU Optimus laptops
            if items:
                best = items[0]
                for it in items:
                    nm = str(it.get("Name") or "").lower()
                    if any(k in nm for k in ("nvidia", "geforce", "rtx", "gtx", "quadro")):
                        best = it
                        break
                    if any(k in nm for k in ("radeon rx", "radeon pro")):
                        best = it
                gpu_name = str(best.get("Name") or gpu_name).strip()
                driver_ver = str(best.get("DriverVersion") or "").strip()
                ram_b = int(best.get("AdapterRAM") or 0)
                if ram_b > 0:
                    vram_mb = max(256, ram_b // (1024 * 1024))
    except Exception:
        pass

    low_nm = gpu_name.lower()
    is_nvidia = any(k in low_nm for k in ("nvidia", "geforce", "rtx", "gtx", "quadro"))
    is_amd_dedicated = any(k in low_nm for k in ("radeon rx", "radeon pro"))
    is_software = any(k in low_nm for k in ("basic render", "microsoft basic", "llvmpipe", "warp"))

    refresh_hz = 60.0
    try:
        scr = QGuiApplication.primaryScreen()
        if scr is not None and scr.refreshRate() > 10:
            refresh_hz = float(scr.refreshRate())
    except Exception:
        pass

    _SYSTEM_GPU_CACHE = {
        "gpu_name": gpu_name,
        "driver_version": driver_ver,
        "vram_mb": vram_mb,
        "is_nvidia": is_nvidia,
        "is_dedicated": is_nvidia or is_amd_dedicated,
        "is_software": is_software,
        "refresh_hz": round(refresh_hz, 1),
        "ac_online": ac_online,
        "on_battery": not ac_online,
        "battery_pct": battery_pct,
    }
    return dict(_SYSTEM_GPU_CACHE)


def _build_ut_goty_3d_head_mesh(gender: str = "male") -> dict[str, Any]:
    """Build a rotatable 360-degree Unreal Tournament GOTY style low-poly 3D character bust mesh with jaw & eyelid vertex morph groups."""
    is_male = (str(gender or "male").lower() == "male")
    verts: list[list[float]] = []
    uvs: list[list[float]] = []
    jaw_weights: list[float] = []
    blink_weights: list[float] = []
    zone_ids: list[int] = []  # 0=skin, 1=hair, 2=beard/collar, 3=eye, 4=armor_shoulder, 5=visor_accent

    # Build cylindrical-spherical anatomical head lattice (12 rings x 20 slices)
    n_rings = 13
    n_slices = 20
    ring_profiles_male = [
        # (y, rx, rz, jaw_w, zone)
        (-0.98, 0.14, 0.14, 0.0, 1),  # 0: Top crown
        (-0.86, 0.42, 0.46, 0.0, 1),  # 1: Upper hair dome
        (-0.66, 0.56, 0.58, 0.0, 1),  # 2: Forehead hairline
        (-0.44, 0.58, 0.58, 0.0, 0),  # 3: Brow ridge
        (-0.24, 0.57, 0.56, 0.0, 0),  # 4: Eye socket plane
        (-0.04, 0.58, 0.60, 0.0, 0),  # 5: Cheekbones & nose tip
        (0.16,  0.54, 0.56, 0.15, 2), # 6: Upper lip / mustache
        (0.32,  0.50, 0.53, 0.85, 2), # 7: Lower lip / jaw hinge
        (0.52,  0.36, 0.44, 1.00, 2), # 8: Chin point
        (0.62,  0.34, 0.36, 0.25, 0), # 9: Neck upper
        (0.80,  0.38, 0.38, 0.0, 0),  # 10: Neck base
        (0.92,  0.86, 0.52, 0.0, 4),  # 11: UT Combat Pauldron / Collar
        (1.16,  1.05, 0.56, 0.0, 4),  # 12: Chest / Torso base
    ]
    ring_profiles_female = [
        (-0.98, 0.22, 0.22, 0.0, 1),
        (-0.86, 0.45, 0.48, 0.0, 1),
        (-0.66, 0.54, 0.56, 0.0, 1),
        (-0.44, 0.53, 0.54, 0.0, 0),
        (-0.24, 0.52, 0.53, 0.0, 0),
        (-0.04, 0.53, 0.56, 0.0, 0),
        (0.16,  0.46, 0.50, 0.15, 0),
        (0.32,  0.40, 0.46, 0.85, 0),
        (0.50,  0.25, 0.38, 1.00, 0),
        (0.62,  0.27, 0.30, 0.20, 0),
        (0.80,  0.31, 0.32, 0.0, 0),
        (0.92,  0.76, 0.46, 0.0, 4),
        (1.16,  0.92, 0.50, 0.0, 4),
    ]
    profiles = ring_profiles_male if is_male else ring_profiles_female

    for r_i, (y_base, rx, rz, j_w, base_zone) in enumerate(profiles):
        v_coord = r_i / float(n_rings - 1)
        for s_i in range(n_slices):
            u_coord = s_i / float(n_slices)
            theta = u_coord * 2.0 * math.pi  # 0 is +Z (front face)
            sin_t = math.sin(theta)
            cos_t = math.cos(theta)  # +1 at front center, -1 at back of head

            x = sin_t * rx
            z = cos_t * rz
            y = y_base

            # Sculpt 3D nose bridge & tip at front center (cos_t > 0.82) on rings 4..5
            if r_i in (4, 5) and cos_t > 0.82:
                nose_protrude = ((cos_t - 0.82) / 0.18) * (0.14 if r_i == 5 else 0.08)
                z += nose_protrude

            # Sculpt brow ridge overhang on ring 3
            if r_i == 3 and cos_t > 0.55:
                z += 0.045 * ((cos_t - 0.55) / 0.45)

            # Sculpt recessed eye sockets on ring 4
            is_eye_socket = (r_i == 4 and 0.62 < cos_t < 0.94 and 0.22 < abs(sin_t) < 0.72)
            b_w = 1.0 if is_eye_socket else 0.0
            if is_eye_socket:
                z -= 0.03

            # Determine surface material zone (Skin, Hair on back/sides, Beard on lower front male, Eyes, Armor)
            z_id = base_zone
            if r_i in (2, 3, 4, 5, 6) and cos_t < 0.15:
                z_id = 1  # Hair covers back and temples of head (360-degree view!)
            elif is_eye_socket:
                z_id = 3  # Eye / Visor zone
            elif r_i in (6, 7, 8) and cos_t > 0.25:
                if is_male:
                    # Mouth slit on ring 6..7 front center stays skin/lip colored
                    if r_i in (6, 7) and cos_t > 0.88:
                        z_id = 5  # Mouth / Lip seam
                    else:
                        z_id = 2  # Sculpted 3D beard
                else:
                    if r_i in (6, 7) and cos_t > 0.88:
                        z_id = 5  # Lip seam
                    else:
                        z_id = 0

            # Jaw only drops on front half of mandible (cos_t > 0.15)
            eff_jaw = j_w * max(0.0, (cos_t - 0.1) / 0.9) if cos_t > 0.1 else 0.0

            verts.append([x, y, z])
            uvs.append([u_coord, v_coord])
            jaw_weights.append(eff_jaw)
            blink_weights.append(b_w)
            zone_ids.append(z_id)

    tris: list[list[int]] = []
    tri_zones: list[int] = []
    for r_i in range(n_rings - 1):
        for s_i in range(n_slices):
            s_next = (s_i + 1) % n_slices
            i0 = r_i * n_slices + s_i
            i1 = r_i * n_slices + s_next
            i2 = (r_i + 1) * n_slices + s_next
            i3 = (r_i + 1) * n_slices + s_i
            z_face = zone_ids[i0] if r_i < 6 else zone_ids[i3]
            tris.append([i0, i1, i2])
            tri_zones.append(z_face)
            tris.append([i0, i2, i3])
            tri_zones.append(z_face)

    return {
        "verts": np.array(verts, dtype=np.float32),
        "uvs": np.array(uvs, dtype=np.float32),
        "jaw_w": np.array(jaw_weights, dtype=np.float32),
        "blink_w": np.array(blink_weights, dtype=np.float32),
        "tris": np.array(tris, dtype=np.int32),
        "tri_zones": np.array(tri_zones, dtype=np.int32),
    }


def load_custom_obj_3d_mesh(obj_path: str) -> dict[str, Any] | None:
    """Load an external Wavefront .OBJ 3D character mesh so users can drop in custom 3D models and spin them 360 degrees."""
    p = Path(obj_path)
    if not p.is_file():
        return None
    try:
        if p.stat().st_size > 32 * 1024 * 1024:
            return None
    except OSError:
        return None
    verts: list[list[float]] = []
    tris: list[list[int]] = []
    try:
        with p.open("r", encoding="utf-8", errors="ignore") as f:
            for ln in f:
                s = ln.split("#", 1)[0].strip()
                if not s:
                    continue
                if s.startswith("v "):
                    parts = s.split()
                    if len(parts) >= 4:
                        try:
                            vx, vy, vz = float(parts[1]), -float(parts[2]), float(parts[3])
                        except ValueError:
                            continue
                        if not (math.isfinite(vx) and math.isfinite(vy) and math.isfinite(vz)):
                            continue
                        verts.append([vx, vy, vz])
                        if len(verts) > 20000:
                            return None
                elif s.startswith("f "):
                    # OBJ face indices are 1-based; negative values count back from the
                    # vertices declared so far, so resolve them HERE, not later.
                    n_now = len(verts)
                    face_idx: list[int] = []
                    for tok in s.split()[1:]:
                        raw = tok.split("/")[0]
                        if not raw or not raw.lstrip("-").isdigit():
                            continue
                        try:
                            vi = int(raw)
                        except ValueError:
                            continue
                        resolved = (n_now + vi) if vi < 0 else (vi - 1)
                        if 0 <= resolved < n_now:
                            face_idx.append(resolved)
                        else:
                            face_idx = []
                            break
                    for k in range(1, len(face_idx) - 1):
                        a, b, c = face_idx[0], face_idx[k], face_idx[k + 1]
                        if a == b or b == c or a == c:
                            continue
                        tris.append([a, b, c])
        if len(verts) < 4 or len(tris) < 2 or len(tris) > 15000:
            return None
        t_arr = np.array(tris, dtype=np.int32)
        if int(t_arr.max()) >= len(verts) or int(t_arr.min()) < 0:
            return None
        v_arr = np.array(verts, dtype=np.float64)
        center = (v_arr.max(axis=0) + v_arr.min(axis=0)) * 0.5
        span = float(np.max(v_arr.max(axis=0) - v_arr.min(axis=0)))
        if not math.isfinite(span) or span <= 1e-6:
            return None
        v_arr = ((v_arr - center) * (2.0 / span)).astype(np.float32)
        jaw_w = np.clip((v_arr[:, 1] - 0.15) * 2.2, 0.0, 1.0) * np.clip(v_arr[:, 2], 0.0, 1.0)
        blink_w = np.zeros(len(v_arr), dtype=np.float32)
        z_arr = np.zeros(len(t_arr), dtype=np.int32)
        return {
            "verts": v_arr,
            "uvs": np.zeros((len(v_arr), 2), dtype=np.float32),
            "jaw_w": jaw_w.astype(np.float32),
            "blink_w": blink_w,
            "tris": t_arr,
            "tri_zones": z_arr,
        }
    except Exception:
        return None


class VoiceAvatarCanvas(QWidget):
    """60fps CPU-efficient PySide6 + NumPy 3D geometric voice avatar renderer."""

    hologram_clicked = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(180, 180)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._shape_id = "cartoon_character"
        self._palette_id = "tulsa_cyan"
        self._cartoon_cfg: dict[str, Any] = dict(DEFAULT_CARTOON_AVATAR_CONFIG)
        self._theme_dict: dict[str, Any] = {}
        self._provider_color = ""
        self._cast_slots: list[dict[str, Any]] = []
        self._active_slot_index: int = 0
        self._slot_scales: dict[int, float] = {}
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
        self._mesh_ut_male = _build_ut_goty_3d_head_mesh("male")
        self._mesh_ut_female = _build_ut_goty_3d_head_mesh("female")
        self._custom_obj_cache: dict[str, dict[str, Any]] = {}
        self._portrait_img_cache: dict[str, QImage] = {}

        # 360-degree mouse drag orbit state for UT 3D Mesh mode
        self._orbit_yaw = 0.0
        self._orbit_pitch = 0.05
        self._dragging_orbit = False
        self._drag_last_pos = QPointF(0.0, 0.0)

        self._bloom_img = QImage(160, 160, QImage.Format.Format_ARGB32_Premultiplied)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._on_tick)

    def set_shape(self, shape_id: str) -> None:
        valid = {sid for sid, _ in AVATAR_SHAPES}
        self._shape_id = shape_id if shape_id in valid else "neural_core"
        self.update()

    def set_cartoon_config(self, cfg: dict[str, Any] | None) -> None:
        merged = dict(DEFAULT_CARTOON_AVATAR_CONFIG)
        if isinstance(cfg, dict):
            for k, def_v in DEFAULT_CARTOON_AVATAR_CONFIG.items():
                if k in cfg:
                    if isinstance(def_v, bool):
                        merged[k] = bool(cfg[k])
                    elif isinstance(def_v, int):
                        try:
                            merged[k] = int(cfg[k])
                        except Exception:
                            merged[k] = def_v
                    elif isinstance(def_v, float):
                        try:
                            merged[k] = float(cfg[k])
                        except Exception:
                            merged[k] = def_v
                    elif k in ("custom_portrait_path", "custom_model_path", "benchmark_gpu_name", "benchmark_reason"):
                        merged[k] = str(cfg[k] or "").strip()
                    else:
                        merged[k] = str(cfg[k] or def_v).strip().lower()
        self._cartoon_cfg = merged
        self.update()

    def set_palette_config(self, palette_id: str, theme_dict: dict[str, Any] | None = None, provider_color_hex: str = "") -> None:
        self._palette_id = palette_id or "tulsa_cyan"
        if isinstance(theme_dict, dict):
            self._theme_dict = dict(theme_dict)
        if provider_color_hex is not None:
            self._provider_color = str(provider_color_hex or "")
        self.update()

    def set_cast_avatars(
        self,
        cast_slots: list[dict[str, Any]] | None,
        active_slot_index: int = 0,
    ) -> None:
        """Configure 1..4 active AI voice avatars with dynamic speaker spotlight scaling."""
        valid_shapes = {sid for sid, _ in AVATAR_SHAPES}
        cleaned: list[dict[str, Any]] = []
        for idx, sl in enumerate((cast_slots or [])[:4]):
            if not isinstance(sl, dict):
                continue
            sh = str(sl.get("avatar_shape") or self._shape_id or "neural_core").strip().lower()
            pal = str(sl.get("avatar_palette") or self._palette_id or "tulsa_cyan").strip().lower()
            cleaned.append({
                "slot_index": int(sl.get("slot_index", idx)),
                "speaker_name": str(sl.get("speaker_name") or f"AI {idx + 1}").strip(),
                "persona_label": str(sl.get("persona_label") or "").strip(),
                "avatar_shape": sh if sh in valid_shapes else "neural_core",
                "avatar_palette": pal or "tulsa_cyan",
                "provider_color": str(sl.get("provider_color") or "").strip(),
            })
        self._cast_slots = cleaned
        self._active_slot_index = int(active_slot_index)
        for pos, sl in enumerate(self._cast_slots):
            sidx = sl["slot_index"]
            if sidx not in self._slot_scales:
                self._slot_scales[sidx] = 1.18 if (sidx == self._active_slot_index or pos == 0) else 0.58
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
            self._dragging_orbit = True
            self._drag_last_pos = event.position()
            self._drag_moved_px = 0.0
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging_orbit:
            pos = event.position()
            dx = pos.x() - self._drag_last_pos.x()
            dy = pos.y() - self._drag_last_pos.y()
            self._drag_moved_px = getattr(self, "_drag_moved_px", 0.0) + abs(dx) + abs(dy)
            self._drag_last_pos = pos
            self._orbit_yaw += dx * 0.012
            self._orbit_pitch = max(-0.65, min(0.65, self._orbit_pitch + dy * 0.009))
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging_orbit:
            self._dragging_orbit = False
            if getattr(self, "_drag_moved_px", 0.0) < 6.0:
                cx, cy = self.width() * 0.5, self.height() * 0.5
                r = min(self.width(), self.height()) * 0.42
                dx = event.position().x() - cx
                dy = event.position().y() - cy
                if (dx * dx + dy * dy) <= (r * r):
                    self.hologram_clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._orbit_yaw = 0.0
            self._orbit_pitch = 0.05
            self.update()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

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
            speed_mul = 0.45
        else:
            eff_state = "idle"
            speed_mul = 0.45

        self._phase += dt * speed_mul
        if self._cast_slots:
            for pos, sl in enumerate(self._cast_slots):
                sidx = sl["slot_index"]
                is_act = (sidx == self._active_slot_index) or (
                    not any(x["slot_index"] == self._active_slot_index for x in self._cast_slots) and pos == 0
                )
                target_sc = 1.18 if is_act else 0.58
                cur_sc = float(self._slot_scales.get(sidx, target_sc))
                self._slot_scales[sidx] = cur_sc + (target_sc - cur_sc) * 0.18
        return {
            "effective_state": eff_state,
            "rms": float(self._smooth_rms),
            "mic": float(self._smooth_mic),
        }

    def _on_tick(self) -> None:
        self.step_simulation()
        self.update()

    def _paint_single_avatar_geometry(
        self,
        painter: QPainter,
        shape_id: str,
        cx: float,
        cy: float,
        scale: float,
        pal: dict[str, str],
        energy: float,
        mic_e: float,
        eff_state: str,
        bands: np.ndarray,
    ) -> None:
        c_core = QColor(pal["core"])
        c_pri = QColor(pal["primary"])
        c_sec = QColor(pal["secondary"])
        c_glow = QColor(pal["glow"])

        sid = shape_id or "neural_core"
        if sid == "cartoon_character":
            self._paint_cartoon_character(painter, cx, cy, scale, c_core, c_pri, c_sec, energy, mic_e, eff_state, bands)
            return

        self._draw_corona_bloom(painter, cx, cy, scale, c_core, c_pri, c_glow, energy, mic_e, eff_state, bands)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)

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

    def _draw_avatar_label_pill(
        self,
        painter: QPainter,
        cx: float,
        cy_bottom: float,
        label_text: str,
        primary_hex: str,
        is_active: bool,
    ) -> None:
        if not label_text:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        font = QFont("Segoe UI", 9 if is_active else 8, QFont.Weight.Bold if is_active else QFont.Weight.Medium)
        painter.setFont(font)
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(label_text)
        th = fm.height()
        pw = tw + 18
        ph = th + 8
        rx = max(6.0, min(float(self.width()) - pw - 6.0, cx - pw * 0.5))
        ry = max(6.0, min(float(self.height()) - ph - 6.0, cy_bottom))
        rect = QRectF(rx, ry, pw, ph)
        c_pri = QColor(primary_hex)
        bg = QColor(10, 16, 24, 215 if is_active else 160)
        border = QColor(c_pri.red(), c_pri.green(), c_pri.blue(), 220 if is_active else 105)
        painter.setBrush(bg)
        painter.setPen(QPen(border, 1.3 if is_active else 0.9))
        painter.drawRoundedRect(rect, 9.0, 9.0)
        painter.setPen(QColor("#f0f6fc") if is_active else QColor("#9ca3af"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, label_text)
        painter.restore()

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
        energy = float(self._smooth_rms)
        mic_e = 0.0
        bands = self._smooth_bands

        if len(self._cast_slots) <= 1:
            sl0 = self._cast_slots[0] if self._cast_slots else None
            use_shape = sl0["avatar_shape"] if sl0 else self._shape_id
            use_pal = (
                resolve_avatar_palette(sl0["avatar_palette"], self._theme_dict, sl0.get("provider_color", ""))
                if sl0
                else pal
            )
            cx, cy = w * 0.5, h * 0.48
            scale = min(w, h) * 0.34
            self._paint_single_avatar_geometry(painter, use_shape, cx, cy, scale, use_pal, energy, mic_e, eff_state, bands)
            if sl0 and sl0.get("speaker_name"):
                tag = f"{'🔊 ' if eff_state == 'speaking' else ''}{sl0['speaker_name']}"
                if sl0.get("persona_label"):
                    tag = f"{tag} · {sl0['persona_label'].split('—', 1)[0].strip()}"
                self._draw_avatar_label_pill(painter, cx, cy + scale * 1.18, tag, use_pal["primary"], True)
            return

        # Multi-Avatar Constellation Arc (2..4 AIs on stage with spotlight speaker scaling)
        n = len(self._cast_slots)
        base_scale = min(w / max(2.2, n * 1.35), h * 0.30) * 0.55
        active_pos = next((i for i, sl in enumerate(self._cast_slots) if sl["slot_index"] == self._active_slot_index), 0)
        x_lo = w * (0.24 if n == 2 else 0.16)
        x_hi = w * (0.76 if n == 2 else 0.84)
        zero_bands = np.zeros(16, dtype=np.float32)

        # Paint inactive listeners first, then the active speaker on top for crisp layering
        draw_order = [i for i in range(n) if i != active_pos] + [active_pos]
        for pos in draw_order:
            sl = self._cast_slots[pos]
            is_act = (pos == active_pos)
            frac = 0.5 if n == 1 else (pos / float(n - 1))
            cx = x_lo + (x_hi - x_lo) * frac
            # Gently pull active speaker toward center/foreground slightly
            if is_act:
                cx = cx * 0.82 + (w * 0.5) * 0.18
            cy = h * (0.48 if is_act else (0.39 if (pos % 2 == 0) else 0.44))
            mult = float(self._slot_scales.get(sl["slot_index"], 1.18 if is_act else 0.58))
            slot_scale = max(24.0, base_scale * mult)
            sl_pal = resolve_avatar_palette(sl["avatar_palette"], self._theme_dict, sl.get("provider_color", ""))
            sl_energy = energy if is_act else 0.0
            sl_mic = mic_e if is_act else 0.0
            sl_state = eff_state if is_act else "idle"
            sl_bands = bands if is_act else zero_bands
            self._paint_single_avatar_geometry(
                painter,
                sl["avatar_shape"],
                cx,
                cy,
                slot_scale,
                sl_pal,
                sl_energy,
                sl_mic,
                sl_state,
                sl_bands,
            )
            lbl = sl["speaker_name"]
            if is_act:
                lbl = f"{'🔊 ' if eff_state == 'speaking' else '● '}{lbl}"
                if sl.get("persona_label"):
                    short_role = sl["persona_label"].split("—", 1)[0].strip()
                    lbl = f"{lbl} · {short_role}"
            self._draw_avatar_label_pill(painter, cx, cy + slot_scale * 1.15, lbl, sl_pal["primary"], is_act)

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
                breath = 0.5 + 0.5 * math.sin(t * 1.4 + ang * 2.0)
                ray_len = br * (0.64 + 0.10 * breath) * float(weights[i])
                a_ray = int(12 + 12 * breath)
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
            breath = 1.0 + 0.035 * math.sin(t * 1.6)
            r_pts = r_pts * breath
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
            pts = verts * (1.0 + 0.05 * np.sin(t * 1.8 + phases)[:, None])
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

    def _resolve_effective_hw_tier(self) -> tuple[str, str]:
        """Determine effective 3D hardware tier ('full_3d', 'lite_3d', or '2d_fallback') and human-readable reason."""
        cfg = self._cartoon_cfg or DEFAULT_CARTOON_AVATAR_CONFIG
        manual = str(cfg.get("hw_tier") or "auto").lower()
        hw = detect_system_gpu_and_power(force_refresh=False)
        if hw.get("is_software"):
            return "2d_fallback", f"Software Renderer ({hw.get('gpu_name')}) → 2D Fallback"

        if manual in ("full_3d", "lite_3d", "2d_fallback"):
            tier, reason = manual, f"Manual Override ({manual.upper()})"
        else:
            bench = str(cfg.get("benchmarked_tier") or "").lower()
            if bench in ("full_3d", "lite_3d", "2d_fallback"):
                fps = float(cfg.get("benchmark_fps") or 0.0)
                tier, reason = bench, f"Auto-Benchmark ({fps:.1f} FPS on {hw.get('gpu_name')})"
            elif hw.get("is_dedicated"):
                tier, reason = "full_3d", f"Dedicated GPU Detected ({hw.get('gpu_name')})"
            else:
                tier, reason = "lite_3d", f"Integrated GPU ({hw.get('gpu_name')}) → UT Lite 3D"

        # Battery guard only steps down Full 3D -> Lite 3D when not explicitly forced to Full 3D; never promotes 2D Fallback upward
        if tier == "full_3d" and manual != "full_3d" and bool(cfg.get("sleep_3d_on_battery", True)) and hw.get("on_battery"):
            return "lite_3d", f"On Battery ({hw.get('battery_pct', 100)}%) → Battery Guard Lite 3D"
        return tier, reason

    def _load_portrait_qimage(self, preset_id: str, custom_path: str = "") -> tuple[QImage | None, dict[str, Any]]:
        """Load & cache the high-res 3D Studio or Lifelike Portrait image and its facial landmark preset."""
        pid = str(preset_id or "pixar_3d_female").lower()
        meta = dict(AVATAR_PORTRAIT_PRESETS.get(pid, AVATAR_PORTRAIT_PRESETS["pixar_3d_female"]))
        if custom_path:
            cached = getattr(self, "_custom_portrait_cache", None)
            now = time.monotonic()
            same_path = cached is not None and cached[0] == custom_path
            if same_path and now < cached[1]:
                im = cached[3]
            else:
                from stat import S_ISREG

                signature = None
                try:
                    info = Path(custom_path).stat()
                    if S_ISREG(info.st_mode):
                        signature = (info.st_mtime_ns, info.st_ctime_ns, info.st_size, info.st_ino)
                except (OSError, ValueError):
                    pass
                if same_path and cached[2] == signature:
                    im = cached[3]
                else:
                    im = None
                    if signature is not None:
                        decoded = QImage(custom_path)
                        if not decoded.isNull():
                            filled = decoded.scaled(
                                720, 720, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation
                            )
                            crop_x = max(0, (filled.width() - 720) // 2)
                            crop_y = max(0, (filled.height() - 720) // 2)
                            im = filled.copy(crop_x, crop_y, 720, 720)
                self._custom_portrait_cache = (custom_path, now + 0.5, signature, im)
            if im is not None and not im.isNull():
                meta["_custom_image"] = True
                return im, meta

        fname = str(meta.get("filename") or "pixar_3d_female.png")
        cache_key = f"builtin:{fname}"
        if cache_key not in self._portrait_img_cache:
            candidates = [
                Path(__file__).resolve().parent / "assets" / "avatars" / fname,
                Path(r"E:\Visual_studio\Palace\assets\avatars") / fname,
                Path(r"C:\Palace_Live\assets\avatars") / fname,
            ]
            for cand in candidates:
                if cand.is_file():
                    im = QImage(str(cand))
                    if not im.isNull():
                        self._portrait_img_cache[cache_key] = im
                        break
        return self._portrait_img_cache.get(cache_key), meta

    def _paint_portrait_avatar(
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
        hw_tier: str,
        hw_reason: str,
    ) -> bool:
        """Render true 3D Pixar Studio or Lifelike Photorealistic portrait with 60 FPS breathing, natural dual-eye blink, and audio-driven jaw/lip-sync."""
        cfg = self._cartoon_cfg or DEFAULT_CARTOON_AVATAR_CONFIG
        eng = str(cfg.get("engine_mode") or "studio_3d").lower()
        gender = str(cfg.get("gender") or "female").lower()
        preset_id = str(cfg.get("preset_id") or "").lower()
        if eng == "lifelike_portrait":
            if preset_id not in ("lifelike_girl", "lifelike_male", "custom"):
                preset_id = "lifelike_male" if gender == "male" else "lifelike_girl"
        elif eng == "voxel_3d":
            if preset_id not in ("brick_movie_male", "brick_movie_female", "custom"):
                preset_id = "brick_movie_male" if gender == "male" else "brick_movie_female"
        else:
            if preset_id not in ("pixar_3d_female", "pixar_3d_male", "custom"):
                preset_id = "pixar_3d_male" if gender == "male" else "pixar_3d_female"

        custom_p = str(cfg.get("custom_portrait_path") or "").strip() if preset_id == "custom" else ""
        img, meta = self._load_portrait_qimage(preset_id, custom_p)
        if img is None or img.isNull():
            return False

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        t = self._phase

        # 1. Audio-reactive studio rim aura behind the portrait frame
        aura_r = scale * (1.36 + 0.16 * energy + 0.06 * mic_e)
        bg_grad = QRadialGradient(QPointF(cx, cy), aura_r)
        if eff_state == "speaking":
            aura_c = QColor(c_pri.red(), c_pri.green(), c_pri.blue(), int(min(170, 75 + energy * 125)))
        elif eff_state == "thinking":
            aura_c = QColor(245, 158, 11, 95)
        elif eff_state == "listening":
            aura_c = QColor(34, 197, 94, int(65 + mic_e * 85))
        else:
            aura_c = QColor(99, 102, 241, 55)
        bg_grad.setColorAt(0.0, aura_c)
        bg_grad.setColorAt(0.72, QColor(18, 24, 38, 65))
        bg_grad.setColorAt(1.0, QColor(6, 8, 14, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg_grad)
        painter.drawEllipse(QPointF(cx, cy), aura_r, aura_r)

        # 2. Organic breathing & 2.5D head drift / parallax
        breath_y = math.sin(t * 1.45) * scale * 0.014
        breath_scale = 1.0 + math.sin(t * 1.45) * 0.008
        drift_x = math.sin(t * 0.72) * scale * 0.016 + (self._orbit_yaw * scale * 0.08)
        drift_y = math.cos(t * 0.58) * scale * 0.010 + (self._orbit_pitch * scale * 0.06)
        head_tilt = math.sin(t * 0.65) * 1.15 if eff_state != "speaking" else math.sin(t * 2.6) * (0.9 + energy * 1.8)

        box_s = scale * 2.18 * breath_scale
        dest_rect = QRectF(cx - box_s * 0.5 + drift_x, cy - box_s * 0.50 + breath_y + drift_y, box_s, box_s)
        if meta.get("_custom_image"):
            fit = box_s / max(img.width(), img.height())
            fit_w, fit_h = img.width() * fit, img.height() * fit
            mid = dest_rect.center()
            dest_rect = QRectF(mid.x() - fit_w * 0.5, mid.y() - fit_h * 0.5, fit_w, fit_h)

        painter.save()
        painter.translate(dest_rect.center())
        painter.rotate(head_tilt)
        painter.translate(-dest_rect.center())

        # Clip portrait to a sleek rounded studio cinema frame
        clip_path = QPainterPath()
        clip_path.addRoundedRect(dest_rect, scale * 0.24, scale * 0.24)
        painter.setClipPath(clip_path)

        iw, ih = float(img.width()), float(img.height())
        painter.drawImage(dest_rect, img, QRectF(0.0, 0.0, iw, ih))

        # 3. Dual-Eye Blink Mask (Council Rule: two separate eye masks with zero nose-bridge pinch)
        blink_cycle = (t * 0.34) % 1.0
        blink_amt = 0.0
        if blink_cycle > 0.92:
            blink_amt = math.sin(((blink_cycle - 0.92) / 0.08) * math.pi)
        elif 0.46 < blink_cycle < 0.52 and eff_state == "thinking":
            blink_amt = math.sin(((blink_cycle - 0.46) / 0.06) * math.pi)

        if blink_amt > 0.04 and hw_tier != "2d_fallback":
            for ek in ("eye_l", "eye_r"):
                rx, ry, rw, rh = meta.get(ek, (0.35, 0.35, 0.12, 0.07))
                # Sample upper eyelid / brow skin strip just above the eye box and fold it down smoothly
                src_lid = QRectF(rx * iw, max(0.0, (ry - rh * 0.55) * ih), rw * iw, rh * 0.55 * ih)
                dst_eye = QRectF(
                    dest_rect.left() + rx * dest_rect.width(),
                    dest_rect.top() + ry * dest_rect.height(),
                    rw * dest_rect.width(),
                    rh * dest_rect.height() * min(1.0, blink_amt * 1.08),
                )
                lid_clip = QPainterPath()
                lid_clip.addRoundedRect(dst_eye, dst_eye.height() * 0.45, dst_eye.height() * 0.45)
                painter.save()
                painter.setClipPath(clip_path.intersected(lid_clip))
                painter.drawImage(dst_eye, img, src_lid)
                # Subtle eyelash crease line at bottom of closed lid
                lash_y = dst_eye.bottom() - 1.0
                painter.setPen(QPen(QColor(28, 18, 14, int(175 * blink_amt)), max(1.4, scale * 0.015)))
                painter.drawLine(QPointF(dst_eye.left() + 3.0, lash_y), QPointF(dst_eye.right() - 3.0, lash_y))
                painter.restore()

        # 4. Real-Time Audio-Driven Jaw & Lip-Sync Warp (clamped to max_drop ~0.055 so loud syllables never unhinge the chin)
        jaw_sens = max(0.5, min(1.8, float(cfg.get("jaw_sensitivity", 100)) / 100.0))
        low_band = float(np.mean(bands[1:5])) if bands.size >= 5 else energy
        mid_band = float(np.mean(bands[5:11])) if bands.size >= 11 else energy
        jaw_open = 0.0
        if eff_state == "speaking":
            raw_open = (energy * 0.68 + low_band * 0.42 + mid_band * 0.25) * jaw_sens
            jaw_open = max(0.02, min(1.0, raw_open * (0.78 + 0.22 * math.sin(t * 15.0))))

        if jaw_open > 0.015 and hw_tier != "2d_fallback":
            jrx, jry, jrw, jrh = meta.get("jaw", (0.33, 0.50, 0.38, 0.16))
            mrx, mry, mrw, mrh = meta.get("mouth", (0.41, 0.50, 0.22, 0.08))
            max_drop_frac = float(meta.get("max_drop", 0.055)) * 0.65
            drop_px = dest_rect.height() * max_drop_frac * jaw_open

            src_jaw = QRectF(jrx * iw, (jry + mrh * 0.44) * ih, jrw * iw, jrh * ih)
            dst_jaw = QRectF(
                dest_rect.left() + jrx * dest_rect.width(),
                dest_rect.top() + (jry + mrh * 0.44) * dest_rect.height() + drop_px,
                jrw * dest_rect.width(),
                jrh * dest_rect.height(),
            )
            jaw_oval = QPainterPath()
            jaw_oval.addRoundedRect(dst_jaw, dst_jaw.width() * 0.42, dst_jaw.height() * 0.46)
            painter.save()
            painter.setClipPath(clip_path.intersected(jaw_oval))
            painter.drawImage(dst_jaw, img, src_jaw)
            painter.restore()

            # Subtle natural lip-part shadow seam right along the lip line
            mouth_cx = dest_rect.left() + (mrx + mrw * 0.5) * dest_rect.width()
            mouth_cy = dest_rect.top() + (mry + mrh * 0.52) * dest_rect.height() + drop_px * 0.25
            mouth_w = mrw * dest_rect.width() * (0.36 + 0.10 * mid_band)
            mouth_h = max(1.5, min(dest_rect.height() * 0.022, drop_px * 0.68))
            mouth_path = QPainterPath()
            mouth_path.addRoundedRect(
                QRectF(mouth_cx - mouth_w * 0.5, mouth_cy - mouth_h * 0.5, mouth_w, mouth_h),
                mouth_h * 0.5,
                mouth_h * 0.5,
            )
            painter.save()
            painter.setClipPath(clip_path.intersected(mouth_path))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(42, 16, 20, int(min(145, 70 + jaw_open * 75))))
            painter.drawPath(mouth_path)
            painter.restore()

        # 5. Optional One-Click Landmark Debug Overlay (Council Recommendation #1)
        if bool(cfg.get("show_landmark_overlay", False)):
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#38bdf8"), 1.6))
            for ek in ("eye_l", "eye_r"):
                rx, ry, rw, rh = meta.get(ek, (0.35, 0.35, 0.12, 0.07))
                painter.drawRect(
                    QRectF(
                        dest_rect.left() + rx * dest_rect.width(),
                        dest_rect.top() + ry * dest_rect.height(),
                        rw * dest_rect.width(),
                        rh * dest_rect.height(),
                    )
                )
            painter.setPen(QPen(QColor("#4ade80"), 1.6))
            rx, ry, rw, rh = meta.get("mouth", (0.41, 0.50, 0.22, 0.08))
            painter.drawRect(
                QRectF(
                    dest_rect.left() + rx * dest_rect.width(),
                    dest_rect.top() + ry * dest_rect.height(),
                    rw * dest_rect.width(),
                    rh * dest_rect.height(),
                )
            )
            painter.setPen(QPen(QColor("#f59e0b"), 1.4, Qt.PenStyle.DashLine))
            rx, ry, rw, rh = meta.get("jaw", (0.33, 0.50, 0.38, 0.16))
            painter.drawRect(
                QRectF(
                    dest_rect.left() + rx * dest_rect.width(),
                    dest_rect.top() + ry * dest_rect.height(),
                    rw * dest_rect.width(),
                    rh * dest_rect.height(),
                )
            )

        painter.restore()  # Undo clip & tilt

        # Outer glowing cinema frame border reactive to voice
        border_col = QColor(c_pri.red(), c_pri.green(), c_pri.blue(), int(min(235, 95 + energy * 135)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(border_col, max(1.8, scale * 0.02 + energy * 2.2)))
        painter.drawRoundedRect(dest_rect, scale * 0.24, scale * 0.24)

        # Subtle hardware tier & engine badge in top-right of frame
        badge_txt = f"{'LivePortrait' if cfg.get('comfyui_live_bridge') else ('3D Studio' if eng == 'studio_3d' else 'Lifelike HD')} | {hw_tier.replace('_', ' ').upper()}"
        self._draw_hw_status_pill(painter, dest_rect.center().x(), dest_rect.bottom() + scale * 0.08, badge_txt, hw_reason)
        painter.restore()
        return True

    def _paint_ut_goty_3d_mesh(
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
        hw_tier: str,
        hw_reason: str,
    ) -> None:
        """Unreal Tournament GOTY Edition style 360-degree rotatable 3D polygon mesh character with Z-buffered Phong lighting, jaw bone & blink morphs."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, hw_tier == "full_3d")
        t = self._phase
        cfg = self._cartoon_cfg or DEFAULT_CARTOON_AVATAR_CONFIG
        gender = str(cfg.get("gender") or "male").lower()
        skin_key = str(cfg.get("skin_tone") or "warm_light").lower()
        hair_col_key = str(cfg.get("hair_color") or "chestnut").lower()
        eye_col_key = str(cfg.get("eye_color") or "hazel").lower()
        outfit_key = str(cfg.get("outfit_color") or "navy_hoodie").lower()

        _, skin_hex, *_ = CARTOON_SKIN_TONES.get(skin_key, CARTOON_SKIN_TONES["warm_light"])
        _, hair_hex, *_ = CARTOON_HAIR_COLORS.get(hair_col_key, CARTOON_HAIR_COLORS["chestnut"])
        _, eye_hex = CARTOON_EYE_COLORS.get(eye_col_key, CARTOON_EYE_COLORS["hazel"])
        _, outfit_hex, *_ = CARTOON_OUTFIT_COLORS.get(outfit_key, CARTOON_OUTFIT_COLORS["navy_hoodie"])

        custom_obj = str(cfg.get("custom_model_path") or "").strip()
        mesh = None
        if custom_obj:
            if custom_obj not in self._custom_obj_cache:
                loaded = load_custom_obj_3d_mesh(custom_obj)
                if loaded is not None:
                    self._custom_obj_cache[custom_obj] = loaded
            mesh = self._custom_obj_cache.get(custom_obj)
        if mesh is None:
            mesh = self._mesh_ut_male if gender == "male" else self._mesh_ut_female

        # Studio backdrop aura
        aura_r = scale * (1.32 + 0.15 * energy)
        bg_grad = QRadialGradient(QPointF(cx, cy), aura_r)
        bg_grad.setColorAt(0.0, QColor(c_pri.red(), c_pri.green(), c_pri.blue(), int(60 + energy * 100)))
        bg_grad.setColorAt(1.0, QColor(5, 8, 15, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg_grad)
        painter.drawEllipse(QPointF(cx, cy), aura_r, aura_r)

        verts = mesh["verts"].copy()
        n_v = len(verts)
        jaw_w = mesh.get("jaw_w", np.zeros(n_v, dtype=np.float32))
        blink_w = mesh.get("blink_w", np.zeros(n_v, dtype=np.float32))
        tris = mesh["tris"]
        tri_zones = mesh.get("tri_zones", np.zeros(len(tris), dtype=np.int32))

        # Apply real-time audio jaw bone morph
        jaw_sens = max(0.5, min(1.8, float(cfg.get("jaw_sensitivity", 100)) / 100.0))
        low_b = float(np.mean(bands[1:5])) if bands.size >= 5 else energy
        jaw_open = 0.0
        if eff_state == "speaking":
            jaw_open = min(1.0, (energy * 0.72 + low_b * 0.45) * jaw_sens * (0.75 + 0.25 * math.sin(t * 14.0)))
        verts[:, 1] += jaw_w * (0.14 * jaw_open)
        verts[:, 2] -= jaw_w * (0.04 * jaw_open)

        # Apply 360-degree user mouse drag orbit + subtle idle breathing sway
        yaw = self._orbit_yaw + math.sin(t * 0.55) * 0.14
        pitch = self._orbit_pitch + math.cos(t * 0.45) * 0.05
        rot = _rotation_matrix_xyz(pitch, yaw, 0.0)
        r_verts = verts @ rot.T

        # Perspective projection
        fov_d = 3.2
        z_cam = fov_d - r_verts[:, 2]
        inv_z = 1.0 / np.maximum(0.4, z_cam)
        proj_scale = scale * 1.08 * fov_d
        sx = cx + r_verts[:, 0] * inv_z * proj_scale
        sy = cy + r_verts[:, 1] * inv_z * proj_scale

        # Compute face normals and painter's algorithm Z-sort
        v0 = r_verts[tris[:, 0]]
        v1 = r_verts[tris[:, 1]]
        v2 = r_verts[tris[:, 2]]
        normals = np.cross(v1 - v0, v2 - v0)
        n_len = np.linalg.norm(normals, axis=1, keepdims=True)
        normals = normals / np.maximum(1e-6, n_len)

        # Back-face culling using 2D screen-space signed area (cross product of projected screen triangle edges)
        tri_centers_z = (v0[:, 2] + v1[:, 2] + v2[:, 2]) / 3.0
        order = np.argsort(tri_centers_z)  # Back to front

        # Key light + rim light directions (pointing toward +Z front camera)
        light_dir = np.array([0.38, -0.35, 0.85], dtype=np.float32)
        light_dir /= np.linalg.norm(light_dir)
        rim_dir = np.array([-0.65, -0.25, 0.71], dtype=np.float32)
        rim_dir /= np.linalg.norm(rim_dir)

        c_skin_rgb = QColor(skin_hex)
        c_hair_rgb = QColor(hair_hex)
        c_beard_rgb = QColor(hair_hex).darker(118) if gender == "male" else c_skin_rgb
        c_eye_rgb = QColor(eye_hex)
        c_armor_rgb = QColor(outfit_hex)
        c_mouth_rgb = QColor("#3b1219") if jaw_open > 0.12 else QColor("#8f444c")

        blink_cycle = (t * 0.34) % 1.0
        is_blinking = (blink_cycle > 0.92)

        zone_colors = [c_skin_rgb, c_hair_rgb, c_beard_rgb, c_eye_rgb, c_armor_rgb, c_mouth_rgb]
        wire_pen = QPen(QColor(c_pri.red(), c_pri.green(), c_pri.blue(), 42), 0.7) if hw_tier == "full_3d" else Qt.PenStyle.NoPen

        for f_idx in order:
            i0, i1, i2 = int(tris[f_idx, 0]), int(tris[f_idx, 1]), int(tris[f_idx, 2])
            x0, y0 = float(sx[i0]), float(sy[i0])
            x1, y1 = float(sx[i1]), float(sy[i1])
            x2, y2 = float(sx[i2]), float(sy[i2])
            signed_area = (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)
            if signed_area <= 0.0:
                continue
            fn = normals[f_idx]  # Outward-pointing surface normal
            z_id = int(tri_zones[f_idx])
            base_c = c_skin_rgb if (z_id == 3 and is_blinking) else zone_colors[min(len(zone_colors) - 1, max(0, z_id))]
            ndotl = max(0.0, float(np.dot(fn, light_dir)))
            rim = max(0.0, float(np.dot(fn, rim_dir))) ** 2.0 if hw_tier == "full_3d" else 0.0
            shade = min(1.35, 0.38 + 0.68 * ndotl + 0.25 * rim)

            r_c = min(255, int(base_c.red() * shade + (c_pri.red() * 0.18 * rim)))
            g_c = min(255, int(base_c.green() * shade + (c_pri.green() * 0.18 * rim)))
            b_c = min(255, int(base_c.blue() * shade + (c_pri.blue() * 0.18 * rim)))

            poly = QPolygonF([QPointF(x0, y0), QPointF(x1, y1), QPointF(x2, y2)])
            painter.setBrush(QColor(r_c, g_c, b_c))
            painter.setPen(wire_pen)
            painter.drawPolygon(poly)

            # Add crisp iris specular catchlight dot on visible eye-socket triangles
            if z_id == 3 and not is_blinking:
                ecx = (x0 + x1 + x2) / 3.0
                ecy = (y0 + y1 + y2) / 3.0
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(255, 255, 255, 225))
                painter.drawEllipse(QPointF(ecx - 1.2, ecy - 1.2), max(1.8, scale * 0.018), max(1.8, scale * 0.018))

        deg_yaw = int(round((self._orbit_yaw * 180.0 / math.pi) % 360))
        badge = f"UT 3D Mesh ({deg_yaw} deg - Drag to Spin 360) | {hw_tier.replace('_', ' ').upper()}"
        self._draw_hw_status_pill(painter, cx, cy + scale * 1.16, badge, hw_reason)
        painter.restore()

    def _paint_voxel_3d_character(
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
        hw_tier: str,
        hw_reason: str,
    ) -> None:
        """2-Layer 3D Voxel / Block Character (8x8x8 pixel-textured head cube + raised 3D hair/beard/glasses shell + blocky torso & shoulders) with 360-degree mouse spin, blinking eyes & 4-state talking voxel mouth."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        t = self._phase
        cfg = self._cartoon_cfg or DEFAULT_CARTOON_AVATAR_CONFIG
        gender = str(cfg.get("gender") or "male").lower()
        skin_key = str(cfg.get("skin_tone") or "warm_light").lower()
        hair_style = str(cfg.get("hair_style") or ("short_crop" if gender == "male" else "cozy_bun")).lower()
        hair_col_key = str(cfg.get("hair_color") or "chestnut").lower()
        eye_col_key = str(cfg.get("eye_color") or "hazel").lower()
        outfit_key = str(cfg.get("outfit_color") or ("navy_hoodie" if gender == "male" else "cream")).lower()
        facial_hair = str(cfg.get("facial_hair") or ("beard" if gender == "male" else "none")).lower()
        has_glasses = bool(cfg.get("glasses", False))

        if gender == "male":
            if hair_style in {"cozy_bun", "long_wavy", "curly"}:
                hair_style = "short_crop"
            if outfit_key == "cream":
                outfit_key = "navy_hoodie"
        else:
            facial_hair = "none"

        _, skin_hex, skin_sh_hex, blush_hex = CARTOON_SKIN_TONES.get(skin_key, CARTOON_SKIN_TONES["warm_light"])
        _, hair_hex, hair_hi_hex = CARTOON_HAIR_COLORS.get(hair_col_key, CARTOON_HAIR_COLORS["chestnut"])
        _, eye_hex = CARTOON_EYE_COLORS.get(eye_col_key, CARTOON_EYE_COLORS["hazel"])
        _, outfit_hex, outfit_sh_hex = CARTOON_OUTFIT_COLORS.get(outfit_key, CARTOON_OUTFIT_COLORS["navy_hoodie"])

        c_skin = QColor(skin_hex)
        c_skin_sh = QColor(skin_sh_hex)
        c_blush = QColor(blush_hex)
        c_hair = QColor(hair_hex)
        c_hair_hi = QColor(hair_hi_hex)
        c_beard = QColor(hair_hex).darker(118)
        c_eye = QColor(eye_hex)
        c_white = QColor("#f8fafc")
        c_outfit = QColor(outfit_hex)
        c_outfit_sh = QColor(outfit_sh_hex)
        c_mouth_dark = QColor("#3b1219")
        c_lip = QColor("#b85d63") if gender == "female" else QColor("#8f444c")

        # Studio backdrop aura
        aura_r = scale * (1.34 + 0.16 * energy)
        bg_grad = QRadialGradient(QPointF(cx, cy), aura_r)
        bg_grad.setColorAt(0.0, QColor(c_pri.red(), c_pri.green(), c_pri.blue(), int(65 + energy * 105)))
        bg_grad.setColorAt(1.0, QColor(5, 8, 15, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg_grad)
        painter.drawEllipse(QPointF(cx, cy), aura_r, aura_r)

        # Blink and audio jaw state
        blink_cycle = (t * 0.34) % 1.0
        is_blinking = (blink_cycle > 0.92)
        jaw_sens = max(0.5, min(1.8, float(cfg.get("jaw_sensitivity", 100)) / 100.0))
        low_b = float(np.mean(bands[1:5])) if bands.size >= 5 else energy
        jaw_open = 0.0
        if eff_state == "speaking":
            jaw_open = min(1.0, (energy * 0.72 + low_b * 0.45) * jaw_sens * (0.76 + 0.24 * math.sin(t * 15.0)))

        # Build 3D textured voxel quads: each quad is (v0, v1, v2, v3, QColor)
        # Coordinate system: X right (-1..+1), Y down (-1..+1), Z front (+1 toward camera)
        quads: list[tuple[np.ndarray, QColor]] = []

        def _add_face_grid(
            origin: tuple[float, float, float],
            u_vec: tuple[float, float, float],
            v_vec: tuple[float, float, float],
            grid_colors: list[list[QColor | None]],
        ) -> None:
            rows = len(grid_colors)
            cols = len(grid_colors[0]) if rows > 0 else 0
            if rows == 0 or cols == 0:
                return
            ox, oy, oz = origin
            ux, uy, uz = u_vec
            vx, vy, vz = v_vec
            for r in range(rows):
                v0_f = r / float(rows)
                v1_f = (r + 1) / float(rows)
                for c in range(cols):
                    col_c = grid_colors[r][c]
                    if col_c is None:
                        continue
                    u0_f = c / float(cols)
                    u1_f = (c + 1) / float(cols)
                    p0 = [ox + ux * u0_f + vx * v0_f, oy + uy * u0_f + vy * v0_f, oz + uz * u0_f + vz * v0_f]
                    p1 = [ox + ux * u1_f + vx * v0_f, oy + uy * u1_f + vy * v0_f, oz + uz * u1_f + vz * v0_f]
                    p2 = [ox + ux * u1_f + vx * v1_f, oy + uy * u1_f + vy * v1_f, oz + uz * u1_f + vz * v1_f]
                    p3 = [ox + ux * u0_f + vx * v1_f, oy + uy * u0_f + vy * v1_f, oz + uz * u0_f + vz * v1_f]
                    quads.append((np.array([p0, p1, p2, p3], dtype=np.float32), col_c))

        def _skin_px(r: int, c: int) -> QColor:
            # Subtle checkerboard pixel texture variation so voxel faces look authentic
            if (r + c) % 3 == 0:
                return c_skin.darker(104)
            if (r * 3 + c) % 5 == 0:
                return c_skin.lighter(103)
            return c_skin

        def _hair_px(r: int, c: int) -> QColor:
            if (r + c) % 2 == 0:
                return c_hair
            if (r * 2 + c) % 3 == 0:
                return c_hair_hi
            return c_hair.darker(110)

        def _outfit_px(r: int, c: int) -> QColor:
            return c_outfit if (r + c) % 2 == 0 else c_outfit_sh

        # ── 1. Inner 8x8x8 Voxel Head Cube (X: -0.44..+0.44, Y: -0.78..+0.10, Z: -0.44..+0.44) ──
        hx0, hx1 = -0.44, 0.44
        hy0, hy1 = -0.78, 0.10 + (0.045 * jaw_open)
        hz0, hz1 = -0.44, 0.44
        hw = hx1 - hx0
        hh = hy1 - hy0
        hd = hz1 - hz0

        # Front Face (8x8 pixel grid at Z = +0.44)
        front_grid: list[list[QColor | None]] = [[_skin_px(r, c) for c in range(8)] for r in range(8)]
        # Top hair hairline on rows 0..1
        for c in range(8):
            front_grid[0][c] = _hair_px(0, c)
            if c in (0, 1, 6, 7) or (gender == "female" and c in (2, 5)):
                front_grid[1][c] = _hair_px(1, c)
        # Pixel Brows on row 2
        for c in (1, 2, 5, 6):
            front_grid[2][c] = c_hair.darker(115)
        # Pixel Eyes on row 3 (2x1 voxel eyes: white sclera on outer pixel, colored iris on inner pixel)
        if is_blinking:
            for c in (1, 2, 5, 6):
                front_grid[3][c] = c_skin_sh.darker(112)
        else:
            front_grid[3][1] = c_white
            front_grid[3][2] = c_eye
            front_grid[3][5] = c_eye
            front_grid[3][6] = c_white
        # Nose pixel on row 4..5 cols 3..4
        front_grid[4][3] = c_skin_sh
        front_grid[4][4] = c_skin_sh.darker(106)
        if gender == "female":
            front_grid[4][1] = c_blush
            front_grid[4][6] = c_blush

        # Beard / Stubble & Audio-Reactive Voxel Mouth on rows 5..7
        if facial_hair in ("beard", "stubble") and gender == "male":
            b_col = c_beard if facial_hair == "beard" else c_skin_sh.darker(120)
            for c in (0, 1, 6, 7):
                front_grid[5][c] = b_col
                front_grid[6][c] = b_col
            for c in range(8):
                front_grid[7][c] = b_col.darker(108) if (c % 2 == 0) else b_col
            # Mustache above mouth
            for c in (2, 3, 4, 5):
                front_grid[5][c] = b_col.darker(110)
        # Mouth pixels on row 6 (and row 5/7 when talking loudly)
        if jaw_open > 0.38:
            front_grid[6][3] = c_mouth_dark
            front_grid[6][4] = c_mouth_dark
            front_grid[6][2] = c_lip
            front_grid[6][5] = c_lip
            if jaw_open > 0.68:
                front_grid[5][3] = c_white  # Upper voxel teeth flash
                front_grid[5][4] = c_white
        elif jaw_open > 0.10:
            front_grid[6][3] = c_mouth_dark
            front_grid[6][4] = c_mouth_dark
        else:
            front_grid[6][2] = c_lip
            front_grid[6][3] = c_lip
            front_grid[6][4] = c_lip
            front_grid[6][5] = c_lip

        _add_face_grid((hx0, hy0, hz1), (hw, 0.0, 0.0), (0.0, hh, 0.0), front_grid)

        # Back Face (8x8 hair & neck at Z = -0.44)
        back_grid: list[list[QColor | None]] = [
            [_hair_px(r, c) if (r < 6 or gender == "female") else _skin_px(r, c) for c in range(8)]
            for r in range(8)
        ]
        _add_face_grid((hx1, hy0, hz0), (-hw, 0.0, 0.0), (0.0, hh, 0.0), back_grid)

        # Left & Right Head Faces (8x8 with sideburns, ear pixels, and beard strap)
        for is_right in (False, True):
            side_grid: list[list[QColor | None]] = [[_skin_px(r, c) for c in range(8)] for r in range(8)]
            for r in range(8):
                for c in range(8):
                    # c=0 is front edge, c=7 is back of head
                    if r < 2 or c >= 4 or (r < 4 and c >= 2):
                        side_grid[r][c] = _hair_px(r, c)
                    elif facial_hair in ("beard", "stubble") and gender == "male" and r >= 5 and c <= 3:
                        side_grid[r][c] = c_beard
                    elif r in (3, 4) and c == 3:
                        side_grid[r][c] = c_skin_sh  # Voxel ear shadow
            if is_right:
                _add_face_grid((hx1, hy0, hz1), (0.0, 0.0, -hd), (0.0, hh, 0.0), side_grid)
            else:
                _add_face_grid((hx0, hy0, hz0), (0.0, 0.0, hd), (0.0, hh, 0.0), [row[::-1] for row in side_grid])

        # Top & Bottom Head Faces
        top_grid: list[list[QColor | None]] = [[_hair_px(r, c) for c in range(8)] for r in range(8)]
        _add_face_grid((hx0, hy0, hz0), (hw, 0.0, 0.0), (0.0, 0.0, hd), top_grid)
        bot_col = c_beard if (facial_hair == "beard" and gender == "male") else c_skin_sh
        bot_grid: list[list[QColor | None]] = [[bot_col for _ in range(4)] for _ in range(4)]
        _add_face_grid((hx0, hy1, hz1), (hw, 0.0, 0.0), (0.0, 0.0, -hd), bot_grid)

        # ── 2. Raised Outer 3D Voxel Layer (3D Hair Crown / Top-Bun / Raised Beard & 3D Voxel Glasses) ──
        ox0, ox1 = -0.475, 0.475
        oy0, oy1 = -0.82, 0.12 + (0.045 * jaw_open)
        oz0, oz1 = -0.475, 0.475
        ow, oh, od = ox1 - ox0, oy1 - oy0, oz1 - oz0

        # Raised 3D Hair Cap on Top
        _add_face_grid((ox0, oy0, oz0), (ow, 0.0, 0.0), (0.0, 0.0, od), top_grid)
        # Raised 3D Front Bangs + Raised 3D Beard / Glasses Shell
        outer_front: list[list[QColor | None]] = [[None for _ in range(8)] for _ in range(8)]
        for c in range(8):
            outer_front[0][c] = _hair_px(0, c).lighter(108)
        if gender == "female":
            outer_front[1][0] = _hair_px(1, 0)
            outer_front[1][7] = _hair_px(1, 7)
            outer_front[2][0] = _hair_px(2, 0)
            outer_front[2][7] = _hair_px(2, 7)
        if facial_hair == "beard" and gender == "male":
            for c in (1, 2, 3, 4, 5, 6):
                outer_front[7][c] = c_beard.lighter(105)
            outer_front[6][1] = c_beard
            outer_front[6][6] = c_beard
        if has_glasses:
            g_col = QColor("#38bdf8")
            for c in (1, 2, 5, 6):
                outer_front[2][c] = g_col
                outer_front[4][c] = g_col
            outer_front[3][0] = g_col
            outer_front[3][3] = g_col
            outer_front[3][4] = g_col
            outer_front[3][7] = g_col
        _add_face_grid((ox0, oy0, oz1), (ow, 0.0, 0.0), (0.0, oh, 0.0), outer_front)

        # Optional 3D Voxel Top-Bun cube for female cozy_bun style
        if gender == "female" and hair_style == "cozy_bun":
            bx0, bx1 = -0.22, 0.22
            by0, by1 = -0.98, -0.78
            bz0, bz1 = -0.26, 0.18
            bw, bh, bd = bx1 - bx0, by1 - by0, bz1 - bz0
            bun_g: list[list[QColor | None]] = [[_hair_px(r, c) for c in range(4)] for r in range(4)]
            _add_face_grid((bx0, by0, bz1), (bw, 0.0, 0.0), (0.0, bh, 0.0), bun_g)
            _add_face_grid((bx1, by0, bz0), (-bw, 0.0, 0.0), (0.0, bh, 0.0), bun_g)
            _add_face_grid((bx0, by0, bz0), (0.0, 0.0, bd), (0.0, bh, 0.0), bun_g)
            _add_face_grid((bx1, by0, bz1), (0.0, 0.0, -bd), (0.0, bh, 0.0), bun_g)
            _add_face_grid((bx0, by0, bz0), (bw, 0.0, 0.0), (0.0, 0.0, bd), bun_g)

        # ── 3. Articulated 3D Blocky Torso & Shoulders (X: -0.76..+0.76, Y: 0.12..1.05, Z: -0.26..+0.26) ──
        breath_y = math.sin(t * 1.5) * 0.02
        tx0, tx1 = -0.76, 0.76
        ty0, ty1 = 0.13 + breath_y, 1.05 + breath_y
        tz0, tz1 = -0.26, 0.26
        tw, th, td = tx1 - tx0, ty1 - ty0, tz1 - tz0
        torso_front: list[list[QColor | None]] = [[_outfit_px(r, c) for c in range(12)] for r in range(6)]
        # Voxel collar V-neck cutout at top center of torso
        torso_front[0][5] = c_skin_sh
        torso_front[0][6] = c_skin_sh
        _add_face_grid((tx0, ty0, tz1), (tw, 0.0, 0.0), (0.0, th, 0.0), torso_front)
        _add_face_grid((tx1, ty0, tz0), (-tw, 0.0, 0.0), (0.0, th, 0.0), torso_front)
        side_torso: list[list[QColor | None]] = [[_outfit_px(r, c).darker(112) for c in range(4)] for r in range(6)]
        _add_face_grid((tx0, ty0, tz0), (0.0, 0.0, td), (0.0, th, 0.0), side_torso)
        _add_face_grid((tx1, ty0, tz1), (0.0, 0.0, -td), (0.0, th, 0.0), side_torso)
        top_torso: list[list[QColor | None]] = [[_outfit_px(r, c).lighter(108) for c in range(12)] for r in range(4)]
        _add_face_grid((tx0, ty0, tz0), (tw, 0.0, 0.0), (0.0, 0.0, td), top_torso)

        # ── 4. Project & Z-Sort All 3D Voxel Quads with Directional Voxel Shading ──
        yaw = self._orbit_yaw + math.sin(t * 0.65) * 0.22
        pitch = self._orbit_pitch + math.cos(t * 0.50) * 0.06
        rot = _rotation_matrix_xyz(pitch, yaw, 0.0)

        all_verts = np.vstack([q[0] for q in quads])  # (4*N, 3)
        r_all = all_verts @ rot.T
        fov_d = 3.3
        z_cam = fov_d - r_all[:, 2]
        inv_z = 1.0 / np.maximum(0.4, z_cam)
        proj_scale = scale * 0.96 * fov_d
        sx = cx + r_all[:, 0] * inv_z * proj_scale
        sy = cy + r_all[:, 1] * inv_z * proj_scale

        n_quads = len(quads)
        r_quads = r_all.reshape((n_quads, 4, 3))
        sx_q = sx.reshape((n_quads, 4))
        sy_q = sy.reshape((n_quads, 4))

        centers_z = np.mean(r_quads[:, :, 2], axis=1)
        order = np.argsort(centers_z)  # Back-to-front painter's algorithm

        light_dir = np.array([0.40, -0.45, 0.80], dtype=np.float32)
        light_dir /= np.linalg.norm(light_dir)

        for q_idx in order:
            x0, y0 = float(sx_q[q_idx, 0]), float(sy_q[q_idx, 0])
            x1, y1 = float(sx_q[q_idx, 1]), float(sy_q[q_idx, 1])
            x2, y2 = float(sx_q[q_idx, 2]), float(sy_q[q_idx, 2])
            x3, y3 = float(sx_q[q_idx, 3]), float(sy_q[q_idx, 3])
            signed_area = (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)
            if signed_area <= 0.0:
                continue
            qv = r_quads[q_idx]
            fn = np.cross(qv[1] - qv[0], qv[2] - qv[0])
            n_len = float(np.linalg.norm(fn))
            if n_len > 1e-6:
                fn = fn / n_len
            ndotl = max(0.0, float(np.dot(fn, light_dir)))
            shade = 0.58 + 0.50 * ndotl
            base_c = quads[q_idx][1]
            rc = min(255, int(base_c.red() * shade))
            gc = min(255, int(base_c.green() * shade))
            bc = min(255, int(base_c.blue() * shade))
            fill_c = QColor(rc, gc, bc)

            poly = QPolygonF([QPointF(x0, y0), QPointF(x1, y1), QPointF(x2, y2), QPointF(x3, y3)])
            painter.setBrush(fill_c)
            painter.setPen(QPen(fill_c, 0.55))  # Seal sub-pixel seams between adjacent voxel tiles
            painter.drawPolygon(poly)

        deg_yaw = int(round((yaw * 180.0 / math.pi) % 360))
        badge = f"3D Voxel Block ({deg_yaw} deg - Drag to Spin 360) | {hw_tier.replace('_', ' ').upper()}"
        self._draw_hw_status_pill(painter, cx, cy + scale * 1.16, badge, hw_reason)
        painter.restore()

    def _draw_hw_status_pill(self, painter: QPainter, cx: float, y_top: float, text: str, tooltip_reason: str = "") -> None:
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            return
        painter.save()
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(text) + 18
        th = fm.height() + 6
        rect = QRectF(cx - tw * 0.5, min(float(self.height()) - th - 58.0, y_top), tw, th)
        painter.setBrush(QColor(11, 17, 26, 210))
        painter.setPen(QPen(QColor(56, 189, 248, 125), 1.0))
        painter.drawRoundedRect(rect, 7.0, 7.0)
        painter.setPen(QColor("#bae6fd"))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        painter.restore()

    def _paint_cartoon_character(
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
        """Master dispatcher for 3D Studio Pixar, Lifelike Talking Portrait, 3D Brick Movie Minifig, UT GOTY 360° 3D Mesh, and 2D Fallback."""
        cfg = self._cartoon_cfg or DEFAULT_CARTOON_AVATAR_CONFIG
        eng = str(cfg.get("engine_mode") or "studio_3d").lower()
        hw_tier, hw_reason = self._resolve_effective_hw_tier()

        if eng == "ut_3d_mesh" and hw_tier != "2d_fallback":
            self._paint_ut_goty_3d_mesh(painter, cx, cy, scale, c_core, c_pri, c_sec, energy, mic_e, eff_state, bands, hw_tier, hw_reason)
            return

        if eng in ("studio_3d", "lifelike_portrait", "voxel_3d"):
            if self._paint_portrait_avatar(painter, cx, cy, scale, c_core, c_pri, c_sec, energy, mic_e, eff_state, bands, hw_tier, hw_reason):
                return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        t = self._phase
        cfg = self._cartoon_cfg or DEFAULT_CARTOON_AVATAR_CONFIG
        gender = str(cfg.get("gender") or "female").lower()
        skin_key = str(cfg.get("skin_tone") or "warm_light").lower()
        hair_style = str(cfg.get("hair_style") or "cozy_bun").lower()
        hair_col_key = str(cfg.get("hair_color") or "chestnut").lower()
        eye_col_key = str(cfg.get("eye_color") or "hazel").lower()
        outfit_key = str(cfg.get("outfit_color") or "cream").lower()
        has_glasses = bool(cfg.get("glasses", False))
        facial_hair = str(cfg.get("facial_hair") or "none").lower()

        # ── Smart gender presets (display-time enforcement) ────────────────
        # A masculine head must never inherit a feminine top-bun, long flowing
        # hair, or a soft cream sweater — and a feminine head must never carry a
        # beard. Applied per-frame so stale saved configs self-heal without
        # forcing the user to manually re-pick every combo in the dialog.
        if gender == "male":
            if hair_style in {"cozy_bun", "long_wavy", "curly"}:
                hair_style = "short_crop"
            if outfit_key == "cream":
                outfit_key = "navy_hoodie"
        else:
            if facial_hair and facial_hair != "none":
                facial_hair = "none"

        _, skin_hex, skin_shadow_hex, blush_hex = CARTOON_SKIN_TONES.get(skin_key, CARTOON_SKIN_TONES["warm_light"])
        _, hair_hex, hair_hi_hex = CARTOON_HAIR_COLORS.get(hair_col_key, CARTOON_HAIR_COLORS["chestnut"])
        _, eye_hex = CARTOON_EYE_COLORS.get(eye_col_key, CARTOON_EYE_COLORS["hazel"])
        _, outfit_hex, outfit_sh_hex = CARTOON_OUTFIT_COLORS.get(outfit_key, CARTOON_OUTFIT_COLORS["cream"])

        c_skin = QColor(skin_hex)
        c_skin_sh = QColor(skin_shadow_hex)
        c_blush = QColor(blush_hex)
        c_blush.setAlpha(95)
        c_hair = QColor(hair_hex)
        c_hair_hi = QColor(hair_hi_hex)
        c_eye = QColor(eye_hex)
        c_outfit = QColor(outfit_hex)
        c_outfit_sh = QColor(outfit_sh_hex)

        # 1. Cozy Dark Studio Backdrop + Audio-Reactive Neon Aura & Fairybread Toast Sign
        aura_r = scale * (1.35 + 0.16 * energy + 0.06 * mic_e)
        bg_grad = QRadialGradient(QPointF(cx, cy - scale * 0.08), aura_r)
        if eff_state == "speaking":
            aura_c = QColor(c_pri.red(), c_pri.green(), c_pri.blue(), int(min(135, 55 + energy * 110)))
        elif eff_state == "thinking":
            aura_c = QColor(245, 158, 11, 85)
        elif eff_state == "listening":
            aura_c = QColor(34, 197, 94, int(55 + mic_e * 80))
        else:
            aura_c = QColor(99, 102, 241, 45)
        bg_grad.setColorAt(0.0, aura_c)
        bg_grad.setColorAt(0.58, QColor(28, 25, 48, 70))
        bg_grad.setColorAt(1.0, QColor(8, 10, 18, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg_grad)
        painter.drawEllipse(QPointF(cx, cy - scale * 0.08), aura_r, aura_r)

        # Glowing neon toast sign in upper-left background (like Mockup #3)
        sign_x = cx - scale * 0.92
        sign_y = cy - scale * 0.42
        sign_s = scale * 0.24
        painter.save()
        painter.translate(sign_x, sign_y)
        painter.rotate(-10.0)
        neon_glow = QColor(251, 191, 36, int(150 + 70 * math.sin(t * 2.0)))
        painter.setPen(QPen(neon_glow, max(2.0, scale * 0.025)))
        painter.setBrush(QColor(24, 20, 32, 180))
        painter.drawRoundedRect(QRectF(-sign_s * 0.5, -sign_s * 0.5, sign_s, sign_s * 0.95), sign_s * 0.2, sign_s * 0.2)
        sprinkle_cols = ("#38bdf8", "#f43f5e", "#4ade80", "#c084fc", "#facc15")
        for sp_i, sp_hex in enumerate(sprinkle_cols):
            ang = sp_i * 1.25
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(sp_hex))
            painter.drawEllipse(QPointF(math.cos(ang) * sign_s * 0.2, math.sin(ang) * sign_s * 0.2), sign_s * 0.055, sign_s * 0.055)
        painter.restore()

        # Subtle organic breathing & head motion
        breath_y = math.sin(t * 1.65) * (scale * 0.018)
        talk_bob = (math.sin(t * 7.5) * energy * scale * 0.022) if eff_state == "speaking" else 0.0
        think_tilt = (math.sin(t * 1.9) * 3.2) if eff_state == "thinking" else (math.sin(t * 0.9) * 1.1)

        head_cx = cx
        head_cy = cy - scale * 0.14 + breath_y + talk_bob
        head_rx = scale * (0.41 if gender == "male" else 0.39)
        head_ry = scale * (0.47 if gender == "male" else 0.46)

        # 2. Back Hair Volume (drawn behind neck & shoulders)
        painter.setPen(QPen(c_hair.darker(135), max(1.2, scale * 0.014)))
        painter.setBrush(c_hair)
        if hair_style == "long_wavy":
            back_hair = QPainterPath()
            back_hair.moveTo(head_cx - head_rx * 1.12, head_cy - head_ry * 0.2)
            back_hair.cubicTo(
                head_cx - head_rx * 1.38, head_cy + head_ry * 0.65,
                head_cx - head_rx * 1.22, head_cy + head_ry * 1.55,
                head_cx - head_rx * 0.72, head_cy + head_ry * 1.68,
            )
            back_hair.lineTo(head_cx + head_rx * 0.72, head_cy + head_ry * 1.68)
            back_hair.cubicTo(
                head_cx + head_rx * 1.22, head_cy + head_ry * 1.55,
                head_cx + head_rx * 1.38, head_cy + head_ry * 0.65,
                head_cx + head_rx * 1.12, head_cy - head_ry * 0.2,
            )
            back_hair.closeSubpath()
            painter.drawPath(back_hair)
        elif hair_style == "curly":
            for c_ang in np.linspace(-0.85 * math.pi, 0.15 * math.pi, 11):
                 puffs_x = head_cx + math.cos(c_ang) * head_rx * 1.14
                 puffs_y = head_cy + math.sin(c_ang) * head_ry * 1.06
                 painter.drawEllipse(QPointF(puffs_x, puffs_y), head_rx * 0.36, head_rx * 0.36)
        elif hair_style == "cozy_bun":
            bun_y = head_cy - head_ry * 1.02
            painter.drawEllipse(QPointF(head_cx, bun_y), head_rx * 0.46, head_ry * 0.34)
            painter.setBrush(c_hair_hi)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(head_cx - head_rx * 0.1, bun_y - head_ry * 0.08), head_rx * 0.22, head_ry * 0.14)

        # 3. Shoulders, Torso & Cozy Knit Sweater / Jacket
        sh_w = scale * (0.94 if gender == "male" else 0.82)
        sh_top = head_cy + head_ry * 0.86
        sh_bot = cy + scale * 1.08
        torso_path = QPainterPath()
        torso_path.moveTo(cx - sh_w, sh_bot)
        torso_path.cubicTo(
            cx - sh_w * 0.96, sh_top + scale * 0.08,
            cx - sh_w * 0.48, sh_top,
            cx, sh_top,
        )
        torso_path.cubicTo(
            cx + sh_w * 0.48, sh_top,
            cx + sh_w * 0.96, sh_top + scale * 0.08,
            cx + sh_w, sh_bot,
        )
        torso_path.closeSubpath()
        out_grad = QLinearGradient(QPointF(cx, sh_top), QPointF(cx, sh_bot))
        out_grad.setColorAt(0.0, c_outfit)
        out_grad.setColorAt(1.0, c_outfit_sh)
        painter.setPen(QPen(c_outfit_sh.darker(130), max(1.4, scale * 0.015)))
        painter.setBrush(out_grad)
        painter.drawPath(torso_path)

        # Subtle sweater rib lines
        painter.setPen(QPen(QColor(c_outfit_sh.red(), c_outfit_sh.green(), c_outfit_sh.blue(), 115), max(1.0, scale * 0.01)))
        for rib_x in (-0.48, -0.24, 0.0, 0.24, 0.48):
            rx_p = cx + sh_w * rib_x
            painter.drawLine(QPointF(rx_p, sh_top + scale * 0.16), QPointF(rx_p, sh_bot - scale * 0.05))

        # Neck & Chin cast shadow
        neck_w = head_rx * (0.44 if gender == "male" else 0.36)
        neck_rect = QRectF(cx - neck_w, head_cy + head_ry * 0.62, neck_w * 2.0, head_ry * 0.44)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(c_skin_sh)
        painter.drawRoundedRect(neck_rect, neck_w * 0.4, neck_w * 0.4)

        # Collar crew-neck curve
        collar_path = QPainterPath()
        collar_path.moveTo(cx - neck_w * 1.35, sh_top + scale * 0.02)
        collar_path.quadTo(cx, sh_top + scale * 0.22, cx + neck_w * 1.35, sh_top + scale * 0.02)
        painter.setPen(QPen(c_outfit.lighter(112), max(3.0, scale * 0.045), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(collar_path)

        # 4. Head & Ears (with gentle tilt transform)
        painter.save()
        painter.translate(head_cx, head_cy)
        painter.rotate(think_tilt)

        # Ears
        ear_w = head_rx * 0.22
        ear_h = head_ry * 0.28
        painter.setPen(QPen(c_skin_sh, max(1.1, scale * 0.012)))
        painter.setBrush(c_skin)
        painter.drawEllipse(QPointF(-head_rx * 0.96, head_ry * 0.04), ear_w, ear_h)
        painter.drawEllipse(QPointF(head_rx * 0.96, head_ry * 0.04), ear_w, ear_h)
        if gender == "female":
            # Gold hoop earrings (like Mockup #3)
            painter.setPen(QPen(QColor("#fbbf24"), max(1.6, scale * 0.018)))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(-head_rx * 1.0, head_ry * 0.26), ear_w * 0.45, ear_w * 0.55)
            painter.drawEllipse(QPointF(head_rx * 1.0, head_ry * 0.26), ear_w * 0.45, ear_w * 0.55)

        # 3D parallax head motion — facial features drift slightly for a subtle Pixar "look at you" vibe
        yaw_x = math.sin(t * 1.1) * scale * 0.032
        pitch_y = math.cos(t * 1.4) * scale * 0.018

        # Face contour (radial 3D key-light from upper-left)
        face_grad = QRadialGradient(QPointF(-head_rx * 0.22 + yaw_x * 0.7, -head_ry * 0.22 + pitch_y * 0.7), head_ry * 1.35)
        face_grad.setColorAt(0.0, c_skin.lighter(108))
        face_grad.setColorAt(0.72, c_skin)
        face_grad.setColorAt(1.0, c_skin_sh)
        painter.setPen(QPen(c_skin_sh.darker(118), max(1.3, scale * 0.014)))
        painter.setBrush(face_grad)
        if gender == "male":
            # Sculpted angular Pixar-style masculine jawline (cheekbones -> mandible -> squared chin)
            jaw = QPainterPath()
            jaw.moveTo(-head_rx * 0.96, -head_ry * 0.34)
            jaw.cubicTo(-head_rx * 1.02, -head_ry * 0.06, -head_rx * 0.94, head_ry * 0.24, -head_rx * 0.78, head_ry * 0.46)
            jaw.lineTo(-head_rx * 0.26, head_ry * 0.96)
            jaw.quadTo(0.0, head_ry * 1.02, head_rx * 0.26, head_ry * 0.96)
            jaw.lineTo(head_rx * 0.78, head_ry * 0.46)
            jaw.cubicTo(head_rx * 0.94, head_ry * 0.24, head_rx * 1.02, -head_ry * 0.06, head_rx * 0.96, -head_ry * 0.34)
            jaw.cubicTo(head_rx * 0.90, -head_ry * 0.74, head_rx * 0.50, -head_ry * 0.98, 0.0, -head_ry * 0.98)
            jaw.cubicTo(-head_rx * 0.50, -head_ry * 0.98, -head_rx * 0.90, -head_ry * 0.74, -head_rx * 0.96, -head_ry * 0.34)
            jaw.closeSubpath()
            painter.drawPath(jaw)
            # Cool 3D rim-light tracing the mandible edge for extra chisel
            rim = QPainterPath()
            rim.moveTo(-head_rx * 0.78, head_ry * 0.46)
            rim.lineTo(-head_rx * 0.26, head_ry * 0.96)
            rim.quadTo(0.0, head_ry * 1.02, head_rx * 0.26, head_ry * 0.96)
            rim.lineTo(head_rx * 0.78, head_ry * 0.46)
            painter.setPen(QPen(QColor(255, 236, 214, 120), max(1.4, scale * 0.016), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(rim)
            # Directional 3D cheekbone contour (soft angled sculpt rather than dark under-eye circles)
            cheek_shadow = QColor(c_skin_sh.darker(112))
            cheek_shadow.setAlpha(42)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(cheek_shadow)
            painter.drawEllipse(QPointF(-head_rx * 0.72 + yaw_x, head_ry * 0.18 + pitch_y), head_rx * 0.15, head_ry * 0.07)
            painter.drawEllipse(QPointF(head_rx * 0.72 + yaw_x, head_ry * 0.18 + pitch_y), head_rx * 0.15, head_ry * 0.07)
            # Chin key-light spec highlight
            painter.setBrush(QColor(255, 255, 255, 55))
            painter.drawEllipse(QPointF(yaw_x, head_ry * 0.92 + pitch_y), head_rx * 0.10, head_ry * 0.035)
        else:
            # Sculpted Pixar heart/oval feminine face contour (graceful cheekbones tapering to a delicate chin)
            fem_face = QPainterPath()
            fem_face.moveTo(0.0, -head_ry * 0.98)
            fem_face.cubicTo(head_rx * 0.56, -head_ry * 0.98, head_rx * 0.95, -head_ry * 0.64, head_rx * 0.92, -head_ry * 0.10)
            fem_face.cubicTo(head_rx * 0.90, head_ry * 0.36, head_rx * 0.54, head_ry * 0.80, head_rx * 0.16, head_ry * 0.95)
            fem_face.quadTo(0.0, head_ry * 1.00, -head_rx * 0.16, head_ry * 0.95)
            fem_face.cubicTo(-head_rx * 0.54, head_ry * 0.80, -head_rx * 0.90, head_ry * 0.36, -head_rx * 0.92, -head_ry * 0.10)
            fem_face.cubicTo(-head_rx * 0.95, -head_ry * 0.64, -head_rx * 0.56, -head_ry * 0.98, 0.0, -head_ry * 0.98)
            fem_face.closeSubpath()
            painter.drawPath(fem_face)
            # Soft warm rim-light hugging the feminine jawline edge
            fem_rim = QPainterPath()
            fem_rim.moveTo(-head_rx * 0.64, head_ry * 0.56)
            fem_rim.cubicTo(-head_rx * 0.44, head_ry * 0.80, -head_rx * 0.22, head_ry * 0.94, 0.0, head_ry * 0.97)
            fem_rim.cubicTo(head_rx * 0.22, head_ry * 0.94, head_rx * 0.44, head_ry * 0.80, head_rx * 0.64, head_ry * 0.56)
            painter.setPen(QPen(QColor(255, 240, 226, 95), max(1.2, scale * 0.014), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(fem_rim)

        # Soft cheek blush — female only now (male uses the directional 3D cheekbone shading above)
        if gender == "female":
            blush_col = QColor(c_blush)
            blush_col.setAlpha(150)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(blush_col)
            painter.drawEllipse(QPointF(-head_rx * 0.52 + yaw_x, head_ry * 0.16 + pitch_y), head_rx * 0.22, head_ry * 0.11)
            painter.drawEllipse(QPointF(head_rx * 0.52 + yaw_x, head_ry * 0.16 + pitch_y), head_rx * 0.22, head_ry * 0.11)

        # Optional Facial Hair (Stubble / Beard) — 3D sculpted beard & mustache with inner mouth cutout
        if facial_hair in {"stubble", "beard"}:
            outer_beard = QPainterPath()
            outer_beard.moveTo(-head_rx * 0.90 + yaw_x * 0.4, head_ry * 0.04 + pitch_y * 0.4)
            outer_beard.cubicTo(
                -head_rx * 0.92 + yaw_x * 0.5, head_ry * 0.36 + pitch_y * 0.5,
                -head_rx * 0.80 + yaw_x * 0.6, head_ry * 0.54 + pitch_y * 0.6,
                -head_rx * 0.28 + yaw_x * 0.7, head_ry * 0.99 + pitch_y * 0.7,
            )
            outer_beard.quadTo(yaw_x * 0.7, head_ry * 1.06 + pitch_y * 0.7, head_rx * 0.28 + yaw_x * 0.7, head_ry * 0.99 + pitch_y * 0.7)
            outer_beard.cubicTo(
                head_rx * 0.80 + yaw_x * 0.6, head_ry * 0.54 + pitch_y * 0.6,
                head_rx * 0.92 + yaw_x * 0.5, head_ry * 0.36 + pitch_y * 0.5,
                head_rx * 0.90 + yaw_x * 0.4, head_ry * 0.04 + pitch_y * 0.4,
            )
            outer_beard.lineTo(head_rx * 0.78 + yaw_x * 0.5, head_ry * 0.04 + pitch_y * 0.4)
            outer_beard.cubicTo(
                head_rx * 0.72 + yaw_x * 0.7, head_ry * 0.34 + pitch_y * 0.6,
                head_rx * 0.44 + yaw_x * 0.9, head_ry * 0.27 + pitch_y * 0.8,
                head_rx * 0.28 + yaw_x, head_ry * 0.29 + pitch_y,
            )
            outer_beard.quadTo(yaw_x, head_ry * 0.22 + pitch_y, -head_rx * 0.28 + yaw_x, head_ry * 0.29 + pitch_y)
            outer_beard.cubicTo(
                -head_rx * 0.44 + yaw_x * 0.9, head_ry * 0.27 + pitch_y * 0.8,
                -head_rx * 0.72 + yaw_x * 0.7, head_ry * 0.34 + pitch_y * 0.6,
                -head_rx * 0.78 + yaw_x * 0.5, head_ry * 0.04 + pitch_y * 0.4,
            )
            outer_beard.closeSubpath()

            mouth_cutout = QPainterPath()
            mouth_cutout.addRoundedRect(
                QRectF(-head_rx * 0.35 + yaw_x, head_ry * 0.35 + pitch_y, head_rx * 0.70, head_ry * 0.24),
                head_rx * 0.18,
                head_ry * 0.12,
            )
            sculpted_beard = outer_beard.subtracted(mouth_cutout)

            b_alpha = 115 if facial_hair == "stubble" else 235
            beard_grad = QLinearGradient(QPointF(yaw_x, head_ry * 0.20 + pitch_y), QPointF(yaw_x, head_ry * 1.04 + pitch_y))
            c_b_top = QColor(c_hair.darker(112))
            c_b_top.setAlpha(b_alpha)
            c_b_bot = QColor(c_hair.darker(148))
            c_b_bot.setAlpha(b_alpha)
            beard_grad.setColorAt(0.0, c_b_top)
            beard_grad.setColorAt(1.0, c_b_bot)
            painter.setPen(QPen(QColor(c_hair.darker(160).red(), c_hair.darker(160).green(), c_hair.darker(160).blue(), min(220, b_alpha)), max(1.1, scale * 0.012)))
            painter.setBrush(beard_grad)
            painter.drawPath(sculpted_beard)

            # Soul patch under lower lip + subtle hair grain texture
            soul_p = QPainterPath()
            soul_p.addRoundedRect(
                QRectF(-head_rx * 0.08 + yaw_x, head_ry * 0.54 + pitch_y, head_rx * 0.16, head_ry * 0.16),
                head_rx * 0.06,
                head_ry * 0.06,
            )
            painter.drawPath(soul_p)

        # 5. Expressive Eyes, Blinking & Eyebrows (with 3D parallax offset)
        blink_cycle = (t * 0.85) % 3.4
        blink_open = 1.0
        if blink_cycle < 0.14:
            blink_open = max(0.06, abs(blink_cycle - 0.07) / 0.07)

        eye_dx = head_rx * (0.40 if gender == "male" else 0.42)
        eye_y = -head_ry * 0.06 + pitch_y * 0.85
        eye_rx = head_rx * (0.195 if gender == "male" else 0.21)
        eye_ry = head_ry * (0.125 if gender == "male" else 0.155) * blink_open

        gaze_x = (math.sin(t * 0.7) * eye_rx * 0.18) if eff_state != "thinking" else (eye_rx * 0.24)
        gaze_y = (-eye_ry * 0.22) if eff_state == "thinking" else 0.0

        for side in (-1.0, 1.0):
            ex = side * eye_dx + yaw_x * 0.9
            if blink_open <= 0.18:
                lash_p = QPainterPath()
                lash_p.moveTo(ex - eye_rx, eye_y)
                lash_p.quadTo(ex, eye_y + head_ry * 0.05, ex + eye_rx, eye_y)
                painter.setPen(QPen(c_hair.darker(150), max(2.0, scale * 0.022), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(lash_p)
            else:
                # Subtle 3D eye socket shading above eyelid
                sock_col = QColor(c_skin_sh.darker(118))
                sock_col.setAlpha(75)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(sock_col)
                painter.drawEllipse(QPointF(ex, eye_y - eye_ry * 0.18), eye_rx * 1.12, eye_ry * 1.16)

                # Sclera with 3D radial shading
                sclera_grad = QRadialGradient(QPointF(ex - eye_rx * 0.2, eye_y - eye_ry * 0.2), eye_rx * 1.2)
                sclera_grad.setColorAt(0.0, QColor("#ffffff"))
                sclera_grad.setColorAt(0.8, QColor("#f1f5f9"))
                sclera_grad.setColorAt(1.0, QColor("#cbd5e1"))
                painter.setPen(QPen(c_skin_sh.darker(135), max(1.1, scale * 0.012)))
                painter.setBrush(sclera_grad)
                if gender == "male":
                    painter.drawRoundedRect(QRectF(ex - eye_rx, eye_y - eye_ry, eye_rx * 2.0, eye_ry * 2.0), eye_rx * 0.72, eye_ry * 0.78)
                else:
                    painter.drawEllipse(QPointF(ex, eye_y), eye_rx, eye_ry)

                # Iris with 3D depth ring
                iris_r = min(eye_rx * 0.68, eye_ry * 0.88)
                ix = ex + gaze_x
                iy = eye_y + gaze_y
                iris_grad = QRadialGradient(QPointF(ix, iy + iris_r * 0.25), iris_r)
                iris_grad.setColorAt(0.0, c_eye.lighter(135))
                iris_grad.setColorAt(0.65, c_eye)
                iris_grad.setColorAt(1.0, c_eye.darker(145))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(iris_grad)
                painter.drawEllipse(QPointF(ix, iy), iris_r, iris_r)

                # Pupil
                pupil_r = iris_r * 0.50
                painter.setBrush(QColor("#0f172a"))
                painter.drawEllipse(QPointF(ix, iy), pupil_r, pupil_r)

                # Dual Catchlights (Pixar/Disney eye sparkle)
                painter.setBrush(QColor(255, 255, 255, 242))
                painter.drawEllipse(QPointF(ix - iris_r * 0.32, iy - iris_r * 0.32), iris_r * 0.26, iris_r * 0.26)
                painter.drawEllipse(QPointF(ix + iris_r * 0.28, iy + iris_r * 0.24), iris_r * 0.13, iris_r * 0.13)

                # Upper Eyelid / Eyelash Arch (feminine wing on female, clean structured lid crease on male)
                lash_arch = QPainterPath()
                if gender == "female":
                    lash_arch.moveTo(ex - eye_rx * 1.05, eye_y - eye_ry * 0.12)
                    lash_arch.quadTo(ex, eye_y - eye_ry * 1.28, ex + eye_rx * 1.12, eye_y - eye_ry * 0.14)
                    painter.setPen(QPen(QColor("#1e1b24"), max(2.4, scale * 0.028), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                else:
                    lash_arch.moveTo(ex - eye_rx * 0.98, eye_y - eye_ry * 0.45)
                    lash_arch.quadTo(ex, eye_y - eye_ry * 1.08, ex + eye_rx * 0.98, eye_y - eye_ry * 0.45)
                    painter.setPen(QPen(c_skin_sh.darker(145), max(1.7, scale * 0.019), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(lash_arch)

            # Expressive Eyebrows (thick straight/angled brow ridge on male; sculpted arch on female)
            brow_lift = (
                head_ry * 0.045 * min(1.0, energy * 1.5)
                if eff_state == "speaking"
                else (head_ry * 0.05 if (eff_state == "thinking" and side > 0) else 0.0)
            )
            brow_y = eye_y - head_ry * (0.20 if gender == "male" else 0.23) - brow_lift
            brow_p = QPainterPath()
            if gender == "male":
                brow_p.moveTo(ex - eye_rx * 1.12, brow_y + side * (head_ry * 0.015))
                brow_p.lineTo(ex + side * eye_rx * 0.35, brow_y - head_ry * 0.035)
                brow_p.lineTo(ex + eye_rx * 1.10, brow_y + head_ry * 0.01)
                painter.setPen(QPen(c_hair.darker(125), max(3.4, scale * 0.038), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            else:
                brow_p.moveTo(ex - eye_rx * 1.05, brow_y + side * (-head_ry * 0.02))
                brow_p.quadTo(ex, brow_y - head_ry * 0.09, ex + eye_rx * 1.05, brow_y + head_ry * 0.01)
                painter.setPen(QPen(c_hair.darker(120), max(2.4, scale * 0.028), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(brow_p)

        # 3D Sculpted Nose Bridge, Tip Highlight & Cast Shadow
        nx = yaw_x * 1.15
        ny = head_ry * 0.16 + pitch_y * 0.95
        # Soft cast shadow beneath nose tip
        painter.setPen(Qt.PenStyle.NoPen)
        nose_sh_col = QColor(c_skin_sh.darker(125))
        nose_sh_col.setAlpha(135)
        painter.setBrush(nose_sh_col)
        painter.drawEllipse(QPointF(nx, ny + head_ry * 0.045), head_rx * (0.115 if gender == "male" else 0.095), head_ry * 0.042)
        # Side bridge contour
        nose_p = QPainterPath()
        nose_p.moveTo(nx - head_rx * 0.045, -head_ry * 0.05 + pitch_y * 0.8)
        nose_p.cubicTo(nx - head_rx * 0.09, ny - head_ry * 0.03, nx - head_rx * 0.11, ny + head_ry * 0.03, nx, ny + head_ry * 0.04)
        nose_p.lineTo(nx + head_rx * 0.075, ny + head_ry * 0.02)
        painter.setPen(QPen(c_skin_sh.darker(125), max(1.4, scale * 0.016), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(nose_p)
        # 3D nose bridge & tip specular highlight
        painter.setPen(QPen(QColor(255, 255, 255, 95), max(1.6, scale * 0.018), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(nx + head_rx * 0.01, -head_ry * 0.03 + pitch_y * 0.8), QPointF(nx + head_rx * 0.015, ny - head_ry * 0.01))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 115))
        painter.drawEllipse(QPointF(nx + head_rx * 0.015, ny), head_rx * 0.032, head_ry * 0.024)

        # Optional Glasses
        if has_glasses:
            painter.setPen(QPen(QColor("#e2e8f0"), max(1.8, scale * 0.02)))
            painter.setBrush(QColor(56, 189, 248, 28))
            g_r = eye_rx * 1.32
            painter.drawRoundedRect(QRectF(yaw_x * 0.9 - eye_dx - g_r, eye_y - g_r * 0.82, g_r * 2.0, g_r * 1.64), g_r * 0.4, g_r * 0.4)
            painter.drawRoundedRect(QRectF(yaw_x * 0.9 + eye_dx - g_r, eye_y - g_r * 0.82, g_r * 2.0, g_r * 1.64), g_r * 0.4, g_r * 0.4)
            painter.drawLine(QPointF(yaw_x * 0.9 - eye_dx + g_r, eye_y), QPointF(yaw_x * 0.9 + eye_dx - g_r, eye_y))

        # 6. Audio-Reactive Lip-Sync Viseme Mouth (5 smooth viseme shapes from FFT bands)
        bass_e = float(np.mean(bands[:4])) if bands.size >= 4 else energy
        mid_e = float(np.mean(bands[4:10])) if bands.size >= 10 else energy
        high_e = float(np.mean(bands[10:])) if bands.size >= 12 else energy

        mouth_y = head_ry * 0.44 + pitch_y * 0.95
        if eff_state == "speaking" and (energy > 0.025 or bass_e > 0.03):
            open_amt = min(1.0, energy * 1.45 + bass_e * 0.55)
            # Round "Oo" vowel when bass dominates, wide "Ah/Eh" when mid/high dominate
            roundness = max(0.55, min(1.15, 0.72 + (mid_e - bass_e * 0.65) * 0.65))
            m_w = head_rx * (0.24 + 0.16 * roundness * min(1.0, open_amt + 0.35))
            m_h = head_ry * (0.04 + 0.22 * open_amt)

            mouth_rect = QRectF(yaw_x - m_w, mouth_y - m_h * 0.35, m_w * 2.0, m_h * 1.7)
            mouth_path = QPainterPath()
            mouth_path.addRoundedRect(mouth_rect, m_w * 0.75, m_h * 0.85)

            painter.save()
            painter.setPen(QPen(c_skin_sh.darker(145), max(1.4, scale * 0.016)))
            painter.setBrush(QColor("#4c1d24"))
            painter.drawPath(mouth_path)

            # Clip teeth & tongue inside open mouth
            painter.setClipPath(mouth_path)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#f8fafc"))
            painter.drawRect(QRectF(yaw_x - m_w, mouth_y - m_h * 0.35, m_w * 2.0, m_h * 0.52))
            painter.setBrush(QColor("#e11d48"))
            painter.drawEllipse(QPointF(yaw_x, mouth_y + m_h * 0.95), m_w * 0.72, m_h * 0.65)
            painter.restore()
        else:
            # Warm friendly smile when idle or listening (3D shaded lips on female, structured smile on male)
            smile_w = head_rx * (0.30 if eff_state == "listening" else 0.26)
            if gender == "female":
                lip_p = QPainterPath()
                lip_p.moveTo(yaw_x - smile_w, mouth_y - head_ry * 0.01)
                lip_p.quadTo(yaw_x, mouth_y - head_ry * 0.06, yaw_x + smile_w, mouth_y - head_ry * 0.01)
                lip_p.quadTo(yaw_x, mouth_y + head_ry * 0.15, yaw_x - smile_w, mouth_y - head_ry * 0.01)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(217, 114, 118, 175))
                painter.drawPath(lip_p)
            smile_p = QPainterPath()
            smile_p.moveTo(yaw_x - smile_w, mouth_y - head_ry * 0.01)
            smile_p.quadTo(yaw_x, mouth_y + head_ry * (0.09 if gender == "male" else 0.13), yaw_x + smile_w, mouth_y - head_ry * 0.01)
            painter.setPen(QPen(QColor("#7c3a32" if gender == "male" else "#9f4248"), max(2.2, scale * 0.024), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(smile_p)

        # 7. Front Hair & Bangs (with 3D temple sideburns & specular sheen on short_crop / side_part / spiky)
        painter.setPen(QPen(c_hair.darker(135), max(1.2, scale * 0.014)))
        hair_grad = QLinearGradient(QPointF(yaw_x * 0.4, -head_ry * 1.15), QPointF(yaw_x * 0.4, head_ry * 0.2))
        hair_grad.setColorAt(0.0, c_hair_hi)
        hair_grad.setColorAt(0.55, c_hair)
        hair_grad.setColorAt(1.0, c_hair.darker(122))
        painter.setBrush(hair_grad)

        crown_p = QPainterPath()
        if hair_style in {"cozy_bun", "long_wavy", "curly"}:
            # Swept parted bangs + soft side framing strands
            crown_p.moveTo(-head_rx * 1.02, -head_ry * 0.12)
            crown_p.cubicTo(-head_rx * 1.08, -head_ry * 0.95, -head_rx * 0.35, -head_ry * 1.18, 0.0, -head_ry * 1.12)
            crown_p.cubicTo(head_rx * 0.35, -head_ry * 1.18, head_rx * 1.08, -head_ry * 0.95, head_rx * 1.02, -head_ry * 0.12)
            crown_p.cubicTo(head_rx * 0.65, -head_ry * 0.45, head_rx * 0.20, -head_ry * 0.68, -head_rx * 0.08, -head_ry * 0.72)
            crown_p.cubicTo(-head_rx * 0.38, -head_ry * 0.64, -head_rx * 0.72, -head_ry * 0.42, -head_rx * 1.02, -head_ry * 0.12)
            painter.drawPath(crown_p)
            # Loose side framing wisps
            for side in (-1.0, 1.0):
                wisp = QPainterPath()
                wisp.moveTo(side * head_rx * 0.94, -head_ry * 0.32)
                wisp.cubicTo(
                    side * head_rx * 1.15, head_ry * 0.05,
                    side * head_rx * 1.06, head_ry * 0.48,
                    side * head_rx * 0.84, head_ry * 0.68,
                )
                wisp.cubicTo(
                    side * head_rx * 0.94, head_ry * 0.35,
                    side * head_rx * 0.96, 0.0,
                    side * head_rx * 0.85, -head_ry * 0.25,
                )
                painter.drawPath(wisp)
        elif hair_style == "spiky":
            crown_p.moveTo(-head_rx * 0.96, head_ry * 0.02)
            crown_p.lineTo(-head_rx * 1.02, -head_ry * 0.42)
            spikes = [(-0.78, -1.10), (-0.46, -0.88), (-0.20, -1.24), (0.08, -0.92), (0.36, -1.22), (0.64, -0.88), (0.90, -1.06)]
            for sx_f, sy_f in spikes:
                crown_p.lineTo(head_rx * sx_f, head_ry * sy_f)
            crown_p.lineTo(head_rx * 1.02, -head_ry * 0.42)
            crown_p.lineTo(head_rx * 0.96, head_ry * 0.02)
            crown_p.lineTo(head_rx * 0.86, -head_ry * 0.46)
            crown_p.quadTo(0.0, -head_ry * 0.72, -head_rx * 0.86, -head_ry * 0.46)
            crown_p.closeSubpath()
            painter.drawPath(crown_p)
        else:
            # 3D Sculpted Short Crop / Side Part with tapered temple sideburns & volume crown
            part_x = -head_rx * 0.42 if hair_style == "side_part" else -head_rx * 0.15
            crown_p.moveTo(-head_rx * 0.94, head_ry * 0.06)
            crown_p.cubicTo(-head_rx * 1.04, -head_ry * 0.35, -head_rx * 1.06, -head_ry * 0.92, -head_rx * 0.48, -head_ry * 1.12)
            crown_p.cubicTo(0.0, -head_ry * 1.24, head_rx * 0.65, -head_ry * 1.14, head_rx * 0.96, -head_ry * 0.75)
            crown_p.cubicTo(head_rx * 1.06, -head_ry * 0.45, head_rx * 1.02, -head_ry * 0.15, head_rx * 0.94, head_ry * 0.06)
            crown_p.lineTo(head_rx * 0.85, head_ry * 0.02)
            crown_p.lineTo(head_rx * 0.82, -head_ry * 0.54)
            crown_p.cubicTo(head_rx * 0.42, -head_ry * 0.76, part_x + head_rx * 0.25, -head_ry * 0.64, part_x, -head_ry * 0.78)
            crown_p.cubicTo(-head_rx * 0.62, -head_ry * 0.72, -head_rx * 0.80, -head_ry * 0.58, -head_rx * 0.82, -head_ry * 0.48)
            crown_p.lineTo(-head_rx * 0.85, head_ry * 0.02)
            crown_p.closeSubpath()
            painter.drawPath(crown_p)
            # 3D Specular Hair Sheen Highlight Ribbon
            sheen = QPainterPath()
            sheen.moveTo(-head_rx * 0.46, -head_ry * 0.92)
            sheen.quadTo(0.0, -head_ry * 1.08, head_rx * 0.48, -head_ry * 0.86)
            painter.setPen(QPen(QColor(c_hair_hi.lighter(125).red(), c_hair_hi.lighter(125).green(), c_hair_hi.lighter(125).blue(), 135), max(2.2, scale * 0.026), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(sheen)

        painter.restore()
        painter.restore()


class CartoonCharacterCustomizerDialog(QDialog):
    """3D & Lifelike Avatar Studio + Game-Style Hardware System Check & Live FPS Benchmark."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        initial_config: dict[str, Any] | None = None,
        on_live_change: Any = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("🎨 3D & Lifelike Avatar Studio — System Check & Customizer")
        self.setModal(True)
        self.resize(560, 620)
        self._cfg = dict(DEFAULT_CARTOON_AVATAR_CONFIG)
        if isinstance(initial_config, dict):
            self._cfg.update(initial_config)
        self._on_live_change = on_live_change
        self._bench_running = False
        self._bench_start_ts = 0.0
        self._bench_frame_times: list[float] = []
        self._bench_last_ts = 0.0

        self.setStyleSheet(
            "QDialog { background: #0d121b; color: #f0f6fc; } "
            "QLabel { color: #e2e8f0; font-size: 12px; } "
            "QComboBox, QLineEdit, QSpinBox { background: #161f2e; color: #f0f6fc; border: 1px solid #2e3c52; border-radius: 6px; padding: 4px 8px; font-size: 12px; } "
            "QCheckBox { color: #e2e8f0; font-size: 12px; } "
            "QPushButton { background: #1e293b; color: #f0f6fc; border: 1px solid #334155; border-radius: 6px; padding: 5px 12px; font-weight: 700; font-size: 12px; } "
            "QPushButton:hover { background: #334155; border-color: #38bdf8; } "
            "QProgressBar { background: #111827; border: 1px solid #2e3c52; border-radius: 5px; text-align: center; color: #f0f6fc; font-weight: 700; height: 16px; } "
            "QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #06b6d4, stop:1 #6366f1); border-radius: 4px; }"
        )
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)

        hdr = QLabel(
            "<b>🎮 3D & Lifelike Avatar Studio</b> "
            "<span style='color:#38bdf8; font-size:11px;'>(Pixar 3D · Lifelike Human · UT GOTY 360° 3D Mesh · GPU Benchmark)</span>"
        )
        v.addWidget(hdr)

        # ── 1. Game-Style Hardware System Check & 3.5s Live GPU Benchmark Card ──
        hw_card = QFrame(self)
        hw_card.setStyleSheet(
            "QFrame { background: #121926; border: 1px solid #29384d; border-radius: 8px; }"
        )
        hw_lay = QVBoxLayout(hw_card)
        hw_lay.setContentsMargins(12, 9, 12, 9)
        hw_lay.setSpacing(6)

        hw_top = QHBoxLayout()
        self.hw_title_lbl = QLabel("<b>⚡ System Requirements & 3D GPU Auto-Detect</b>")
        hw_top.addWidget(self.hw_title_lbl, 1)
        self.bench_btn = QPushButton("🚀 Run 3.5s 3D Benchmark")
        self.bench_btn.setToolTip("Spins a live 3D test mesh for 3.5s (ignoring the first 1.2s shader warmup) to auto-score Full 3D vs Lite 3D vs 2D")
        self.bench_btn.setStyleSheet(
            "QPushButton { background: #0f293a; color: #38bdf8; border: 1px solid #0284c7; border-radius: 6px; padding: 4px 10px; font-weight: 700; } "
            "QPushButton:hover { background: #163e57; color: #ffffff; }"
        )
        self.bench_btn.clicked.connect(self.run_live_gpu_benchmark)
        hw_top.addWidget(self.bench_btn)
        hw_lay.addLayout(hw_top)

        self.hw_telemetry_lbl = QLabel()
        self.hw_telemetry_lbl.setWordWrap(True)
        self.hw_telemetry_lbl.setStyleSheet("color: #94a3b8; font-size: 11.5px; font-family: Consolas, monospace;")
        hw_lay.addWidget(self.hw_telemetry_lbl)

        self.bench_progress = QProgressBar()
        self.bench_progress.setRange(0, 100)
        self.bench_progress.setValue(0)
        self.bench_progress.hide()
        hw_lay.addWidget(self.bench_progress)

        hw_opts = QHBoxLayout()
        hw_opts.addWidget(QLabel("Graphics Tier Override:"))
        self.hw_tier_cb = QComboBox()
        self.hw_tier_cb.addItem("Auto-Detect (Use Benchmark / GPU)", "auto")
        self.hw_tier_cb.addItem("Force Full 3D (NVIDIA / Dedicated GPU)", "full_3d")
        self.hw_tier_cb.addItem("Force Lite 3D (UT GOTY Fast Mode)", "lite_3d")
        self.hw_tier_cb.addItem("Force 2D Fallback (Battery Saver)", "2d_fallback")
        self._select_data(self.hw_tier_cb, self._cfg.get("hw_tier", "auto"))
        hw_opts.addWidget(self.hw_tier_cb, 1)

        self.battery_guard_chk = QCheckBox("Sleep Heavy 3D on Laptop Battery")
        self.battery_guard_chk.setChecked(bool(self._cfg.get("sleep_3d_on_battery", True)))
        self.battery_guard_chk.setToolTip("Automatically drops from Full 3D to Lite 3D when your NVIDIA laptop is unplugged on battery")
        hw_opts.addWidget(self.battery_guard_chk)
        hw_lay.addLayout(hw_opts)
        v.addWidget(hw_card)

        # ── 2. Avatar Engine Mode & Built-in / Custom Character Form ──
        form = QFormLayout()
        form.setSpacing(8)

        self.engine_mode_cb = QComboBox()
        self.engine_mode_cb.addItem("✨ 3D Pixar / Studio Animated Character (Mockup #2 Quality)", "studio_3d")
        self.engine_mode_cb.addItem("📸 Lifelike Photorealistic Human Portrait (Live Blink & Lip-Sync)", "lifelike_portrait")
        self.engine_mode_cb.addItem("🧱 3D Brick Movie Minifig Character (Lego Movie Glossy ABS Style)", "voxel_3d")
        self.engine_mode_cb.addItem("🎮 Unreal Tournament GOTY 360° Rotatable 3D Mesh (Drag to Spin)", "ut_3d_mesh")
        self.engine_mode_cb.addItem("🎨 Classic 2D Vector Cartoon (Lightweight)", "vector_2d")
        self._select_data(self.engine_mode_cb, self._cfg.get("engine_mode", "studio_3d"))
        form.addRow("Avatar Engine Mode:", self.engine_mode_cb)

        self.preset_cb = QComboBox()
        for pid, pmeta in AVATAR_PORTRAIT_PRESETS.items():
            self.preset_cb.addItem(str(pmeta["label"]), pid)
        self.preset_cb.addItem("📁 Custom Portrait Photo / AI Generated Image…", "custom")
        self._select_data(self.preset_cb, self._cfg.get("preset_id", "pixar_3d_female"))
        form.addRow("Character Preset:", self.preset_cb)

        # Custom Portrait / 3D Model file row
        file_row = QHBoxLayout()
        self.custom_path_edit = QLineEdit(str(self._cfg.get("custom_portrait_path") or self._cfg.get("custom_model_path") or ""))
        self.custom_path_edit.setPlaceholderText("Optional: Browse a .png/.jpg photo OR a .obj 3D mesh file…")
        file_row.addWidget(self.custom_path_edit, 1)
        browse_img_btn = QPushButton("Browse Photo…")
        browse_img_btn.clicked.connect(self._browse_custom_portrait)
        file_row.addWidget(browse_img_btn)
        browse_mesh_btn = QPushButton("Load 3D .OBJ…")
        browse_mesh_btn.setToolTip("Load a 3D Wavefront .OBJ mesh file to rotate 360° in UT 3D Mesh mode")
        browse_mesh_btn.clicked.connect(self._browse_custom_mesh)
        file_row.addWidget(browse_mesh_btn)
        form.addRow("Custom File / Model:", file_row)

        self.gender_cb = QComboBox()
        self.gender_cb.addItem("Female Character", "female")
        self.gender_cb.addItem("Male Character", "male")
        self._select_data(self.gender_cb, self._cfg.get("gender", "female"))
        form.addRow("Gender / Rig:", self.gender_cb)

        # Lip-Sync Jaw Sensitivity + Debug Landmark Overlay
        jaw_row = QHBoxLayout()
        self.jaw_spin = QSpinBox()
        self.jaw_spin.setRange(50, 180)
        self.jaw_spin.setSuffix("%")
        self.jaw_spin.setValue(int(self._cfg.get("jaw_sensitivity", 100)))
        jaw_row.addWidget(self.jaw_spin)
        self.landmark_chk = QCheckBox("Show Eye & Jaw Landmark Calibration Boxes")
        self.landmark_chk.setChecked(bool(self._cfg.get("show_landmark_overlay", False)))
        jaw_row.addWidget(self.landmark_chk)
        self.comfy_chk = QCheckBox("ComfyUI LivePortrait Hook")
        self.comfy_chk.setChecked(bool(self._cfg.get("comfyui_live_bridge", False)))
        self.comfy_chk.setToolTip("When enabled on an NVIDIA GPU with ComfyUI running (127.0.0.1:8188), enables LivePortrait/Video synthesis bridge")
        jaw_row.addWidget(self.comfy_chk)
        jaw_row.addStretch(1)
        form.addRow("Lip-Sync & Calibration:", jaw_row)

        # Appearance customization for UT 3D Mesh & 2D Vector modes
        self.skin_cb = QComboBox()
        for k, (lbl, *_rest) in CARTOON_SKIN_TONES.items():
            self.skin_cb.addItem(lbl, k)
        self._select_data(self.skin_cb, self._cfg.get("skin_tone", "warm_light"))
        form.addRow("3D Mesh Skin Tone:", self.skin_cb)

        self.hair_style_cb = QComboBox()
        for k, lbl in CARTOON_HAIR_STYLES:
            self.hair_style_cb.addItem(lbl, k)
        self._select_data(self.hair_style_cb, self._cfg.get("hair_style", "cozy_bun"))
        form.addRow("Hair Style:", self.hair_style_cb)

        self.hair_col_cb = QComboBox()
        for k, (lbl, *_rest) in CARTOON_HAIR_COLORS.items():
            self.hair_col_cb.addItem(lbl, k)
        self._select_data(self.hair_col_cb, self._cfg.get("hair_color", "chestnut"))
        form.addRow("Hair & Beard Color:", self.hair_col_cb)

        self.eye_col_cb = QComboBox()
        for k, (lbl, *_rest) in CARTOON_EYE_COLORS.items():
            self.eye_col_cb.addItem(lbl, k)
        self._select_data(self.eye_col_cb, self._cfg.get("eye_color", "hazel"))
        form.addRow("Eye Color:", self.eye_col_cb)

        self.outfit_cb = QComboBox()
        for k, (lbl, *_rest) in CARTOON_OUTFIT_COLORS.items():
            self.outfit_cb.addItem(lbl, k)
        self._select_data(self.outfit_cb, self._cfg.get("outfit_color", "cream"))
        form.addRow("Outfit / Armor Tint:", self.outfit_cb)

        self.beard_cb = QComboBox()
        self.beard_cb.addItem("None", "none")
        self.beard_cb.addItem("Light Stubble", "stubble")
        self.beard_cb.addItem("Full Beard", "beard")
        self._select_data(self.beard_cb, self._cfg.get("facial_hair", "none"))
        form.addRow("Facial Hair:", self.beard_cb)

        self.glasses_chk = QCheckBox("Wear Glasses")
        self.glasses_chk.setChecked(bool(self._cfg.get("glasses", False)))
        form.addRow("Accessories:", self.glasses_chk)
        v.addLayout(form)

        self._bench_timer = QTimer(self)
        self._bench_timer.setInterval(12)
        self._bench_timer.timeout.connect(self._step_gpu_benchmark)
        self._bench_mesh = _build_ut_goty_3d_head_mesh("male")
        self._bench_img = QImage(380, 380, QImage.Format.Format_ARGB32_Premultiplied)
        self._saved_portrait_path = str(self._cfg.get("custom_portrait_path") or "").strip()
        self._saved_model_path = str(self._cfg.get("custom_model_path") or "").strip()

        self.engine_mode_cb.currentIndexChanged.connect(self._on_engine_mode_changed)
        self.preset_cb.currentIndexChanged.connect(self._on_preset_changed)
        self.gender_cb.currentIndexChanged.connect(self._on_gender_changed)
        for cb in (
            self.hw_tier_cb,
            self.engine_mode_cb,
            self.preset_cb,
            self.gender_cb,
            self.skin_cb,
            self.hair_style_cb,
            self.hair_col_cb,
            self.eye_col_cb,
            self.outfit_cb,
            self.beard_cb,
        ):
            cb.currentIndexChanged.connect(self._emit_live)
        for chk in (self.battery_guard_chk, self.landmark_chk, self.comfy_chk, self.glasses_chk):
            chk.toggled.connect(self._emit_live)
        self.jaw_spin.valueChanged.connect(self._emit_live)
        self.custom_path_edit.textChanged.connect(self._emit_live)

        self._refresh_hardware_telemetry_label()

        v.addStretch(1)
        btns = QHBoxLayout()
        btns.addStretch(1)
        done_btn = QPushButton("✓ Apply & Close")
        done_btn.setStyleSheet(
            "QPushButton { background: #6366f1; color: #ffffff; border: 1px solid #818cf8; border-radius: 7px; padding: 7px 18px; font-weight: 700; } "
            "QPushButton:hover { background: #4f46e5; }"
        )
        done_btn.clicked.connect(self.accept)
        btns.addWidget(done_btn)
        v.addLayout(btns)

    @staticmethod
    def _select_data(cb: QComboBox, val: Any) -> None:
        idx = cb.findData(str(val or "").lower())
        if idx >= 0:
            cb.setCurrentIndex(idx)

    def _refresh_hardware_telemetry_label(self) -> None:
        hw = detect_system_gpu_and_power(force_refresh=False)
        gpu_nm = hw.get("gpu_name", "Unknown GPU")
        vram = hw.get("vram_mb", 1024)
        drv = hw.get("driver_version", "N/A")
        hz = hw.get("refresh_hz", 60.0)
        pwr = f"Battery ({hw.get('battery_pct', 100)}%)" if hw.get("on_battery") else "AC Power (Plugged In)"
        chip_tag = "🟢 NVIDIA / Dedicated 3D GPU" if hw.get("is_dedicated") else ("🔴 Software Render" if hw.get("is_software") else "🟡 Integrated Graphics (UT Lite 3D Ready)")

        bench_tier = str(self._cfg.get("benchmarked_tier") or "").upper()
        bench_fps = float(self._cfg.get("benchmark_fps") or 0.0)
        bench_p95 = float(self._cfg.get("benchmark_p95_ms") or 0.0)
        bench_reason = str(self._cfg.get("benchmark_reason") or "Not benchmarked yet — click 'Run 3.5s 3D Benchmark' to test live frame rate.")
        if bench_tier and bench_fps > 0:
            score_line = f"Benchmark: <b>{bench_tier}</b> · Avg: <b>{bench_fps:.1f} FPS</b> · p95 Frame: <b>{bench_p95:.1f} ms</b><br><span style='color:#38bdf8;'>Decision: {bench_reason}</span>"
        else:
            score_line = f"<span style='color:#cbd5e1;'>Status: {bench_reason}</span>"

        self.hw_telemetry_lbl.setText(
            f"GPU: <b>{gpu_nm}</b> ({vram} MB VRAM · Driver {drv})<br>"
            f"Class: {chip_tag} · Display: {hz:.0f} Hz · Power: {pwr}<br>"
            f"{score_line}"
        )

    def run_live_gpu_benchmark(self) -> None:
        """Run the Council-designed 3.5-second live 3D spin benchmark (1.2s warmup discarded, 2.3s scored)."""
        if self._bench_running:
            return
        self._bench_running = True
        self._bench_start_ts = time.monotonic()
        self._bench_last_ts = self._bench_start_ts
        self._bench_frame_times = []
        self.bench_btn.setEnabled(False)
        self.bench_btn.setText("⏳ Benchmarking 3D Spin…")
        self.bench_progress.setValue(0)
        self.bench_progress.show()
        self._bench_timer.start()

    def _step_gpu_benchmark(self) -> None:
        # The QTimer outlives the dialog if the user closes it mid-run (Escape, window
        # close button, app quit). Touching deleted Qt widgets from the tick raises
        # RuntimeError, so bail out and stop the timer instead of crashing the event loop.
        try:
            if not self.isVisible():
                try:
                    self._bench_timer.stop()
                except RuntimeError:
                    pass
                self._bench_running = False
                return
        except RuntimeError:
            return
        now = time.monotonic()
        elapsed = now - self._bench_start_ts
        self._bench_last_ts = now

        # Time actual 3D projection + polygon rasterization without rebuilding the mesh each tick
        t0 = time.perf_counter()
        p = QPainter(self._bench_img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        mesh = self._bench_mesh
        rot = _rotation_matrix_xyz(0.15 * math.sin(elapsed * 4.0), elapsed * 3.6, 0.0)
        rv = mesh["verts"] @ rot.T
        tris = mesh["tris"]
        v0, v1, v2 = rv[tris[:, 0]], rv[tris[:, 1]], rv[tris[:, 2]]
        cz = (v0[:, 2] + v1[:, 2] + v2[:, 2]) / 3.0
        for idx in np.argsort(cz):
            i0, i1, i2 = int(tris[idx, 0]), int(tris[idx, 1]), int(tris[idx, 2])
            poly = QPolygonF([
                QPointF(190.0 + float(rv[i0, 0]) * 120.0, 190.0 + float(rv[i0, 1]) * 120.0),
                QPointF(190.0 + float(rv[i1, 0]) * 120.0, 190.0 + float(rv[i1, 1]) * 120.0),
                QPointF(190.0 + float(rv[i2, 0]) * 120.0, 190.0 + float(rv[i2, 1]) * 120.0),
            ])
            p.setBrush(QColor(56, 189, 248, 180))
            p.drawPolygon(poly)
        p.end()
        paint_ms = max(1.0, (time.perf_counter() - t0) * 1000.0)

        # Discard first 1.2s warmup window (Council recommendation to prevent false-fail from cold shader/cache stutter)
        if elapsed >= 1.20:
            self._bench_frame_times.append(paint_ms)

        pct = min(100, int((elapsed / 3.50) * 100))
        phase_lbl = "Warming up shaders (discarded)…" if elapsed < 1.20 else "Scoring live 3D spin frames…"
        self.bench_progress.setFormat(f"{pct}% — {phase_lbl}")
        self.bench_progress.setValue(pct)

        if elapsed >= 3.50:
            self._bench_timer.stop()
            self._bench_running = False
            self.bench_btn.setEnabled(True)
            self.bench_btn.setText("🔄 Re-Run 3.5s 3D Benchmark")
            self.bench_progress.hide()
            self._finalize_gpu_benchmark()

    def _finalize_gpu_benchmark(self) -> None:
        # Defence in depth: if any close path bypassed the timer stop, never persist a
        # tier derived from a partial sample set measured against a dialog that is gone.
        try:
            if not self.isVisible():
                return
        except RuntimeError:
            return
        hw = detect_system_gpu_and_power(force_refresh=False)
        if not self._bench_frame_times:
            self._cfg["benchmark_reason"] = "No valid benchmark samples — tier unchanged."
            self._refresh_hardware_telemetry_label()
            return
        ft = np.array(self._bench_frame_times, dtype=np.float32)
        avg_ms = float(np.mean(ft))
        p95_ms = float(np.percentile(ft, 95))
        stutters = int(np.sum(ft > 33.3))
        hz = float(hw.get("refresh_hz") or 60.0)
        avg_fps = min(hz, 1000.0 / max(4.0, avg_ms))

        if hw.get("is_software"):
            tier = "2d_fallback"
            reason = f"Software Renderer detected ({hw.get('gpu_name')}) → 2D Fallback"
        elif hw.get("is_dedicated") and avg_fps >= hz * 0.78 and p95_ms <= (1000.0 / hz) * 1.6:
            tier = "full_3d"
            reason = f"Dedicated GPU {avg_fps:.1f} FPS (p95 {p95_ms:.1f}ms, {stutters} stutters) → Full 3D Unlocked"
        elif avg_fps >= hz * 0.85 and p95_ms <= 14.0:
            tier = "full_3d"
            reason = f"High-Speed {avg_fps:.1f} FPS (p95 {p95_ms:.1f}ms, {stutters} stutters) → Full 3D Unlocked"
        elif avg_fps >= 24.0:
            tier = "lite_3d"
            reason = f"Solid {avg_fps:.1f} FPS (p95 {p95_ms:.1f}ms) on {hw.get('gpu_name')} → UT Lite 3D Selected"
        else:
            tier = "2d_fallback"
            reason = f"Low {avg_fps:.1f} FPS ({p95_ms:.1f}ms p95) → Safe 2D Fallback"

        self._cfg["benchmarked_tier"] = tier
        self._cfg["benchmark_fps"] = round(avg_fps, 1)
        self._cfg["benchmark_p95_ms"] = round(p95_ms, 1)
        self._cfg["benchmark_gpu_name"] = str(hw.get("gpu_name") or "")
        self._cfg["benchmark_reason"] = reason
        self._refresh_hardware_telemetry_label()
        self._emit_live()

    def _browse_custom_portrait(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Photorealistic or 3D Character Portrait Image",
            "",
            "Images (*.png *.jpg *.jpeg *.webp)",
        )
        if path:
            self._saved_portrait_path = path
            self.custom_path_edit.blockSignals(True)
            self.custom_path_edit.setText(path)
            self.custom_path_edit.blockSignals(False)
            self.engine_mode_cb.blockSignals(True)
            if str(self.engine_mode_cb.currentData() or "") not in ("studio_3d", "lifelike_portrait", "voxel_3d"):
                self._select_data(self.engine_mode_cb, "lifelike_portrait")
            self.engine_mode_cb.blockSignals(False)
            self.preset_cb.blockSignals(True)
            self._select_data(self.preset_cb, "custom")
            self.preset_cb.blockSignals(False)
            self._emit_live()

    def _browse_custom_mesh(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select 3D Character Mesh (.OBJ)",
            "",
            "3D Wavefront OBJ (*.obj)",
        )
        if path:
            self._saved_model_path = path
            self.custom_path_edit.blockSignals(True)
            self.custom_path_edit.setText(path)
            self.custom_path_edit.blockSignals(False)
            self.engine_mode_cb.blockSignals(True)
            self._select_data(self.engine_mode_cb, "ut_3d_mesh")
            self.engine_mode_cb.blockSignals(False)
            self._emit_live()

    def _custom_path_is_mesh(self) -> bool:
        return str(self.engine_mode_cb.currentData() or "").lower() == "ut_3d_mesh"

    def _sync_custom_asset_path(self) -> None:
        path = self._saved_model_path if self._custom_path_is_mesh() else self._saved_portrait_path
        was_blocked = self.custom_path_edit.blockSignals(True)
        try:
            self.custom_path_edit.setText(path)
        finally:
            self.custom_path_edit.blockSignals(was_blocked)
        self._custom_asset_path_synced = True

    def showEvent(self, event) -> None:
        self._sync_custom_asset_path()
        super().showEvent(event)

    def _on_engine_mode_changed(self, *_args) -> None:
        self._sync_custom_asset_path()
        eng = str(self.engine_mode_cb.currentData() or "studio_3d").lower()
        g = str(self.gender_cb.currentData() or "female").lower()
        if eng == "lifelike_portrait":
            self._select_data(self.preset_cb, "lifelike_male" if g == "male" else "lifelike_girl")
        elif eng == "voxel_3d":
            self._select_data(self.preset_cb, "brick_movie_male" if g == "male" else "brick_movie_female")
        elif eng == "studio_3d":
            self._select_data(self.preset_cb, "pixar_3d_male" if g == "male" else "pixar_3d_female")
        self._emit_live()

    def _on_preset_changed(self, *_args) -> None:
        pid = str(self.preset_cb.currentData() or "pixar_3d_female").lower()
        meta = AVATAR_PORTRAIT_PRESETS.get(pid)
        if meta:
            self.gender_cb.blockSignals(True)
            self._select_data(self.gender_cb, meta.get("gender", "female"))
            self.gender_cb.blockSignals(False)
            cur_eng = str(self.engine_mode_cb.currentData() or "studio_3d").lower()
            if cur_eng in ("studio_3d", "lifelike_portrait", "voxel_3d"):
                self.engine_mode_cb.blockSignals(True)
                self._select_data(self.engine_mode_cb, meta.get("engine_mode", "studio_3d"))
                self.engine_mode_cb.blockSignals(False)
        self._emit_live()

    def _on_gender_changed(self, *_args) -> None:
        g = str(self.gender_cb.currentData() or "female").lower()
        eng = str(self.engine_mode_cb.currentData() or "studio_3d").lower()
        if g == "male":
            if eng == "studio_3d":
                self._select_data(self.preset_cb, "pixar_3d_male")
            elif eng == "lifelike_portrait":
                self._select_data(self.preset_cb, "lifelike_male")
            elif eng == "voxel_3d":
                self._select_data(self.preset_cb, "brick_movie_male")
            if str(self.hair_style_cb.currentData() or "") in {"cozy_bun", "long_wavy", "curly"}:
                self._select_data(self.hair_style_cb, "short_crop")
            if str(self.outfit_cb.currentData() or "") == "cream":
                self._select_data(self.outfit_cb, "navy_hoodie")
            if str(self.beard_cb.currentData() or "none") == "none":
                self._select_data(self.beard_cb, "beard")
        elif g == "female":
            if eng == "studio_3d":
                self._select_data(self.preset_cb, "pixar_3d_female")
            elif eng == "lifelike_portrait":
                self._select_data(self.preset_cb, "lifelike_girl")
            elif eng == "voxel_3d":
                self._select_data(self.preset_cb, "brick_movie_female")
            if str(self.beard_cb.currentData() or "none") != "none":
                self._select_data(self.beard_cb, "none")
        self._emit_live()

    def current_config(self) -> dict[str, Any]:
        cpath = self.custom_path_edit.text().strip()
        if cpath.lower().endswith(".obj"):
            self._saved_model_path = cpath
        elif cpath:
            self._saved_portrait_path = cpath
        elif str(self.engine_mode_cb.currentData() or "").lower() == "ut_3d_mesh":
            # Empty field clears the slot for the mode actually being edited, so a
            # browsed custom file can always be removed again.
            self._saved_model_path = ""
        else:
            self._saved_portrait_path = ""
        return {
            "engine_mode": str(self.engine_mode_cb.currentData() or "studio_3d"),
            "preset_id": str(self.preset_cb.currentData() or "pixar_3d_female"),
            "custom_portrait_path": self._saved_portrait_path,
            "custom_model_path": self._saved_model_path,
            "hw_tier": str(self.hw_tier_cb.currentData() or "auto"),
            "benchmarked_tier": str(self._cfg.get("benchmarked_tier") or ""),
            "benchmark_fps": float(self._cfg.get("benchmark_fps") or 0.0),
            "benchmark_p95_ms": float(self._cfg.get("benchmark_p95_ms") or 0.0),
            "benchmark_gpu_name": str(self._cfg.get("benchmark_gpu_name") or ""),
            "benchmark_reason": str(self._cfg.get("benchmark_reason") or ""),
            "sleep_3d_on_battery": bool(self.battery_guard_chk.isChecked()),
            "comfyui_live_bridge": bool(self.comfy_chk.isChecked()),
            "show_landmark_overlay": bool(self.landmark_chk.isChecked()),
            "jaw_sensitivity": int(self.jaw_spin.value()),
            "gender": str(self.gender_cb.currentData() or "female"),
            "skin_tone": str(self.skin_cb.currentData() or "warm_light"),
            "hair_style": str(self.hair_style_cb.currentData() or "cozy_bun"),
            "hair_color": str(self.hair_col_cb.currentData() or "chestnut"),
            "eye_color": str(self.eye_col_cb.currentData() or "hazel"),
            "outfit_color": str(self.outfit_cb.currentData() or "cream"),
            "facial_hair": str(self.beard_cb.currentData() or "none"),
            "glasses": bool(self.glasses_chk.isChecked()),
        }

    def _emit_live(self, *_args) -> None:
        if callable(self._on_live_change):
            self._on_live_change(self.current_config())


class VoiceAvatarStageWindow(QWidget):
    """Optional Windowed or Full-Screen Voice Avatar stage with autohide slide-up bottom bar."""

    mode_changed = Signal(str)
    settings_changed = Signal(dict)
    mute_toggled = Signal(bool)
    stop_speaking_requested = Signal()
    end_talk_requested = Signal()
    open_settings_requested = Signal()
    return_to_chat_requested = Signal()
    model_control_requested = Signal()

    HOTZONE_PX = 48

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("voiceAvatarStageWindow")
        self._stage_mode = "windowed"  # "windowed" | "fullscreen"
        self._shape_id = "cartoon_character"
        self._palette_id = "tulsa_cyan"
        self._cartoon_cfg: dict[str, Any] = dict(DEFAULT_CARTOON_AVATAR_CONFIG)
        self._always_on_top = True
        self._show_activity = True
        self._muted = False
        self._menu_open = False
        self._programmatic_close = False

        self.setWindowTitle("Fairybread 3D Voice Avatar Stage")
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet("QWidget#voiceAvatarStageWindow { background: #030608; }")

        self.canvas = VoiceAvatarCanvas(self)
        self.canvas.installEventFilter(self)
        self.canvas.hologram_clicked.connect(self.stop_speaking_requested.emit)

        # Top-Left Clickable AI & Model Version Pill (Opens Mockup #3 Floating Control Panel Card)
        self.top_model_pill_btn = QPushButton("🧠 ◆ Gemini · 2.5 Flash ▾", self)
        self.top_model_pill_btn.setObjectName("avatarTopModelPill")
        self.top_model_pill_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.top_model_pill_btn.setToolTip("Click to open the AI & Model Version Control Panel (Switch Provider, Light/Intermediate/Heavy Tier, or Auto)")
        self.top_model_pill_btn.setStyleSheet(
            "QPushButton#avatarTopModelPill { background: rgba(17, 23, 36, 0.90); color: #f0f6fc; "
            "border: 1px solid rgba(129, 140, 248, 0.55); border-radius: 9px; padding: 5px 12px; "
            "font-size: 12px; font-weight: 700; } "
            "QPushButton#avatarTopModelPill:hover { background: rgba(30, 41, 59, 0.96); border-color: #38bdf8; }"
        )
        self.top_model_pill_btn.clicked.connect(self.model_control_requested.emit)

        # Top-Right Quick Cartoon Character Customizer Button
        self.top_customize_btn = QPushButton("🎨 Customize", self)
        self.top_customize_btn.setObjectName("avatarTopCustomizeBtn")
        self.top_customize_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.top_customize_btn.setToolTip("Customize Cartoon Character (Male/Female, Skin Tone, Hair Style & Color, Eye Color, Glasses, Outfit)")
        self.top_customize_btn.setStyleSheet(
            "QPushButton#avatarTopCustomizeBtn { background: rgba(17, 23, 36, 0.88); color: #c084fc; "
            "border: 1px solid rgba(192, 132, 252, 0.45); border-radius: 9px; padding: 5px 10px; "
            "font-size: 11.5px; font-weight: 700; } "
            "QPushButton#avatarTopCustomizeBtn:hover { background: rgba(35, 25, 56, 0.95); color: #ffffff; border-color: #c084fc; }"
        )
        self.top_customize_btn.clicked.connect(self.open_cartoon_customizer)

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
        cartoon_config: dict[str, Any] | None = None,
        model_pill_text: str | None = None,
        theme_dict: dict[str, Any] | None = None,
        provider_color_hex: str | None = None,
        always_on_top: bool | None = None,
        show_activity: bool | None = None,
    ) -> None:
        if shape_id is not None:
            self._shape_id = shape_id
            self.canvas.set_shape(shape_id)
        if cartoon_config is not None:
            self._cartoon_cfg = dict(cartoon_config)
            self.canvas.set_cartoon_config(self._cartoon_cfg)
        if model_pill_text is not None and hasattr(self, "top_model_pill_btn"):
            self.top_model_pill_btn.setText(str(model_pill_text))
            self.top_model_pill_btn.adjustSize()
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
        if hasattr(self, "top_customize_btn"):
            self.top_customize_btn.setVisible(self._shape_id == "cartoon_character")
        self._sync_dock_compact_buttons()
        self._layout_overlays()

    def open_cartoon_customizer(self) -> None:
        if self._shape_id != "cartoon_character":
            self._pick_shape("cartoon_character")

        def _on_live(new_cfg: dict[str, Any]) -> None:
            self._cartoon_cfg = dict(new_cfg)
            self.canvas.set_cartoon_config(self._cartoon_cfg)
            self.settings_changed.emit({"cartoon_avatar_config": self._cartoon_cfg})

        dlg = CartoonCharacterCustomizerDialog(
            self,
            initial_config=self._cartoon_cfg,
            on_live_change=_on_live,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            _on_live(dlg.current_config())

    def present_in_mode(self, mode: str) -> None:
        """Show the avatar window cleanly in `'windowed'` or `'fullscreen'` mode."""
        target = "fullscreen" if mode == "fullscreen" else "windowed"
        prev = self._stage_mode
        self._stage_mode = target
        want_on_top = bool(target == "windowed" and self._always_on_top)
        has_on_top = bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        if has_on_top != want_on_top:
            was_vis = self.isVisible()
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, want_on_top)
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

    def set_cast_avatars(self, cast_slots: list[dict[str, Any]] | None, active_slot_index: int = 0) -> None:
        """Update the 3D stage with 1..4 active AI voice avatars and speaker spotlight."""
        self.canvas.set_cast_avatars(cast_slots, active_slot_index=active_slot_index)

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
        if hasattr(self, "top_model_pill_btn"):
            self.top_model_pill_btn.adjustSize()
            self.top_model_pill_btn.move(12, 10)
            self.top_model_pill_btn.raise_()
        if hasattr(self, "top_customize_btn"):
            self.top_customize_btn.adjustSize()
            self.top_customize_btn.move(max(160, w - self.top_customize_btn.width() - 12), 10)
            self.top_customize_btn.raise_()
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

        s_sub = menu.addMenu("Avatar Style / Shape")
        for sid, slabel in AVATAR_SHAPES:
            act = s_sub.addAction(("✓ " if self._shape_id == sid else "   ") + slabel)
            act.triggered.connect(lambda _c=False, s_val=sid: self._pick_shape(s_val))

        cust_act = menu.addAction("🎨 Customize Cartoon Character…")
        cust_act.triggered.connect(self.open_cartoon_customizer)

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
        if getattr(self.canvas, "_cast_slots", None) and len(self.canvas._cast_slots) == 1:
            self.canvas._cast_slots[0]["avatar_shape"] = shape_id
            self.canvas.update()
        self.settings_changed.emit({"voice_avatar_shape": shape_id})

    def _pick_palette(self, palette_id: str) -> None:
        self._palette_id = palette_id
        self.canvas.set_palette_config(palette_id)
        if getattr(self.canvas, "_cast_slots", None) and len(self.canvas._cast_slots) == 1:
            self.canvas._cast_slots[0]["avatar_palette"] = palette_id
            self.canvas.update()
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
