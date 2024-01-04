from enum import Enum
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, ClassVar, TypeAlias, Union

from gladiunits.utils import from_iterable

CATEGORIES = [
    'Actions',
    'Buildings',
    'Cities',
    'Factions',
    'Features',
    'Items',
    'Scenarios',
    'Traits',
    'Units',
    'Upgrades',
    'Weapons',
    'WorldParameters',
]
PARSED_CATEGORIES = [
    # 'Actions',
    # 'Buildings',
    # 'Cities',
    # 'Factions',
    # 'Features',
    # 'Items',
    # 'Scenarios',
    'Traits',
    'Units',
    'Upgrades',
    'Weapons',
    # 'WorldParameters',
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
            # handle edge cases like '<noCooldownAction name="SerpentShield/SerpentShield"/>'
            # in Eldar/SerpentShield.xml
            if category == self.path.stem:
                idx = self.path.parts.index(category)
                if idx > 0:
                    idx -= 1
                    category = self.path.parts[idx]
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
            raise ValueError(f"unknown category: {self.category!r}")


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


Parsed: TypeAlias = Union["Upgrade", "Trait", "Weapon", "Unit"]


@dataclass(frozen=True)
class ReferenceMixin:
    reference: Parsed | Origin | None

    @property
    def reffed_category(self) -> str | None:
        if not isinstance(self.reference, Origin):
            return None
        return self.reference.category


@dataclass(frozen=True)
class Parameter:
    TYPES: ClassVar[dict[str, Any]] = {
        'action': Origin,
        'add': float,
        'addMax': float,
        'addMin': float,
        'base': int,
        'count': int,
        'duration': int,
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
        'name': Origin,
        'rank': int,
        'range': int,
        'reference': Origin,
        'requiredUpgrade': Origin,
        'weapon': Origin,
    }
    type: str
    value: Parsed | Origin | float | int | str | bool

    def __post_init__(self) -> None:
        if self.type not in self.TYPES:
            raise TypeError(f"unrecognized parameter type: {self.type!r}")

    @property
    def is_dereferenced(self) -> bool:
        if isinstance(self.value, Origin) and self.value.category in PARSED_CATEGORIES:
            return False
        return True


@dataclass(frozen=True)
class Effect:
    name: str
    params: tuple[Parameter, ...]
    sub_effects: tuple["Effect", ...]

    @property
    def all_params(self) -> list[Parameter]:
        return [*self.params, *[p for e in self.sub_effects for p in e.all_params]]

    @property
    def is_dereferenced(self) -> bool:
        return all(p.is_dereferenced for p in self.all_params)

    @property
    def is_negative(self) -> bool:
        return len(self.name) > 3 and self.name.startswith("no") and self.name[2].isupper()


@dataclass(frozen=True)
class CategoryEffect(Effect):
    def __post_init__(self) -> None:
        if not self.is_valid(self.name):
            raise TypeError(f"not a category effect: {self.name!r}")

    @classmethod
    def get_category(cls, name: str) -> str | None:
        if name == "city" or name == "noCity":
            return "Cities"
        if name in ("self", "opponent"):
            return "Units"
        categories = [cat[:-1].lower() for cat in CATEGORIES]
        cat = from_iterable(categories, lambda c: c in name.lower())
        if not cat:
            return None
        return CATEGORIES[categories.index(cat)]

    @classmethod
    def is_valid(cls, name: str) -> bool:
        return cls.get_category(name) is not None

    @property
    def category(self) -> str:
        return self.get_category(self.name)


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
    conditions: tuple[Effect, ...]
    effects: tuple[Effect, ...]

    @property
    def all_effects(self) -> list[Effect]:
        return [*self.conditions, *self.effects]

    @property
    def all_params(self) -> list[Parameter]:
        return [p for e in self.all_effects for p in e.all_params]

    @property
    def is_dereferenced(self) -> bool:
        return all(p.is_dereferenced for p in self.all_params)


@dataclass(frozen=True)
class Area:
    affects: Literal["Unit", "Player", "Tile"]
    radius: int | None
    exclude_radius: int | None


@dataclass(frozen=True)
class AreaModifier(Modifier):
    area: Area


@dataclass(frozen=True)
class ModifiersMixin:
    modifiers: tuple[Modifier | AreaModifier, ...]

    @property
    def all_effects(self) -> list[Effect]:
        return [e for m in self.modifiers for e in m.all_effects]


@dataclass(frozen=True)
class Upgrade(ReferenceMixin, TextsMixin, Origin):
    tier: int
    required_upgrades: tuple[Union["Upgrade",  Origin], ...]
    dlc: str | None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.category != "Upgrades":
            raise ValueError(f"not a path to an upgrade .xml: {self.path}")
        if self.tier not in range(11):
            raise ValueError("tier must be an integer between 0 and 10")

    @property
    def is_dereferenced(self) -> bool:
        if (self.reference is not None
                and isinstance(self.reference, Origin)
                and self.reference.category_path in PARSED_CATEGORIES):
            return False
        return all(isinstance(u, Upgrade) for u in self.required_upgrades)


@dataclass(frozen=True)
class Trait(ModifiersMixin, ReferenceMixin, TextsMixin, Origin):
    type: Literal["Buff", "Debuff"] | None
    target_conditions: tuple[Effect, ...]
    max_rank: int | None
    stacking: bool | None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.category != "Traits":
            raise ValueError(f"not a path to a trait .xml: {self.path}")

    @property
    def all_effects(self) -> list[Effect]:  # override
        return [*self.target_conditions, *super().all_effects]

    @property
    def is_dereferenced(self) -> bool:
        if (self.reference is not None
                and isinstance(self.reference, Origin)
                and self.reference.category_path in PARSED_CATEGORIES):
            return False
        return all(m.is_dereferenced for m in self.modifiers) and all(
            tc.is_dereferenced for tc in self.target_conditions)


@dataclass(frozen=True)
class Target:
    max_range: int
    conditions: tuple[Effect, ...]

    @property
    def is_dereferenced(self) -> bool:
        return all(c.is_dereferenced for c in self.conditions)


class WeaponType(Enum):
    BEAM = 'beamWeapon'
    EXPLOSIVE = 'explosiveWeapon'
    FLAMER = 'flamerWeapon'
    GRENADE = 'grenadeWeapon'
    MISSILE = 'missileWeapon'
    POWER = 'powerWeapon'
    PROJECTILE = 'projectileWeapon'
    REGULAR = 'weapon'
    UNKNOWN = 'unknown'

    @classmethod
    def from_tag(cls, tag: str) -> "WeaponType":
        try:
            return cls(tag)
        except ValueError:
            return cls.UNKNOWN


@dataclass(frozen=True)
class Weapon(ModifiersMixin, ReferenceMixin, TextsMixin, Origin):
    type: WeaponType
    target: Target | None
    traits: tuple[CategoryEffect, ...]

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.category != "Weapons":
            raise ValueError(f"not a path to a weapon .xml: {self.path}")

    @property
    def is_dereferenced(self) -> bool:
        if (self.reference is not None
                and isinstance(self.reference, Origin)
                and self.reference.category_path in PARSED_CATEGORIES):
            return False
        if self.target is not None and not self.target.is_dereferenced:
            return False
        return all(m.is_dereferenced for m in self.modifiers) and all(
            t.is_dereferenced for t in self.traits)


@dataclass(frozen=True)
class Unit(ModifiersMixin, ReferenceMixin, TextsMixin, Origin):
    group_size: int
    modifiers: tuple[Modifier, ...]
    weapons: tuple[CategoryEffect, ...]
    # TODO: parse action modifiers, targets (extend Weapon target parsing)
    actions: tuple[CategoryEffect, ...]
    traits: tuple[CategoryEffect, ...]

    # @property
    # def total_hitpoints(self) -> float:
    #     return self.hitpoints * self.group_size
    #
    def __post_init__(self) -> None:
        super().__post_init__()
        if self.category != "Units":
            raise ValueError(f"not a path to an unit .xml: {self.path}")

    @property
    def is_dereferenced(self) -> bool:
        if (self.reference is not None
                and isinstance(self.reference, Origin)
                and self.reference.category_path in PARSED_CATEGORIES):
            return False
        return all(m.is_dereferenced for m in self.modifiers) and all(
            e.is_dereferenced for e in (*self.weapons, *self.actions, *self.traits))
