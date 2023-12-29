from dataclasses import dataclass
from pathlib import Path
from typing import Tuple


CATEGORIES = [
    'Actions',
    'Buildings',
    'Features',
    'Items',
    'Traits',
    'Units',
    'Upgrades',
    'Weapons'
]
FACTIONS = [
    'AdeptusMechanicus',
    'AstraMilitarum',
    'ChaosSpaceMarines',
    'Drukhari',
    'Eldar',
    'Necrons',
    'Neutral',
    'Orks',
    'SistersOfBattle',
    'SpaceMarines',
    'Tau',
    'Tyranids',
]


@dataclass(frozen=True)
class Origin:
    path: Path

    @property
    def name(self) -> str:
        return self.path.stem

    @property
    def category(self) -> str:
        parent = self.path.parent
        if parent.name in FACTIONS:
            category = parent.parent.name
        else:
            category = parent.name
            if category == "Artefacts":
                if parent.parent.name in CATEGORIES:
                    category = parent.parent.name
                else:
                    category = parent.parent.parent.name
        return category

    @property
    def category_path(self) -> Path:
        idx = self.path.parts.index(self.category)
        return Path(*self.path.parts[idx:])

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(f"Unknown category: {self.category!r}")


@dataclass(frozen=True)
class Trait(Origin):
    required_upgrade: str | None

    def __post_init__(self) -> None:
        if self.category != "Traits":
            raise ValueError(f"Not a path to a trait .xml: {self.path}")


@dataclass(frozen=True)
class Weapon(Origin):
    attacks: int | None
    melee_armor_penetration: int | None
    melee_damage: float | None
    ranged_armor_penetration: int | None
    ranged_damage: float | None
    range: int | None
    traits: Tuple[Trait, ...]

    def __post_init__(self) -> None:
        if self.category != "Weapons":
            raise ValueError(f"Not a path to a weapon .xml: {self.path}")


@dataclass(frozen=True)
class Upgrade(Origin):
    tier: int
    reference: Origin
    required_upgrades: Tuple["Upgrade", ...]

    @property
    def ref_category(self) -> str:
        return self.reference.category

    def __post_init__(self) -> None:
        if self.category != "Upgrades":
            raise ValueError(f"Not a path to an upgrade .xml: {self.path}")
        if self.tier not in range(11):
            raise ValueError("Tier must be an integer between 0 and 10")
        if any(u.tier > self.tier for u in self.required_upgrades):
            raise ValueError("Required upgrades cannot be of surpassing tier")


@dataclass(frozen=True)
class Action(Origin):
    weapon: Weapon | None
    cooldown: int | None
    required_upgrade: Upgrade | None

    def __post__init__(self) -> None:
        if self.category != "Units":
            raise ValueError(f"Not a path to an unit .xml: {self.path}")
        if self.cooldown and self.cooldown < 0:
            raise ValueError("Cooldown must not be negative")


@dataclass(frozen=True)
class Unit(Origin):
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

    def __post__init__(self) -> None:
        if self.category != "Units":
            raise ValueError(f"Not a path to an unit .xml: {self.path}")


