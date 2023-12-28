from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class Trait:
    name: str
    required_upgrade: str | None


@dataclass(frozen=True)
class Weapon:
    name: str
    displayed_name: str
    attacks: int | None
    melee_armor_penetration: int | None
    melee_damage: float | None
    ranged_armor_penetration: int | None
    ranged_damage: float | None
    range: int | None
    traits: Tuple[Trait, ...]


@dataclass(frozen=True)
class Upgrade:
    name: str
    tier: int
    required_upgrades: Tuple["Upgrade", ...]

    def __post_init__(self) -> None:
        if self.tier not in range(1, 11):
            raise ValueError("Tier must be an integer between 1 and 10")
        if any(u.tier > self.tier for u in self.required_upgrades):
            raise ValueError("Required upgrades cannot be of surpassing tier")


@dataclass(frozen=True)
class Action:
    name: str
    displayed_name: str
    weapon: Weapon | None
    cooldown: int | None

    def __post__init__(self) -> None:
        if self.cooldown and self.cooldown < 0:
            raise ValueError("Cooldown must not be negative")


@dataclass(frozen=True)
class Unit:
    name: str
    displayed_name: str
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
    actions: Tuple[Action, ...]
    traits: Tuple[Trait, ...]

    @property
    def total_hitpoints(self) -> float:
        return self.hitpoints * self.group_size


