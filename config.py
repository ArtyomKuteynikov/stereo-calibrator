from pathlib import Path

_HERE = Path(__file__).parent

CAPTURE_DIR = _HERE / "images"

COUNTDOWN_SECS = 0.5
COOLDOWN_SECS = 1

STATE_IDLE = "idle"
STATE_COUNTDOWN = "countdown"
STATE_COOLDOWN = "cooldown"

ZONE_NAMES = {
    (0, 0): "верхний левый угол",
    (0, 1): "верх центр",
    (0, 2): "верхний правый угол",
    (1, 0): "левый центр",
    (1, 1): "центр",
    (1, 2): "правый центр",
    (2, 0): "нижний левый угол",
    (2, 1): "низ центр",
    (2, 2): "нижний правый угол",
}
