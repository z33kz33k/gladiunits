from enum import Enum
from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal, Tuple, ClassVar, Type

from gladiunits.utils import from_iterable

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
    def faction(self) -> str | None:
        return from_iterable(self.path.parts, lambda p: p in FACTIONS)

    @property
    def category_path(self) -> Path:
        idx = self.path.parts.index(self.category)
        return Path(*self.path.parts[idx:-1], self.path.stem)

    @property
    def name(self) -> str:
        return str(Path(*self.category_path.parts[1:]))

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(f"Unknown category: {self.category!r}")


@dataclass(frozen=True)
class TextsMixin:
    name: str
    description: str | None
    flavor: str | None

    @property
    def properties(self) -> tuple:
        return self.name, self.description, self.flavor

    @staticmethod
    def from_other(other: "TextsMixin") -> "TextsMixin":
        return TextsMixin(*other.properties)


@dataclass(frozen=True)
class ReferenceMixin:
    reference: Path | None  # TODO: to be resolved into actual referenced objects (if possible)

    @property
    def reffed_category(self) -> str | None:
        if not self.reference:
            return None
        origin = Origin(self.reference)
        return origin.category


@dataclass(frozen=True)
class Upgrade(ReferenceMixin, TextsMixin, Origin):
    tier: int
    required_upgrades: Tuple["Upgrade", ...]

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.category != "Upgrades":
            raise ValueError(f"Not a path to an upgrade .xml: {self.path}")
        if self.tier not in range(11):
            raise ValueError("Tier must be an integer between 0 and 10")
        if any(u.tier > self.tier for u in self.required_upgrades):
            raise ValueError("Required upgrades cannot be of surpassing tier")


@dataclass(frozen=True)
class Parameter:
    TYPES: ClassVar[Tuple[Tuple[str, Type], ...]] = {
        'action': str,
        'add': float,
        'addMax': float,
        'addMin': float,
        'count': int,
        'duration': float,
        'equal': float,
        'greater': float,
        'less': float,
        'match': str,
        'max': float,
        'min': float,
        'minMax': float,
        'minMin': float,
        'mul': float,
        'mulMax': float,
        'mulMin': float,
        'name': str,
        'range': float,
        'weapon': str,
    }
    type: str
    value: str

    def __post_init__(self) -> None:
        if self.type not in self.TYPES:
            raise TypeError(f"Unrecognized parameter type: {self.type!r}")


@dataclass(frozen=True)
class Effect:
    name: str
    params: Tuple[Parameter, ...]
    sub_effects: Tuple["Effect", ...]

    @property
    def all_params(self) -> List[Parameter]:
        return [*self.params, *[p for e in self.sub_effects for p in e.all_params]]


class ModifierType(Enum):
    REGULAR = 'modifiers'
    ON_COMBAT_OPPONENT = 'onCombatOpponentModifiers'
    ON_COMBAT_SELF = 'onCombatSelfModifiers'
    ON_ENEMY_KILLED_OPPONENT_TILE = 'onEnemyKilledOpponentTileModifiers'
    ON_ENEMY_KILLED_SELF_AREA = 'onEnemyKilledSelf'
    ON_ENEMY_KILLED_SELF = 'onEnemyKilledSelfModifiers'
    ON_TILE_ENTERED = 'onTileEnteredModifiers'
    ON_TRAIT_ADDED = 'onTraitAddedModifiers'
    ON_TRAIT_REMOVED = 'onTraitRemovedModifiers'
    ON_TRANSPORT_DISEMBARKED = 'onTransportDisembarked'
    ON_TRANSPORT_EMBARKED = 'onTransportEmbarked'
    ON_UNIT_DISAPPEARED_AREA = 'onUnitDisappeared'
    ON_UNIT_DISAPPEARED = 'onUnitDisappearedModifiers'
    ON_UNIT_DISEMBARKED = 'onUnitDisembarked'
    OPPONENT = 'opponentModifiers'
    # <perTurnModifiers endure="0"/> 'endure' is not parsed as it's always there and the same
    PER_TURN = 'perTurnModifiers'
    UNKNOWN = "unknown"

    @classmethod
    def from_tag(cls, tag: str) -> "ModifierType":
        try:
            return cls(tag)
        except ValueError:
            return cls.UNKNOWN


@dataclass(frozen=True)
class Modifier:
    type: ModifierType
    conditions: Tuple[Effect, ...]
    effects: Tuple[Effect, ...]

    @property
    def all_effects(self) -> List[Effect]:
        return [*self.conditions, *self.effects]

    @property
    def all_params(self) -> List[Parameter]:
        return [p for e in self.all_effects for p in e.all_params]


@dataclass(frozen=True)
class Area:
    affects: Literal["Unit", "Player"]
    radius: int | None


@dataclass(frozen=True)
class AreaModifier(Modifier):
    area: Area


@dataclass(frozen=True)
class ModifiersMixin:
    modifiers: Tuple[Modifier | AreaModifier, ...]

    @property
    def all_effects(self) -> List[Effect]:
        return [e for m in self.modifiers for e in m.all_effects]


@dataclass(frozen=True)
class Trait(ModifiersMixin, ReferenceMixin, TextsMixin, Origin):
    sub_category: Literal["Buff", "Debuff"] | None
    target_conditions: Tuple[Effect, ...]

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.category != "Traits":
            raise ValueError(f"Not a path to a trait .xml: {self.path}")

    @property
    def all_effects(self) -> List[Effect]:  # override
        return [*self.target_conditions, *super().all_effects]


@dataclass(frozen=True)
class Weapon(ModifiersMixin, TextsMixin, Origin):
    attacks: int | None
    melee_armor_penetration: int | None
    melee_damage: float | None
    ranged_armor_penetration: int | None
    ranged_damage: float | None
    range: int | None
    traits: Tuple[Trait, ...]

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.category != "Weapons":
            raise ValueError(f"Not a path to a weapon .xml: {self.path}")


@dataclass(frozen=True)
class Action:
    weapon: Weapon | None
    cooldown: int | None
    required_upgrade: Upgrade | None

    def __post_init__(self) -> None:
        if self.cooldown and self.cooldown < 0:
            raise ValueError("Cooldown must not be negative")


@dataclass(frozen=True)
class Unit(ModifiersMixin, TextsMixin, Origin):
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

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.category != "Units":
            raise ValueError(f"Not a path to an unit .xml: {self.path}")
