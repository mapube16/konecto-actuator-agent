from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class Actuator(BaseModel):
    model_config = ConfigDict(strict=False)

    # Identity
    base_part_number: str = Field(..., min_length=5)
    enclosure_type: str
    voltage: str
    phase: str
    application_type: str

    # Mechanical
    torque_inlbs: float = Field(..., gt=0)
    torque_nm: float = Field(..., gt=0)

    # Duty / cycle
    duty_cycle: float = Field(..., ge=0, le=100)
    cycles_per_hour: float
    starts_per_hour: float

    # Motor
    motor_power_watts: float = Field(..., gt=0)
    csa_certified: bool

    # AC-frequency-dependent fields (null for DC-only or N/A models)
    speed_60hz: Optional[float] = None
    speed_50hz: Optional[float] = None
    fla_60hz: Optional[float] = None
    fla_50hz: Optional[float] = None
    lra_60hz: Optional[float] = None
    lra_50hz: Optional[float] = None


if __name__ == "__main__":
    sample = {
        "base_part_number": "761A00-11300000/A",
        "enclosure_type": "weatherproof",
        "voltage": "110V",
        "phase": "single",
        "application_type": "on/off",
        "torque_inlbs": 700.0,
        "torque_nm": 80.0,
        "duty_cycle": 40.0,
        "cycles_per_hour": 36.0,
        "starts_per_hour": 960.0,
        "motor_power_watts": 15.0,
        "csa_certified": True,
        "speed_60hz": 17.0,
        "speed_50hz": 20.0,
        "fla_60hz": 1.2,
        "fla_50hz": 1.1,
        "lra_60hz": 1.4,
        "lra_50hz": 1.3,
    }
    a = Actuator.model_validate(sample)
    assert a.base_part_number == "761A00-11300000/A"
    assert a.torque_nm > 0
    assert isinstance(a.csa_certified, bool)
    print("schema self-test passed")
