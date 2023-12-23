"""

    gladiunits.__init__.py
    ~~~~~~~~~~~~~~~~~~~~~~
    Process WHK40: Gladius XMLs.

    @author: z33k

"""
from dataclasses import dataclass
from typing import Tuple

from gladiunits.utils import init_log


init_log()


@dataclass
class Weapon:
    name: str


@dataclass
class Action:
    name: str


@dataclass
class Trait:
    name: str


@dataclass
class Upgrade:
    name: str
    tier: int


@dataclass
class Unit:
    name: str
    armor: int
    hitpoints: float
    movement: int
    morale: int
    melee_accuracy: int
    melee_attacks: int
    ranged_accuracy: int
    ranged_attacks: int
    production_cost: float
    requisitions_upkeep: float
    requisitions_cost: float
    group_size: int
    weapons: Tuple[Weapon, ...]

    @property
    def total_hitpoints(self) -> float:
        return self.hitpoints * self.group_size

