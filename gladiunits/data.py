"""

    gladiunits.data.py
    ~~~~~~~~~~~~~~~~~~
    Data structures.

    @author: z33k

"""
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field, fields, is_dataclass
from enum import Enum, auto
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar, Literal, Type, TypeAlias, Union

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
    'Buildings',
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

_CIRCULAR_REFS = {
    "Units/ChaosSpaceMarines/MasterOfPossession",
    "Units/Eldar/FirePrism",
    "Units/Neutral/Artefacts/Damage",
    "Units/Neutral/Artefacts/Healing",
    "Units/Neutral/Artefacts/Hitpoints",
    "Units/Neutral/Artefacts/Loyalty",
    "Units/Neutral/Artefacts/Movement",
    "Units/Neutral/Artefacts/Sight",
    "Units/Neutral/CatachanDevilLair",
    "Units/Neutral/Psychneuein",
    "Units/SpaceMarines/Hunter",
    "Units/SpaceMarines/Predator",
    "Units/SpaceMarines/ThunderfireCannon",
    "Units/SpaceMarines/Vindicator",
    "Units/SpaceMarines/Whirlwind",
    "Traits/ChaosSpaceMarines/GiftOfMutation",
    "Traits/ChaosSpaceMarines/Bloated",
    "Traits/Tau/TargetAcquired",
    'Buildings/AdeptusMechanicus/Construction',
    'Buildings/AstraMilitarum/Construction',
    'Buildings/ChaosSpaceMarines/Construction',
    'Buildings/Drukhari/Construction',
    'Buildings/Eldar/Construction',
    'Buildings/Necrons/Construction',
    'Buildings/Neutral/Construction',
    'Buildings/Orks/Construction',
    'Buildings/SistersOfBattle/Construction',
    'Buildings/SpaceMarines/Construction',
    'Buildings/Tau/Construction',
    'Buildings/Tyranids/Construction',
}


@dataclass(frozen=True)
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

    def matches(self, category_path: str) -> bool:
        return str(self.category_path) == category_path


@dataclass(frozen=True)
class TextsMixin:
    name: str
    description: str | None
    flavor: str | None


Data: TypeAlias = Union["UpgradeWrapper", "Upgrade", "Trait", "Weapon", "Unit"]
ParamValue: TypeAlias = (Data | tuple[Data, ...] | Origin | tuple[Origin, ...] | float | int |
                         str | bool)


@dataclass(frozen=True)
class ReferenceMixin:
    reference: Data | Origin | None

    @property
    def reffed_category(self) -> str | None:
        if not isinstance(self.reference, Origin):
            return None
        return self.reference.category


def is_unresolved_ref(value: Any) -> bool:
    # needs an explicit type check
    if type(value) is not Origin:
        return False
    if str(value.category_path) in _CIRCULAR_REFS:
        return False
    return value.category in PARSED_CATEGORIES


# recursive
def collect_unresolved_refs(
        obj: Any, crumbs="",
        collected: dict[str, Origin] = None) -> dict[str, Origin]:
    crumbs = crumbs.split(".") if crumbs else []
    collected = collected or {}

    if is_dataclass(obj):
        for f in fields(obj):
            if f.name == "reference":
                continue
            crumbs.append(f.name)
            value = getattr(obj, f.name)

            if isinstance(value, (tuple, list)):
                for i, item in enumerate(value):
                    crumbs.append(str(i))
                    if is_unresolved_ref(item):
                        collected[".".join(crumbs)] = item
                    else:
                        collected = collect_unresolved_refs(item, ".".join(crumbs), collected)
                    # trim crumbs
                    crumbs = crumbs[:-1]

            elif is_unresolved_ref(value):
                collected[".".join(crumbs)] = value

            # trim crumbs
            crumbs = crumbs[:-1]

    return collected


@dataclass(frozen=True)
class Parameter:
    TYPES: ClassVar[dict[str, Any]] = {
        'action': Origin,
        'add': float,
        'addMax': float,
        'addMin': float,
        'base': float,
        'beginOnDisappear': bool,
        'building': Origin,
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
        'feature': Origin,
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
    def unresolved_refs(self) -> OrderedDict[str, Origin]:
        return OrderedDict(sorted((k, v) for k, v in collect_unresolved_refs(self).items()))

    @property
    def is_resolved(self) -> bool:
        return not self.unresolved_refs


@dataclass(frozen=True)
class Effect:
    name: str
    params: tuple[Parameter, ...]
    sub_effects: tuple["Effect", ...]

    @property
    def all_params(self) -> list[Parameter]:
        return [*self.params, *[p for e in self.sub_effects for p in e.all_params]]

    @property
    def unresolved_refs(self) -> OrderedDict[str, Origin]:
        return OrderedDict(sorted((k, v) for k, v in collect_unresolved_refs(self).items()))

    @property
    def is_resolved(self) -> bool:
        return not self.unresolved_refs

    @property
    def is_negative(self) -> bool:
        return len(self.name) > 3 and self.name.startswith("no") and self.name[2].isupper()

    @property
    def is_heal(self) -> bool:
        heal_param = from_iterable(
            self.params, lambda p: p.type in ("add", "addMin", "addMax"))
        return self.name == "hitpoints" and heal_param and heal_param.value > 0


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

    def applies_to_cat_and_trait(self, category: str, trait: str) -> bool:
        if self.category != category:
            return False
        for se in self.sub_effects:
            if se.name == "trait":
                for p in se.params:
                    if isinstance(p.value, Trait) and p.value.matches(trait):
                        return True
        return False

    def applies_to_cat_and_no_trait(self, category: str, trait: str) -> bool:
        if self.category != category:
            return False
        for se in self.sub_effects:
            if se.name == "noTrait":
                for p in se.params:
                    if isinstance(p.value, Trait) and p.value.matches(trait):
                        return True
        return False

    @property
    def applies_to_vehicles(self) -> bool:
        return self.applies_to_cat_and_trait("Units", "Traits/Vehicle")

    @property
    def applies_to_fortifications(self) -> bool:
        return self.applies_to_cat_and_trait("Units", "Traits/Fortification")

    @property
    def applies_to_non_vehicles(self) -> bool:
        return self.applies_to_cat_and_no_trait("Units", "Traits/Vehicle")

    @property
    def applies_to_non_fortifications(self) -> bool:
        return self.applies_to_cat_and_no_trait("Units", "Traits/Fortification")


@dataclass(frozen=True)
class Upgrade(ReferenceMixin, TextsMixin, Origin):
    tier: int | None
    dlc: str | None
    required_upgrades: tuple[Union["Upgrade",  Origin], ...] = field(default=())

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.category != "Upgrades":
            raise ValueError(f"not a path to an upgrade .xml: {self.path}")
        if self.tier and self.tier not in range(1, 11):
            raise ValueError("tier must be an integer between 1 and 10")

    def __hash__(self) -> int:
        return hash(str(self.path))

    def __eq__(self, other: "Upgrade") -> bool:
        return str(self.path) == str(other.path)

    @property
    def unresolved_refs(self) -> OrderedDict[str, Origin]:
        return OrderedDict(sorted((k, v) for k, v in collect_unresolved_refs(self).items()))

    @property
    def is_resolved(self) -> bool:
        return not self.unresolved_refs


@dataclass
class UpgradeWrapper:
    upgrade: Upgrade
    required_upgrades: list[Union["Upgrade",  Origin]]

    @property
    def unresolved_refs(self) -> OrderedDict[str, Origin]:
        return OrderedDict(sorted((k, v) for k, v in collect_unresolved_refs(self).items()))

    @property
    def is_resolved(self) -> bool:
        return not self.unresolved_refs

    def to_upgrade(self) -> Upgrade:
        return Upgrade(
            path=self.upgrade.path,
            name=self.upgrade.name,
            description=self.upgrade.description,
            flavor=self.upgrade.flavor,
            reference=self.upgrade.reference,
            tier=self.upgrade.tier,
            dlc=self.upgrade.dlc,
            required_upgrades=tuple(u for u in self.required_upgrades)
        )


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
class RequiredUpgradeMixin:
    required_upgrade: Upgrade | None

    @property
    def is_basic(self) -> bool:
        return not self.required_upgrade

    @property
    def tier(self) -> int | None:
        if not self.required_upgrade:
            return None
        return self.required_upgrade.tier


@dataclass(frozen=True)
class Modifier(RequiredUpgradeMixin):
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
    def unresolved_refs(self) -> OrderedDict[str, Origin]:
        return OrderedDict(sorted((k, v) for k, v in collect_unresolved_refs(self).items()))

    @property
    def is_resolved(self) -> bool:
        return not self.unresolved_refs

    @property
    def is_heal(self) -> bool:
        return any(e.is_heal for e in self.effects)


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

    @property
    def mod_effects(self) -> list[Effect]:
        return [e for m in self.modifiers for e in m.effects]

    @property
    def unresolved_refs(self) -> OrderedDict[str, Origin]:
        return OrderedDict(sorted((k, v) for k, v in collect_unresolved_refs(self).items()))

    @property
    def is_resolved(self) -> bool:
        return not self.unresolved_refs

    @property
    def augmentations(self) -> tuple[Upgrade, ...]:
        return tuple(m.required_upgrade for m in self.modifiers if m.required_upgrade)

    @property
    def is_augmentable(self) -> bool:
        return bool(self.augmentations)


# Traits are different than Actions and Modifiers (other XML tags that can sometimes possess
# a 'requiredUpgrade' attribute) as they come in two breeds: 1) one that doesn't ever possess
# 'requiredUpgrade' (root element of Trait .xml files) and 2) one that sometimes does (a
# sub-element of Weapon and Unit .xml files), but nevertheless they are treated similarly and
# parsed as one object with an attribute equal to None in cases where there was no
# `requiredUpgrade` in a source file
@dataclass(frozen=True)
class Trait(RequiredUpgradeMixin, ModifiersMixin, ReferenceMixin, TextsMixin, Origin):
    type: Literal["Buff", "Debuff"] | None
    target_conditions: tuple[Effect, ...]
    max_rank: int | None
    stacking: bool | None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.category != "Traits":
            raise ValueError(f"not a path to a trait .xml: {self.path}")

    def __hash__(self) -> int:
        return hash(str(self.path))

    def __eq__(self, other: "Upgrade") -> bool:
        return str(self.path) == str(other.path)

    @property
    def all_effects(self) -> list[Effect]:  # override
        return [*self.target_conditions, *super().all_effects]

    @property
    def is_faction_specific(self) -> bool:  # makes sense only for Traits
        return self.faction is not None

    @classmethod
    def with_upgrade(cls, trait: "Trait", required_upgrade: Upgrade) -> "Trait":
        return cls(
            path=trait.path,
            name=trait.name,
            description=trait.description,
            flavor=trait.flavor,
            reference=trait.reference,
            modifiers=trait.modifiers,
            type=trait.type,
            target_conditions=trait.target_conditions,
            max_rank=trait.max_rank,
            stacking=trait.stacking,
            required_upgrade=required_upgrade,
        )


@dataclass(frozen=True)
class Target(ModifiersMixin):
    is_self_target: bool
    max_range: int | None
    min_range: int | None
    line_of_sight: int | None
    conditions: tuple[Effect, ...]

    @property
    def all_effects(self) -> list[Effect]:  # override
        return [*self.conditions, *super().all_effects]

    @property
    def is_heal(self) -> bool:
        return any(m.is_heal for m in self.modifiers)

    @property
    def is_organic_only_heal(self) -> bool:
        return self.is_heal and any(
            c.applies_to_non_vehicles and c.applies_to_non_fortifications
            for c in self.conditions if isinstance(c, CategoryEffect))

    @property
    def is_mechanical_only_heal(self) -> bool:
        return self.is_heal and any(
            c.applies_to_vehicles and c.applies_to_fortifications
            for c in self.conditions if isinstance(c, CategoryEffect))


@dataclass(frozen=True)
class TraitsMixin:
    traits: tuple[Trait, ...]

    @property
    def basic_traits(self) -> list[Trait]:
        return [t for t in self.traits if t.is_basic]

    @property
    def upgrade_requiring_traits(self) -> list[Trait]:
        return [t for t in self.traits if not t.is_basic]

    @property
    def augmentable_traits(self) -> list[Trait]:
        return [t for t in self.traits if t.is_augmentable]

    def has_trait(self, trait: str, basic=True) -> bool:
        if not trait:
            return False
        if not trait.startswith("Traits/"):
            trait = trait[0].upper() + trait[1:]
            trait = f"Traits/{trait}"
        traits = self.basic_traits if basic else self.traits
        return any(t.matches(trait) for t in traits)


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
class Weapon(TraitsMixin, RequiredUpgradeMixin, ModifiersMixin, ReferenceMixin, TextsMixin, Origin):
    type: WeaponType
    target: Target | None
    count: int | None  # defined in Units XMLs
    enabled: bool | None  # defined in Units XMLs

    @classmethod
    def with_additional_data(
            cls, weapon: "Weapon", count: int, enabled: bool,
            required_upgrade: Upgrade | None = None) -> "Weapon":
        return cls(
            path=weapon.path,
            name=weapon.name,
            description=weapon.description,
            flavor=weapon.flavor,
            reference=weapon.reference,
            modifiers=weapon.modifiers,
            type=weapon.type,
            target=weapon.target,
            traits=weapon.traits,
            count=count,
            enabled=enabled,
            required_upgrade=required_upgrade
        )

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.category != "Weapons":
            raise ValueError(f"not a path to a weapon .xml: {self.path}")

    def __hash__(self) -> int:
        return hash(str(self.path))

    def __eq__(self, other: "Upgrade") -> bool:
        return str(self.path) == str(other.path)

    @property
    def all_effects(self) -> list[Effect]:  # override
        target_effects = self.target.all_effects if self.target else []
        return [*super().all_effects, *self.traits] + target_effects


# Some actions can be available only after an upgrade (and then, they have 'requiredUpgrade'
# defined as one of its attributes in XML) or can be available from the start but only augmented
# via upgrade (and then one of its Modifiers has a 'requiredUpgrade' defined as one of its
# attributes in XML)
@dataclass(frozen=True)
class Action(RequiredUpgradeMixin, ModifiersMixin, ReferenceMixin):
    name: str
    params: tuple[Parameter, ...]
    texts: TextsMixin | None
    conditions: tuple[Effect, ...]
    targets: tuple[Target, ...]
    required_weapons: tuple[Weapon, ...]  # can be multiple, e.g. <cycleWeapon> case

    def __hash__(self) -> int:
        return hash((self.name, self.texts))

    def __eq__(self, other: "Action") -> bool:
        return (self.name, self.texts) == (other.name, other.texts)

    @property
    def all_effects(self) -> list[Effect]:  # override
        target_effects = [e for t in self.targets for e in t.all_effects]
        return [*super().all_effects, *self.conditions, *target_effects]

    @property
    def is_simple(self) -> bool:
        return all(
            not item for item in (self.params, self.modifiers, self.conditions, self.targets))

    @property
    def is_elaborate(self) -> bool:
        return not self.is_simple

    @property
    def is_heal(self) -> bool:
        return any(t.is_heal for t in self.targets)

    @property
    def is_self_heal(self) -> bool:
        healing_targets = [t for t in self.targets if t.is_heal]
        return any(t.is_self_target for t in healing_targets)

    @property
    def is_organic_only_heal(self) -> bool:
        for t in self.targets:
            if t.is_organic_only_heal:
                return True
        return False

    @property
    def is_mechanical_only_heal(self) -> bool:
        for t in self.targets:
            if t.is_mechanical_only_heal:
                return True
        return False

    @property
    def produced_unit(self) -> Union["Unit", Origin, None]:
        if self.name == "produceUnit":
            for p in self.params:
                if p.type == "unit":
                    return p.value
        if self.name.startswith("deploy"):
            for p in self.params:
                if p.type == "unitType":
                    return p.value
        if self.reference and self.reference.category == "Units" and "Artefacts" not in str(
                self.reference.category_path):
            return self.reference
        return None


@dataclass(frozen=True)
class ActionsMixin:
    actions: tuple[Action, ...]

    @property
    def simple_actions(self) -> list[Action]:
        return [a for a in self.actions if a.is_simple]

    @property
    def elaborate_actions(self) -> list[Action]:
        return [a for a in self.actions if a.is_elaborate]

    @property
    def basic_actions(self) -> list[Action]:  # no upgrade required
        return [a for a in self.elaborate_actions if a.is_basic]

    @property
    def upgrade_requiring_actions(self) -> list[Action]:
        return [a for a in self.elaborate_actions if not a.is_basic]

    @property
    def weapon_requiring_actions(self) -> list[Action]:
        return [a for a in self.elaborate_actions if a.required_weapons]

    @property
    def augmentable_actions(self) -> list[Action]:
        return [a for a in self.elaborate_actions if a.is_augmentable]

    def has_action(self, action: str, elaborate=True) -> bool:
        actions = self.elaborate_actions if elaborate else self.actions
        return any(a.name == action for a in actions)


@dataclass(frozen=True)
class Unit(RequiredUpgradeMixin, ActionsMixin, TraitsMixin, ModifiersMixin, ReferenceMixin,
           TextsMixin, Origin):
    group_size: int
    weapons: tuple[Weapon, ...]
    dlc: str | None
    producer: Union["Unit", "Building", None]

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.category != "Units":
            raise ValueError(f"not a path to an unit .xml: {self.path}")

    def __hash__(self) -> int:
        return hash(str(self.path))

    def __eq__(self, other: "Upgrade") -> bool:
        return str(self.path) == str(other.path)

    @classmethod
    def with_producer(
            cls, unit: "Unit", producer: Union["Unit", "Building"]) -> "Unit":
        return cls(
            path=unit.path,
            name=unit.name,
            description=unit.description,
            flavor=unit.flavor,
            reference=unit.reference,
            modifiers=unit.modifiers,
            group_size=unit.group_size,
            weapons=unit.weapons,
            actions=unit.actions,
            traits=unit.traits,
            required_upgrade=unit.required_upgrade,
            dlc=unit.dlc,
            producer=producer
        )

    @property
    def tier(self) -> int | None:  # override
        tier = super().tier
        if tier is None:
            if isinstance(self.producer, Building) and self.producer.required_upgrade:
                tier = self.producer.required_upgrade.tier
            elif isinstance(self.producer, Unit):
                tier = self.producer.tier
        if (tier is None
                and not self.is_artefact
                and not self.is_fortification
                and self.faction != "Neutral"):
            return 0
        return tier

    @property
    def cost(self) -> dict[str, float]:
        return self._get_cost()

    @property
    def upkeep(self) -> dict[str, float]:
        return self._get_cost(upkeep=True)

    @property
    def all_effects(self) -> list[Effect]:  # override
        weapon_effects = [e for w in self.weapons for e in w.all_effects]
        action_effects = [e for a in self.actions for e in a.all_effects]
        trait_effects = [e for t in self.traits for e in t.all_effects]
        return [*super().all_effects, *weapon_effects, *action_effects, *trait_effects]

    @lru_cache()
    def _get_key_property(self, name: str, convert_to: Type = None) -> ParamValue | None:
        for effect in [e for e in self.mod_effects if len(e.params) == 1]:
            if effect.name == name:
                param = effect.params[0]
                return param.value if convert_to is None else convert_to(param.value)
        return None

    @lru_cache()
    def _get_cost(self, upkeep=False) -> dict[str, float]:
        suffix = "Upkeep" if upkeep else "Cost"
        cost_effects = [e for e in self.mod_effects
                        if len(e.params) == 1 and e.name.endswith(suffix)]
        cost = {}
        for effect in cost_effects:
            cost[effect.name.replace(suffix, "")] = float(effect.params[0].value)
        cost["total"] = sum(cost.values())
        return cost

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

    # weapons
    @property
    def basic_weapons(self) -> list[Weapon]:
        return [w for w in self.weapons if w.is_basic]

    @property
    def upgrade_requiring_weapons(self) -> list[Weapon]:
        return [w for w in self.weapons if not w.is_basic]

    @property
    def augmentable_weapons(self) -> list[Weapon]:
        return [w for w in self.weapons if w.is_augmentable]

    # trait-based classifiers
    @property
    def is_artefact(self) -> bool:
        return self.has_trait("Artefact")

    @property
    def is_fortification(self) -> bool:  # most are transports too (hold cargo)
        return self.has_trait("Fortification")

    @property
    def is_vehicle(self) -> bool:
        return self.has_trait("Vehicle")

    @property
    def is_hero(self) -> bool:
        return self.has_trait("Hero")

    @property
    def is_monstrous_creature(self) -> bool:
        return self.has_trait("MonstrousCreature")

    @property
    def is_infantry(self) -> bool:  # based on Painboy healing
        return not self.is_fortification and not self.is_vehicle and not self.is_monstrous_creature

    @property
    def is_tank(self) -> bool:  # subset of vehicles
        return self.has_trait("Tank")

    @property
    def is_transport(self) -> bool:  # most are vehicles (apart from 2 monstrous creatures)
        return self.has_trait("Transport")

    @property
    def is_walker(self) -> bool:  # subset of vehicles
        return self.has_trait("Walker")

    @property
    def is_bike(self) -> bool:  # only two
        return self.has_trait("Bike")

    @property
    def is_jetbike(self) -> bool:
        return self.has_trait("Jetbike")

    @property
    def is_jetpack_user(self) -> bool:
        return self.has_trait("JetPack")

    @property
    def is_flyer(self) -> bool:  # subset of vehicles
        return self.has_trait("Flyer")

    @property
    def is_skimmer(self) -> bool:
        return self.has_trait("Skimmer")

    @property
    def is_open_topped(self) -> bool:  # subset of vehicles
        return self.has_trait("OpenTopped")

    @property
    def is_gargantuan(self) -> bool:
        return self.has_trait("Gargantuan")

    @property
    def is_psyker(self) -> bool:
        return self.has_trait("Psyker")

    @property
    def is_daemon(self) -> bool:
        return self.has_trait("Daemon")

    @property
    def is_amphibious(self) -> bool:  # only one (Chimera)
        return self.has_trait("Amphibious")

    @property
    def is_fearless(self) -> bool:
        return self.has_trait("Fearless")

    @property
    def is_relentless(self) -> bool:
        return self.has_trait("Relentless")

    @property
    def is_zealot(self) -> bool:
        return self.has_trait("Zealot")

    @property
    def is_mechanical(self) -> bool:  # important for healing
        return self.is_vehicle or self.is_fortification

    @property
    def is_organic(self) -> bool:  # important for healing
        return not self.is_mechanical

    # action-based classifiers
    @property
    def is_jumper(self) -> bool:
        return self.has_action("jumpPack")

    @property
    def is_scout(self) -> bool:
        return self.has_action("scout")

    @property
    def is_tile_cleaner(self) -> bool:
        return self.has_action("clearTileUnitAbility")

    @property
    def is_healer(self) -> bool:
        return any(a.is_heal for a in self.elaborate_actions)

    @property
    def is_self_healer(self) -> bool:
        return any(a.is_self_heal for a in self.elaborate_actions)

    @property
    def is_others_healer(self) -> bool:
        return self.is_healer and not self.is_self_healer

    @property
    def is_organic_only_healer(self) -> bool:
        return any(a.is_organic_only_heal for a in self.elaborate_actions)

    @property
    def is_mechanical_only_healer(self) -> bool:
        return any(a.is_mechanical_only_heal for a in self.elaborate_actions)

    @property
    def is_settler(self) -> bool:
        return self.has_action("foundCity")

    @property
    def is_skirmisher(self) -> bool:
        return self.has_action("jink") and self.has_action("turboBoost")

    @property
    def is_grenadier(self) -> bool:
        return self.has_action("throwGrenade")


@dataclass(frozen=True)
class Building(RequiredUpgradeMixin, TraitsMixin, ActionsMixin, ModifiersMixin, TextsMixin, Origin):

    def __hash__(self) -> int:
        return hash(str(self.path))

    def __eq__(self, other: "Upgrade") -> bool:
        return str(self.path) == str(other.path)

    @property
    def _produce_unit_actions(self) -> list[Action]:
        return [a for a in self.actions if a.name == "produceUnit"]

    @property
    def produced_units(self) -> list[Unit]:
        if not self._produce_unit_actions:
            return []
        return [p.value for a in self._produce_unit_actions for p in a.params if p.type == "unit"]

    def get_matching_action(self, unit: "Unit") -> Action | None:
        for action in self._produce_unit_actions:
            for param in action.params:
                if param.value.category_path == unit.category_path:
                    return action
        return None


def get_mod_effects(objects: list[Data | Action], most_numerous_first=False
                    ) -> OrderedDict[str, list[Data | Action]]:
    effects_map = defaultdict(list)
    for obj in objects:
        for e in {e.name for m in obj.modifiers for e in m.effects}:
            effects_map[e].append(obj)
    if most_numerous_first:
        new_map = [(k, v) for k, v in effects_map.items()]
        new_map.sort(key=lambda pair: len(pair[1]), reverse=True)
        return OrderedDict(new_map)
    return OrderedDict(sorted((k, v) for k, v in effects_map.items()))


def get_obj(objects: list[Data | Action], name: str) -> Data | Action | None:
    return from_iterable(objects, lambda o: o.name == name)


def get_objects(objects: list[Data | Action], *names: str) -> list[Data | Action | None]:
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
