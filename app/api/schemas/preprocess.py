from __future__ import annotations
from typing import Optional, List, Dict
from pydantic import BaseModel


class ButterworthConfig(BaseModel):
    cutoff_hz: float
    order: int = 4


class PreprocessConfig(BaseModel):
    schema_yaml: str
    normalize_ranges: Dict[str, float]
    strict: bool = False
    zeroing_enabled: bool = True
    zero_window_s: float = 1.0
    zero_min_samples: int = 10
    clip_0_1: bool = False
    butterworth_smoothing: List[ButterworthConfig] = []
    butterworth_generate_residuals: bool = False
    active_signal_disp_col: Optional[str] = None
    active_signal_vel_col: Optional[str] = None
    active_disp_thresh: float = 20.0
    active_vel_thresh: float = 50.0
    active_window: str = "500ms"
    active_padding: str = "1s"
    active_min_seg: str = "3s"
    sample_rate_hz: Optional[float] = None
