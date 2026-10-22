"""Camera geometry; target distance is an explicit user-supplied assumption."""
import math

def validate_motion(mode, travel, distance):
    if mode not in ('independent', 'target_distance'):
        raise ValueError('Unknown zoom mode.')
    if not math.isfinite(travel) or travel < 0:
        raise ValueError('Travel must be finite and non-negative.')
    if mode == 'target_distance' and (not math.isfinite(distance) or distance <= travel):
        raise ValueError('Target distance must be finite and greater than travel distance.')

def motion_scales(t, zoom, travel, mode='independent', distance=0):
    """Return background magnification, extra stellar zoom, travelled parsecs."""
    validate_motion(mode, travel, distance)
    move=travel*t
    if mode == 'target_distance':
        return distance/(distance-move), 1.0, move
    z=1+(zoom-1)*t
    return z,z,move
