"""Integrate presentation motion without rescaling its elapsed history."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .persistent_world import FieldForcing
    from .scene_director import SceneMotion


@dataclass(slots=True)
class MotionPhases:
    """Live visual travel, retained with the field across seeks and GPU rebuilds."""

    travel: float = 0.0
    orbit: float = 0.0
    orbit_distance: float = 0.0
    depth: float = 0.0
    flow_x: float = 0.0
    flow_y: float = 0.0
    parallax_x: float = 0.0
    parallax_y: float = 0.0
    energy_journey: float = 0.0
    depth_journey: float = 0.0
    energy_depth_journey: float = 0.0
    excitation: float = 0.0
    filament_growth: float = 0.0
    filament_travel: float = 0.0
    energy: float = 0.0

    def advance(
        self, delta_seconds: float, motion: SceneMotion, forcing: FieldForcing
    ) -> None:
        """Apply current rates only to newly elapsed, unpaused field time."""

        if delta_seconds <= 0.0:
            return
        journey = delta_seconds * (0.18 + motion.travel_rate * 0.42)
        self.travel += delta_seconds * motion.travel_rate
        self.orbit += delta_seconds * motion.orbit_rate
        self.orbit_distance += delta_seconds * abs(motion.orbit_rate)
        self.depth += delta_seconds * motion.depth_rate
        self.flow_x += journey * motion.direction_x
        self.flow_y += journey * motion.direction_y
        self.parallax_x += journey * motion.direction_x * motion.parallax
        self.parallax_y += journey * motion.direction_y * motion.parallax
        self.energy_journey += journey * forcing.energy
        self.depth_journey += journey * motion.depth_rate
        self.energy_depth_journey += journey * motion.depth_rate * forcing.energy
        self.excitation += delta_seconds * forcing.curl
        self.filament_growth += delta_seconds * (
            0.014 + forcing.harmonic_coherence * 0.024 + forcing.harmonic_layer * 0.018
        )
        self.filament_travel += delta_seconds * (
            0.18 + forcing.energy * 0.7 + forcing.vocal_layer * 0.24
        )
        self.energy += delta_seconds * forcing.energy

    def uniform_values(self) -> tuple[float, ...]:
        """Pack the four phase vectors in the shared FieldState order."""

        return (
            self.travel,
            self.orbit,
            self.orbit_distance,
            self.depth,
            self.flow_x,
            self.flow_y,
            self.parallax_x,
            self.parallax_y,
            self.energy_journey,
            self.depth_journey,
            self.energy_depth_journey,
            self.excitation,
            self.filament_growth,
            self.filament_travel,
            self.energy,
            0.0,
        )
