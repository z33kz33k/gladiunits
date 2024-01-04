import re
from collections import deque
from pathlib import Path

import lxml
from lxml.etree import XMLSyntaxError, _Element as Element

from gladiunits.constants import PathLike
from gladiunits.data import Area, AreaModifier, Modifier, Origin, Parameter, Target, TextsMixin, \
    CATEGORIES, FACTIONS, Effect, CategoryEffect, ModifierType, WeaponType
from gladiunits.utils import from_iterable


class FileParser:
    @property
    def file(self) -> Path:
        return self._file

    @property
    def lines(self) -> list[str]:
        with self.file.open(encoding='utf8') as f:
            lines = [*f]
        return lines

    def __init__(self, file: PathLike) -> None:
        self._file = Path(file)
        if not self.file.is_file():
            raise FileNotFoundError(f"Not a file: '{self.file}'")


class _EntryLine:
    PATTERN_TEMPLATE = r'{}=\"(.*)\"'

    @property
    def name(self) -> str:
        return self._name

    @property
    def category(self) -> str:
        return self._category

    @property
    def name_path(self) -> Path:
        return Path(self.category) / self.name

    @property
    def value(self) -> str:
        return self._value

    @property
    def ref(self) -> Path | None:
        return self._ref

    def __init__(self, line: str, category: str) -> None:
        if not self.is_valid(line):
            raise ValueError(f"Invalid entry line: '{line}'")
        self._line, self._category = line, category
        self._ref = None
        self._name = self._parse_name()
        self._value = self._parse(self._line, "value")
        if self.value.startswith("<string name="):
            self._ref = Path(self._parse(self.value, "name", double_quotes=False))

    def __repr__(self) -> str:
        text = f"{self.__class__.__name__}(origin='{self.name_path}'"
        if self.ref:
            text += f", ref='{self.ref}')"
        else:
            text += f", value='{self.value}')"
        return text

    @classmethod
    def _parse(cls, text: str, attr: str, double_quotes=True) -> str:
        if double_quotes:
            pattern = cls.PATTERN_TEMPLATE.format(attr)
        else:
            pattern = cls.PATTERN_TEMPLATE.replace('"', "'").format(attr)
        compiled_pattern = re.compile(pattern)
        match = compiled_pattern.search(text)
        if not match:
            raise ValueError(f"Cannot parse {attr!r} in '{text}'")
        return match.group(1)

    def _parse_name(self) -> str:
        text, *_ = self._line.split("value=")
        return self._parse(text.strip(), "name")

    @staticmethod
    def is_valid(line: str) -> bool:
        return all(token in line for token in ("<entry", "name=", "value=", "/>"))


class _CoreFileParser(FileParser):
    @property
    def category(self) -> str:
        return self.file.stem

    @property
    def entry_lines(self) -> list[_EntryLine]:
        return self._entry_lines

    @property
    def plain_lines(self) -> list[_EntryLine]:
        return [line for line in self.entry_lines if not line.ref]

    @property
    def reffed_lines(self) -> list[_EntryLine]:
        return [line for line in self.entry_lines if line.ref]

    @property
    def refs(self) -> list[Path]:
        return sorted({el.ref for el in self.reffed_lines}, key=lambda r: str(r))

    def __init__(self, file: PathLike) -> None:
        super().__init__(file)
        if self.category not in CATEGORIES:
            raise ValueError(f"Unknown category: {self.category!r}")
        self._entry_lines = []
        for line in self.lines:
            if _EntryLine.is_valid(line):
                self._entry_lines.append(_EntryLine(line, self.category))


def _parse_displayed_texts() -> dict[str, str]:
    files = (
        r"xml/Core/Languages/English/Actions.xml",
        r"xml/Core/Languages/English/Buildings.xml",
        r"xml/Core/Languages/English/Features.xml",
        r"xml/Core/Languages/English/Items.xml",
        r"xml/Core/Languages/English/Traits.xml",
        r"xml/Core/Languages/English/Units.xml",
        r"xml/Core/Languages/English/Upgrades.xml",
        r"xml/Core/Languages/English/Weapons.xml",
        r"xml/Core/Languages/English/WorldParameters.xml",
    )
    parsers = [_CoreFileParser(file) for file in files]
    parsers.sort(key=lambda p: len(p.reffed_lines))

    context = {str(entry_line.name_path): entry_line.value for parser in parsers
               for entry_line in parser.plain_lines}

    stack = [entry_line for parser in parsers for entry_line in parser.reffed_lines][::-1]
    stack = deque(stack)
    while stack:
        line = stack.pop()
        found = context.get(str(line.ref))
        if found:
            context.update({str(line.name_path): found})
        else:
            stack.appendleft(line)

    return context


DISPLAYED_TEXTS = _parse_displayed_texts()


class XmlParser(FileParser):
    ROOT_TAG = None

    @property
    def root(self) -> Element:
        return self._root

    @property
    def origin(self) -> Origin:
        return self._origin

    @property
    def category(self) -> str:
        return self.origin.category

    @property
    def faction(self) -> str | None:
        return self.origin.faction

    @property
    def texts(self) -> TextsMixin:
        return self._texts

    @property
    def name(self):
        return self.texts.name

    def __init__(self, file: PathLike) -> None:
        super().__init__(file)
        self._origin = Origin(self.file)
        self._texts = self._get_texts()
        if self.file.suffix.lower() != ".xml":
            raise ValueError(f"Not a XML file: '{self.file}'")
        parser = lxml.etree.XMLParser(remove_comments=True)
        try:
            self._root: Element = lxml.etree.parse(self.file, parser).getroot()
        except XMLSyntaxError as e:
            if "Unescaped '<' not allowed" in str(e):
                with self.file.open(encoding="utf8") as f:
                    lines = [self._sanitize_line(line) for line in f][1:]

                    # sanitize_line() won't handle nested XML inside attributes
                    lines = [line for line in lines if '="<' not in line]  # ignore those
                    try:
                        self._root = lxml.etree.fromstring("".join(lines))
                    except XMLSyntaxError as e:
                        if "Unescaped '<' not allowed" in str(e):
                            truly_sanitized = []
                            for line in lines:
                                try:
                                    if "<" in line and "/>" in line:
                                        lxml.etree.fromstring(line)
                                    truly_sanitized.append(line)
                                except XMLSyntaxError:
                                    pass
                            self._root = lxml.etree.fromstring("".join(truly_sanitized), parser)
                        else:
                            raise
            else:
                raise
        self._validate_root_tag()

    @staticmethod
    def _sanitize_line(line: str) -> str:  # GPT4
        # define a function to replace < and > with { and } respectively
        def replace_brackets(match):
            return match.group().replace('<', '{').replace('>', '}')

        # use re.sub with a function as replacer
        return re.sub(r"(?<=value=\")<.*>(?=\")", replace_brackets, line)

    def collect_tags(self, root: Element | None = None) -> list[str]:
        root = self.root if root is None else root
        return sorted({el.tag for el in root.iter(Element)})

    def collect_attrs(self, root: Element | None = None) -> list[str]:
        root = self.root if root is None else root
        return sorted({attr for el in root.iter(Element) for attr in el.attrib})

    def get_immediate_tags(self, root: Element | None = None) -> list[str]:
        root = self.root if root is None else root
        immediate_tags = [el.tag for el in root]
        return sorted(t for t in immediate_tags if isinstance(t, str))

    def get_immediate_attrs(self, root: Element | None = None) -> list[str]:
        root = self.root if root is None else root
        immediate_attrs = {attr for el in root for attr in el.attrib}
        return sorted(t for t in immediate_attrs if isinstance(t, str))

    def _get_texts(self) -> TextsMixin:
        path = self._origin.category_path
        name = DISPLAYED_TEXTS[str(path)]
        desc = DISPLAYED_TEXTS.get(f"{str(path)}Description")
        flavor = DISPLAYED_TEXTS.get(f"{str(path)}Flavor")
        return TextsMixin(name, desc, flavor)

    def _validate_root_tag(self) -> None:
        if self.ROOT_TAG and self.root.tag != self.ROOT_TAG:
            raise ValueError(f"Invalid root tag: {self.root.tag!r}")

    @classmethod
    def to_effect(
            cls, element: Element,
            parent_category: str | None = None, process_sub_effects=True) -> Effect:  # recursive
        name = element.tag
        category = CategoryEffect.get_category(name) or parent_category
        params = [cls.to_param(attr, value, category) for attr, value in element.attrib.items()]

        if process_sub_effects:
            sub_effects = tuple(cls.to_effect(sub_el, category) for sub_el in element)
        else:
            sub_effects = ()
        if CategoryEffect.is_valid(name):
            return CategoryEffect(name, tuple(params), sub_effects)
        return Effect(name, tuple(params), sub_effects)

    @staticmethod
    def to_param(attr: str, value: str, category: str | None) -> Parameter:
        value_type = Parameter.TYPES.get(attr)
        value_type = value_type or str
        if attr == "name" and category:
            return Parameter("name", Origin(Path(category) / value))
        elif CategoryEffect.is_valid(attr) and value_type is Origin:
            attr_category = CategoryEffect.get_category(attr)
            return Parameter(attr, Origin(Path(attr_category) / value))
        elif attr == "icon":
            return Parameter("reference", Origin(Path(value)))
        if value_type is bool:
            value = int(value)
        elif value_type is Origin:
            value = Path(value)
        return Parameter(attr, value_type(value))

    def parse_effects(
            self, parent_element: Element,
            container_xpath="effects", process_sub_effects=True) -> tuple[Effect, ...]:
        return tuple(
            self.to_effect(sub_el, process_sub_effects=process_sub_effects)
            for el in parent_element.findall(container_xpath)
            for sub_el in el)

    def _parse_modifier(
            self, modifier_el: Element, type_: ModifierType,
            area: Area | None = None) -> Modifier | AreaModifier:
        effects = self.parse_effects(modifier_el)
        conditions = self.parse_effects(modifier_el, "conditions")
        if area:
            return AreaModifier(type_, conditions, effects, area)
        return Modifier(type_, conditions, effects)

    def parse_modifiers(self) -> tuple[Modifier | AreaModifier, ...]:
        modifier_tags = {*{mod_type.value for mod_type in ModifierType}, "areas"}
        modifiers, container_elements = [], [el for el in self.root if el.tag in modifier_tags]
        for el in container_elements:
            type_ = ModifierType.REGULAR if el.tag == "areas" else ModifierType.from_tag(el.tag)

            for sub_el in el:
                # area modifiers
                if sub_el.tag == "area":
                    area = self.parse_area(sub_el)
                    for modifier_el in sub_el.findall(".//modifier"):
                        modifiers.append(self._parse_modifier(modifier_el, type_, area))
                elif sub_el.tag == "modifier":
                    modifiers.append(self._parse_modifier(sub_el, type_))
                else:
                    for modifier_el in sub_el.findall(".//modifier"):
                        modifiers.append(self._parse_modifier(modifier_el, type_))

        return tuple(modifiers)

    @staticmethod
    def parse_area(area_el: Element) -> Area:
        radius = area_el.attrib.get("radius")
        exclude_radius = area_el.attrib.get("excludeRadius")
        return Area(
            area_el.attrib["affects"],
            int(radius) if radius is not None else None,
            int(exclude_radius) if exclude_radius is not None else None
        )

    def parse_reference(self, element: Element | None = None) -> Origin | None:
        element = self.root if element is None else element
        reference = element.attrib.get("icon")
        if not reference:
            return None
        reference = Path(reference)
        if not any(p in CATEGORIES for p in reference.parts):
            return None  # self-reference, e.g. in Traits/Missing.xml
        return Origin(reference)


class UpgradeParser(XmlParser):
    """Parser of 'Upgrades' .xml files.

    'strategyModifiers' tag and its content is used by the game AI and as such is not of
    interest for this project.
    """
    ROOT_TAG = "upgrade"
    IMMEDIATE_TAGS = ['requiredUpgrades', 'strategyModifiers']

    @property
    def tier(self) -> int:
        return self._tier

    @property
    def required_upgrades(self) -> tuple[Effect, ...]:  # TODO: parse it into actual Upgrade objects
        return self._required_upgrades

    @property
    def dlc(self) -> str | None:
        return self._dlc

    @property
    def reference(self) -> Origin | None:
        return self._reference

    def __init__(self, file: PathLike) -> None:
        super().__init__(file)
        if (self.file.parent.name not in FACTIONS
                or self.file.parent.parent.name != "Upgrades"):
            raise ValueError(f"Invalid input file: {self.file}")
        self._reference = self.parse_reference()
        self._tier = self.root.attrib.get("position")
        self._tier = int(self._tier) if self._tier else 0
        self._required_upgrades = self.parse_effects(self.root, "requiredUpgrades")
        self._dlc = self.root.attrib.get("dlc")
        if self._dlc:
            self._dlc = DISPLAYED_TEXTS.get(str(Path("WorldParameters") / self._dlc))


def parse_upgrades() -> list[UpgradeParser]:
    # required correcting a malformed original file:
    # Upgrades/Tau/RipykaVa.xml (doubly defined 'icon' attribute)
    rootdir = Path(r"xml/World/Upgrades")
    return [UpgradeParser(f) for p in rootdir.iterdir() if p.is_dir() for f in p.iterdir()]


class TraitParser(XmlParser):
    """Parser of 'Traits' .xml files.

    <modifiers> or those that end with such ending contain (multiple in theory but usually only
    one) <modifier> tags. All those that end differently (except <areas> and <targetConditions>)
    do so only to specify <area> for <modifiers> contained.
    <modifier> contains <effects> that in turn enumerates self-named tags i.e <addTrait> that
    specify (multiple in theory, but usually only one) effects.
    Effects can be conditional. This gets specified within <conditions> tag in self-named tags
    i.e. <encounter>. Those tags, contrary to effects, can get pretty complicated.

    Selected example:
    "Strikedown"
    <trait alwaysVisible="1" category="Buff">
        <onCombatOpponentModifiers>
            <modifier>
                <conditions>
                    <encounter>
                        <self>
                            <attacking/>
                        </self>
                        <opponent>
                            <noAttacking/>
                            <noTrait name="Fortification"/>
                            <noTrait name="MonstrousCreature"/>
                            <noTrait name="Vehicle"/>
                        </opponent>
                    </encounter>
                </conditions>
                <effects>
                    <addTrait name="Slowed" duration="1"/>
                </effects>
            </modifier>
        </onCombatOpponentModifiers>
    </trait>

    "Pinned"
    <trait category="Debuff">
        <modifiers>
            <modifier>
                <conditions>
                    <unit>
                        <noTrait name="Bike"/>
                        <noTrait name="Fearless"/>
                        <noTrait name="Fortification"/>
                        <noTrait name="Jetbike"/>
                        <noTrait name="Eldar/KhaineAwakened"/>
                        <noTrait name="MonstrousCreature"/>
                        <noTrait name="Tyranids/SynapseLink"/>
                        <noTrait name="Vehicle"/>
                        <noTrait name="Zealot"/>
                    </unit>
                </conditions>
                <effects>
                    <movementMax mul="-0.67"/>
                    <rangedAccuracy mul="-0.17"/>
                    <rangedDamageReduction add="0.17"/>
                </effects>
            </modifier>
            <modifier visible="0">
                <conditions>
                    <unit>
                        <noTrait name="Bike"/>
                        <noTrait name="Fearless"/>
                        <noTrait name="Fortification"/>
                        <noTrait name="Jetbike"/>
                        <noTrait name="Eldar/KhaineAwakened"/>
                        <noTrait name="MonstrousCreature"/>
                        <noTrait name="Tyranids/SynapseLink"/>
                        <noTrait name="Vehicle"/>
                        <noTrait name="Zealot"/>
                    </unit>
                </conditions>
                <effects>
                    <preventOverwatch add="1"/>
                </effects>
            </modifier>
        </modifiers>
    </trait>
    """
    ROOT_TAG = "trait"
    IMMEDIATE_TAGS = [
        'areas',
        'modifiers',
        'onCombatOpponentModifiers',
        'onCombatSelfModifiers',
        'onEnemyKilledOpponentTileModifiers',
        'onEnemyKilledSelf',
        'onEnemyKilledSelfModifiers',
        'onTileEnteredModifiers',
        'onTraitAddedModifiers',
        'onTraitRemovedModifiers',
        'onTransportDisembarked',
        'onTransportEmbarked',
        'onUnitDisappeared',
        'onUnitDisappearedModifiers',
        'onUnitDisembarked',
        'opponentModifiers',
        'perTurnModifiers',
        'targetConditions'
    ]
    EFFECTS = [
        'accuracy',
        'actionPointsMax',
        'addFeature',
        'addRandomBoonOfChaos',
        'addTrait',
        'addUnit',
        'additionalMembersHit',
        'armor',
        'armorPenetration',
        'attacks',
        'attacksTaken',
        'biomassUpkeep',
        'boonOfChaosChance',
        'cargoSlotsRequired',
        'circumstanceMeleeDamage',
        'cityDamageReduction',
        'cityRadius',
        'consumedMovement',
        'damage',
        'damageFromHitpoints',
        'damageReturnFactor',
        'damageSelfFactor',
        'damageTaken',
        'deathExperience',
        'deathMorale',
        'duplicateTypeCost',
        'energy',
        'energyFromAdjacentBuildings',
        'energyFromExperienceValueFactor',
        'energyUpkeep',
        'feelNoPainDamageReduction',
        'flatResourcesFromFeatures',
        'food',
        'foodFromAdjacentBuildings',
        'foodUpkeep',
        'growth',
        'healingRate',
        'heroDamageReduction',
        'hitpoints',
        'hitpointsFactorFromMax',
        'hitpointsMax',
        'ignoreLineOfSight',
        'ignoreZoneOfControl',
        'influence',
        'influenceFromAdjacentBuildings',
        'influencePerCombatFromUpkeepFactor',
        'influencePerExperience',
        'influencePerKillValue',
        'influenceUpkeep',
        'invulnerableDamageReduction',
        'lifeStealFactor',
        'lifeStealRadius',
        'loyalty',
        'loyaltyFromAdjacentBuildings',
        'loyaltyFromUtopiaType',
        'loyaltyPerCity',
        'meleeAccuracy',
        'meleeArmorPenetration',
        'meleeAttacks',
        'meleeDamage',
        'meleeDamageReduction',
        'meleeOverwatch',
        'minDamageFromHitpointsFraction',
        'monolithicBuildingsBonus',
        'monolithicBuildingsPenalty',
        'morale',
        'moraleLossFactor',
        'moraleLossFactorPerAllyInArea',
        'moraleMax',
        'moraleRegeneration',
        'movement',
        'movementCost',
        'movementMax',
        'opponentRangedAccuracy',
        'ore',
        'oreFromAdjacentBuildings',
        'orePerKillValue',
        'oreUpkeep',
        'populationLimit',
        'preventEnemyOverwatch',
        'preventOverwatch',
        'processUse',
        'production',
        'productionFromAdjacentBuildings',
        'rangeMax',
        'rangedAccuracy',
        'rangedArmorPenetration',
        'rangedAttacks',
        'rangedDamageReduction',
        'rangedDamageReductionBypass',
        'rangedInvulnerableDamageReduction',
        'removeFeature',
        'removeTrait',
        'removeUnit',
        'requisitions',
        'requisitionsUpkeep',
        'research',
        'researchCost',
        'researchFromAdjacentBuildings',
        'researchPerExperience',
        'researchPerKillValue',
        'sight',
        'supportSystemSlots',
        'typeLimit',
        'weaponDamage',
        'witchfireDamageReduction'
    ]
    CONDITIONS = [
        'building',
        'encounter',
        'encounterRange',
        'player',
        'supportingFire',
        'tile',
        'unit',
        'weapon'
    ]

    @property
    def type(self) -> str | None:
        return self._type

    @property
    def modifiers(self) -> tuple[Modifier | AreaModifier, ...]:
        return self._modifiers

    @property
    def target_conditions(self) -> tuple[Effect, ...]:
        return self._target_conditions

    @property
    def max_rank(self) -> int | None:
        return self._max_rank

    @property
    def stacking(self) -> bool | None:
        return self._stacking

    @property
    def reference(self) -> Origin | None:
        return self._reference

    def __init__(self, file: PathLike) -> None:
        super().__init__(file)
        if (self.file.parent.name != "Traits"
                and self.file.parent.parent.name != "Traits"):
            raise ValueError(f"Invalid input file: {self.file}")
        self._reference = self.parse_reference()
        self._type = self.root.attrib.get("category")
        self._modifiers = self.parse_modifiers()
        self._target_conditions = self._parse_target_conditions()
        self._max_rank = self.root.attrib.get("rankMax")
        if self._max_rank:
            self._max_rank = int(self._max_rank)
        self._stacking = self.root.attrib.get("stacking")
        if self._stacking:
            self._stacking = True if self._stacking == "1" else False

    def _parse_target_conditions(self) -> tuple[Effect, ...]:
        conditions = []
        target_conditions_el = self.root.find("targetConditions")
        if target_conditions_el is not None:
            for sub_el in target_conditions_el:
                conditions.append(self.to_effect(sub_el))
        return tuple(conditions)


def parse_traits() -> list[TraitParser]:
    # required correcting a malformed original file:
    # Traits/ChaosSpaceMarines/RunesOfTheBloodGod.xml (missing whitespace)
    rootdir = Path(r"xml/World/Traits")
    flat = [f for f in rootdir.iterdir() if f.is_file()]
    nested = [f for p in rootdir.iterdir() if p.is_dir() for f in p.iterdir()]
    traits = []
    for f in [*flat, *nested]:
        try:
            traits.append(TraitParser(f))
        except XMLSyntaxError:
            pass  # Traits/OrkoidFungusFood.xml (the body commented out)
    return traits


class WeaponParser(XmlParser):
    ROOT_TAG = "weapon"
    IMMEDIATE_TAGS = ['model', 'modifiers', 'target', 'traits']
    CONDITIONS = ['encounter']

    @property
    def modifiers(self) -> tuple[Modifier, ...]:
        return self._modifiers

    @property
    def type(self) -> WeaponType:
        return self._type

    @property
    def target(self) -> Target | None:
        return self._target

    @property
    def traits(self) -> tuple[Effect, ...]:
        return self._traits

    @property
    def reference(self) -> Origin | None:
        return self._reference

    def __init__(self, file: PathLike) -> None:
        super().__init__(file)
        if self.file.parent.name != "Weapons":
            raise ValueError(f"Invalid input file: {self.file}")
        self._reference = self.parse_reference()
        self._modifiers = self.parse_modifiers()
        self._type = self._parse_type()
        self._target = self.root.find("target")
        if self._target is not None:
            max_range = self._target.attrib["rangeMax"]
            conditions = self.parse_effects(self._target, "conditions")
            self._target = Target(max_range, conditions)
        self._traits = self.parse_effects(self.root, "traits")

    def _parse_type(self) -> WeaponType:
        model_el = self.root.find("model")
        if model_el is None:
            return WeaponType.REGULAR
        type_el = from_iterable(model_el, lambda sub_el: "weapon" in sub_el.tag.lower())
        if type_el is None:
            return WeaponType.REGULAR
        return WeaponType.from_tag(type_el.tag)


def parse_weapons() -> list[WeaponParser]:
    rootdir = Path(r"xml/World/Weapons")
    return [WeaponParser(f) for f in rootdir.iterdir()]


# TODO


class UnitParser(XmlParser):
    ROOT_TAG = "unit"
    IMMEDIATE_TAGS = []
    CONDITIONS = []

    @property
    def group_size(self) -> int:
        return self._group_size

    @property
    def modifiers(self) -> tuple[Modifier, ...]:
        return self._modifiers

    @property
    def weapons(self) -> tuple[Effect, ...]:
        return self._weapons

    @property
    def actions(self) -> tuple[Effect, ...]:
        return self._actions

    @property
    def traits(self) -> tuple[Effect, ...]:
        return self._traits

    @property
    def reference(self) -> Origin | None:
        return self._reference

    def __init__(self, file: PathLike) -> None:
        super().__init__(file)
        if self.file.parent.name != "Units":
            raise ValueError(f"Invalid input file: {self.file}")
        self._reference = self.parse_reference()
        group_el = self.root.find("group")
        if group_el is None:
            raise ValueError(f"no group element: {self.file}")
        self._group_size = int(group_el.attrib["size"])
        self._modifiers = self.parse_modifiers()
        self._weapons = self.parse_effects(self.root, "weapons", process_sub_effects=False)
        self._actions = self.parse_effects(self.root, "actions", process_sub_effects=False)
        self._traits = self.parse_effects(self.root, "traits")



