"""

    gladiunits.data.py
    ~~~~~~~~~~~~~~~~~~
    Data structures.

    @author: z33k

"""
from collections import OrderedDict, defaultdict
from enum import Enum
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, ClassVar, Type, TypeAlias, Union

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


@dataclass
class Origin:
    path: Path

    @property
    def category(self) -> str:
        parent = self.path.parent
        if parent.name in FACTIONS:
            category = parent.parent.name
        elif parent.parent.name in FACTIONS:
            category = parent.parent.parent.name
        else:
            category = parent.name
            if category == "Artefacts":
                if parent.parent.name in CATEGORIES:
                    category = parent.parent.name
                else:
                    category = parent.parent.parent.name
            elif category == "Items" and parent.parent.name == "Traits":
                category = "Traits"
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
    def stem(self) -> str:
        return str(Path(*self.category_path.parts[1:]))

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(f"unknown category: {self.category!r}")

    def __str__(self) -> str:
        return str(self.path)


@dataclass
class TextsMixin:
    name: str
    description: str | None
    flavor: str | None


Parsed: TypeAlias = Union["Upgrade", "Trait", "Weapon", "Unit"]
ParamValue: TypeAlias = (Parsed | list[Parsed] | Origin | list[Origin] | float | int | str | bool)


@dataclass
class ReferenceMixin:
    reference: Parsed | Origin | None

    @property
    def reffed_category(self) -> str | None:
        if not isinstance(self.reference, Origin):
            return None
        return self.reference.category


def is_unresolved_reference(value: Any) -> bool:
    return type(value) is Origin and value.category in PARSED_CATEGORIES


@dataclass
class Parameter:
    TYPES: ClassVar[dict[str, Any]] = {
        'action': Origin,
        'add': float,
        'addMax': float,
        'addMin': float,
        'base': float,
        'beginOnDisappear': bool,
        'charges': int,
        'consumedAction': bool,
        'consumedActionPoints': bool,
        'consumedMovement': bool,
        'cooldown': int,
        'cooldownMin': int,
        'cooldownMax': int,
        'cooldownRemaining': int,
        'cooldownScalesWithPace': bool,
        'costScalesWithPace': bool,
        'count': int,
        'countMax': int,
        'disableable': bool,
        'duration': int,
        'durationMin': int,
        'durationMax': int,
        'elite': bool,
        'enabled': bool,
        'equal': float,
        'greater': float,
        'interfaceSound': str,
        'less': float,
        'levelMin': int,
        'levelMax': int,
        'levelUpPriority': float,
        'match': str,
        'max': float,
        'min': float,
        'minMax': float,
        'minMin': float,
        'mul': float,
        'mulMax': float,
        'mulMin': float,
        'name': Origin,
        'passive': bool,
        'psychicPower': bool,
        'radius': int,
        'rank': int,
        'rankMax': int,
        'range': int,
        'reference': Origin,
        'removeOnSourceDeath': bool,
        'requiredActionPoints': bool,
        'requiredMovement': bool,
        'requiredUpgrade': Origin,
        'shoutString': Origin,
        'slotName': str,
        'unit': Origin,
        'unitType': Origin,
        'usableInTransport': bool,
        'visible': bool,
        'weapon': Origin,
        'weaponSlotName': Origin,
        'weaponSlotNames': (tuple, Origin),
    }
    type: str
    value: ParamValue

    def __post_init__(self) -> None:
        if self.type not in self.TYPES:
            raise TypeError(f"unrecognized parameter type: {self.type!r}")

    @property
    def is_resolved(self) -> bool:
        if is_unresolved_reference(self.value):
            return False
        if isinstance(self.value, list) and any(is_unresolved_reference(v) for v in self.value):
            return False
        return True


@dataclass
class Effect:
    name: str
    params: list[Parameter]
    sub_effects: list["Effect"]

    @property
    def all_params(self) -> list[Parameter]:
        return [*self.params, *[p for e in self.sub_effects for p in e.all_params]]

    @property
    def unresolved_references(self) -> list[Origin]:
        return sorted([p.value for p in self.all_params if not p.is_resolved], key=str)

    @property
    def is_resolved(self) -> bool:
        return not self.unresolved_references

    @property
    def is_negative(self) -> bool:
        return len(self.name) > 3 and self.name.startswith("no") and self.name[2].isupper()


@dataclass
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


@dataclass
class Modifier:
    type: ModifierType
    conditions: list[Effect]
    effects: list[Effect]

    @property
    def all_effects(self) -> list[Effect]:
        return [*self.conditions, *self.effects]

    @property
    def all_params(self) -> list[Parameter]:
        return [p for e in self.all_effects for p in e.all_params]

    @property
    def unresolved_references(self) -> list[Origin]:
        return sorted([p.value for p in self.all_params if not p.is_resolved], key=str)

    @property
    def is_resolved(self) -> bool:
        return all(p.is_resolved for p in self.all_params)


@dataclass(frozen=True)
class Area:
    affects: Literal["Unit", "Player", "Tile"]
    radius: int | None
    exclude_radius: int | None


@dataclass
class AreaModifier(Modifier):
    area: Area


@dataclass
class ModifiersMixin:
    modifiers: list[Modifier | AreaModifier]

    @property
    def all_effects(self) -> list[Effect]:
        return [e for m in self.modifiers for e in m.all_effects]

    @property
    def mod_effects(self) -> list[Effect]:
        return [e for m in self.modifiers for e in m.effects]

    @property
    def unresolved_references(self) -> list[Origin]:
        return sorted(
            [p.value for e in self.all_effects for p in e.all_params if not p.is_resolved], key=str)

    @property
    def is_resolved(self) -> bool:
        return not self.unresolved_references


@dataclass
class Upgrade(ReferenceMixin, TextsMixin, Origin):
    tier: int
    required_upgrades: list[Union["Upgrade",  Origin]]
    dlc: str | None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.category != "Upgrades":
            raise ValueError(f"not a path to an upgrade .xml: {self.path}")
        if self.tier not in range(11):
            raise ValueError("tier must be an integer between 0 and 10")

    @property
    def unresolved_references(self) -> list[Origin]:
        refs = []
        if is_unresolved_reference(self.reference):
            refs.append(self.reference)
        return sorted(
            [*refs, *[u for u in self.required_upgrades if isinstance(u, Origin)]], key=str)

    @property
    def is_resolved(self) -> bool:
        return not self.unresolved_references


@dataclass
class Trait(ModifiersMixin, ReferenceMixin, TextsMixin, Origin):
    type: Literal["Buff", "Debuff"] | None
    target_conditions: list[Effect]
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
    def unresolved_references(self) -> list[Origin]:  # override
        refs = []
        if is_unresolved_reference(self.reference):
            refs.append(self.reference)
        return sorted([*refs, *super().unresolved_references], key=str)


@dataclass
class Target(ModifiersMixin):
    is_self_target: bool
    max_range: int | None
    min_range: int | None
    line_of_sight: int | None
    conditions: list[Effect]

    @property
    def all_effects(self) -> list[Effect]:  # override
        return [*self.conditions, *super().all_effects]


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


@dataclass
class Weapon(ModifiersMixin, ReferenceMixin, TextsMixin, Origin):
    type: WeaponType
    target: Target | None
    traits: list[CategoryEffect]

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.category != "Weapons":
            raise ValueError(f"not a path to a weapon .xml: {self.path}")

    @property
    def all_effects(self) -> list[Effect]:  # override
        target_effects = self.target.all_effects if self.target else []
        return [*super().all_effects, *self.traits] + target_effects

    @property
    def unresolved_references(self) -> list[Origin]:  # override
        refs = []
        if is_unresolved_reference(self.reference):
            refs.append(self.reference)
        return sorted([*refs, *super().unresolved_references], key=str)


@dataclass
class Action(ModifiersMixin, ReferenceMixin):
    name: str
    params: list[Parameter]
    texts: TextsMixin | None
    conditions: list[Effect]
    targets: list[Target]

    @property
    def all_effects(self) -> list[Effect]:  # override
        target_effects = [e for t in self.targets for e in t.all_effects]
        return [*super().all_effects, *self.conditions, *target_effects]

    @property
    def unresolved_references(self) -> list[Origin]:  # override
        refs = []
        if is_unresolved_reference(self.reference):
            refs.append(self.reference)
        return sorted(
            [*refs, *[p.value for p in self.params if not p.is_resolved],
             *super().unresolved_references], key=str)

    @property
    def is_simple(self) -> bool:
        return all(
            not item for item in (self.params, self.modifiers, self.conditions, self.targets))


@dataclass
class Unit(ModifiersMixin, ReferenceMixin, TextsMixin, Origin):
    group_size: int
    weapons: list[CategoryEffect]
    actions: list[Action]
    traits: list[CategoryEffect]

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.category != "Units":
            raise ValueError(f"not a path to an unit .xml: {self.path}")

    @property
    def all_effects(self) -> list[Effect]:  # override
        action_effects = [e for a in self.actions for e in a.all_effects]
        return [*super().all_effects, *self.weapons, *action_effects, *self.traits]

    @property
    def unresolved_references(self) -> list[Origin]:  # override
        refs = []
        if is_unresolved_reference(self.reference):
            refs.append(self.reference)
        return sorted(
            [*refs, *[r for item in [*self.modifiers, *self.weapons, *self.actions, *self.traits]
                      for r in item.unresolved_references]], key=str)

    @property
    def elaborate_actions(self) -> list[Action]:
        return [a for a in self.actions if not a.is_simple]

    def _get_key_property(self, name: str, convert_to: Type | None = None) -> ParamValue | None:
        effect = from_iterable(self.mod_effects, lambda e: e.name == name)
        if not effect:
            return None
        param = from_iterable(effect.params, lambda p: p.type in ("base", "max"))
        value = param.value if param else None
        if convert_to and value is not None:
            return convert_to(value)
        return value

    # key properties
    @property
    def armor(self) -> int | None:
        return self._get_key_property("armor", int)

    @property
    def hitpoints(self) -> int | None:
        return self._get_key_property("hitpointsMax", int)

    @property
    def total_hitpoints(self) -> int | None:
        return self.group_size * self.hitpoints if self.hitpoints is not None else None

    @property
    def morale(self) -> int:
        return self._get_key_property("moraleMax", int)


def get_mod_effects(objects: list[Parsed | Action], most_numerous_first=False
                    ) -> OrderedDict[str, list[Parsed | Action]]:
    effects_map = defaultdict(list)
    for obj in objects:
        for e in {e.name for m in obj.modifiers for e in m.effects}:
            effects_map[e].append(obj)
    if most_numerous_first:
        new_map = [(k, v) for k, v in effects_map.items()]
        new_map.sort(key=lambda pair: len(pair[1]), reverse=True)
        return OrderedDict(new_map)
    return OrderedDict(sorted((k, v) for k, v in effects_map.items()))


def get_obj(objects: list[Parsed | Action], name: str) -> Parsed | Action | None:
    return from_iterable(objects, lambda o: o.name == name)


def get_objects(objects: list[Parsed | Action], *names: str) -> list[Parsed | Action | None]:
    d = {n: i for i, n in enumerate(names)}
    retrieved = []
    for obj in objects:
        if obj.name in names:
            retrieved.append((obj, d[obj.name]))
    for name in names:  # match number of outputs with number of inputs
        if name not in {r.name for r, _ in retrieved}:
            retrieved.append((None, d[name]))
    retrieved.sort(key=lambda r: r[1])  # preserve the input ordering
    return [r[0] for r in retrieved]
