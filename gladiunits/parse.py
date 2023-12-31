import re
from collections import deque
from pathlib import Path
from typing import Dict, List, Tuple

import lxml
from lxml.etree import XMLSyntaxError, _Element as Element

from gladiunits.constants import PathLike
from gladiunits.data import Area, AreaModifier, Modifier, Origin, Parameter, TextsMixin, CATEGORIES, \
    FACTIONS, Effect, ModifierType


class FileParser:
    @property
    def file(self) -> Path:
        return self._file

    @property
    def lines(self) -> List[str]:
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
    def entry_lines(self) -> List[_EntryLine]:
        return self._entry_lines

    @property
    def plain_lines(self) -> List[_EntryLine]:
        return [line for line in self.entry_lines if not line.ref]

    @property
    def reffed_lines(self) -> List[_EntryLine]:
        return [line for line in self.entry_lines if line.ref]

    @property
    def refs(self) -> List[Path]:
        return sorted({el.ref for el in self.reffed_lines}, key=lambda r: str(r))

    def __init__(self, file: PathLike) -> None:
        super().__init__(file)
        if self.category not in CATEGORIES:
            raise ValueError(f"Unknown category: {self.category!r}")
        self._entry_lines = []
        for line in self.lines:
            if _EntryLine.is_valid(line):
                self._entry_lines.append(_EntryLine(line, self.category))


def _parse_displayed_texts() -> Dict[str, str]:
    files = (
        r"xml/Core/Languages/English/Actions.xml",
        r"xml/Core/Languages/English/Buildings.xml",
        r"xml/Core/Languages/English/Features.xml",
        r"xml/Core/Languages/English/Items.xml",
        r"xml/Core/Languages/English/Traits.xml",
        r"xml/Core/Languages/English/Units.xml",
        r"xml/Core/Languages/English/Upgrades.xml",
        r"xml/Core/Languages/English/Weapons.xml",
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

    def collect_tags(self, root: Element | None = None) -> List[str]:
        root = self.root if root is None else root
        return sorted({el.tag for el in root.iter(Element)})

    def collect_attrs(self, root: Element | None = None) -> List[str]:
        root = self.root if root is None else root
        return sorted({attr for el in root.iter(Element) for attr in el.attrib})

    def get_immediate_tags(self, root: Element | None = None) -> List[str]:
        root = self.root if root is None else root
        immediate_tags = [el.tag for el in root]
        return sorted(t for t in immediate_tags if isinstance(t, str))

    def get_immediate_attrs(self, root: Element | None = None) -> List[str]:
        root = self.root if root is None else root
        immediate_attrs = {attr for el in root for attr in el.attrib}
        return sorted(t for t in immediate_attrs if isinstance(t, str))

    def _get_texts(self) -> TextsMixin:
        path = self._origin.category_path
        name = DISPLAYED_TEXTS[str(path)]
        desc = DISPLAYED_TEXTS.get(f"{str(path)}Description")
        flavor = DISPLAYED_TEXTS.get(f"{str(path)}Flavor")
        return TextsMixin(name, flavor, desc)

    def _validate_root_tag(self) -> None:
        if self.ROOT_TAG and self.root.tag != self.ROOT_TAG:
            raise ValueError(f"Invalid root tag: {self.root.tag!r}")


class _ReferenceXmlParser(XmlParser):
    @property
    def reference(self) -> Path | None:
        return self._reference

    @property
    def reffed_category(self) -> str | None:  # TODO: remove (duplicated in Upgrade)
        if not self.reference:
            return None
        origin = Origin(self.reference)
        return origin.category

    def __init__(self, file: PathLike) -> None:
        super().__init__(file)
        self._reference = self.root.attrib.get("icon")
        self._reference = Path(self._reference) if self._reference else None


class UpgradeParser(_ReferenceXmlParser):
    """Parser of 'Upgrades' .xml files.

    'strategyModifiers' tag and its content is used by the game AI and as such is not of
    interest for this project.
    """
    ROOT_TAG = "upgrade"

    @property
    def tier(self) -> int:
        return self._tier

    @property
    def required_upgrades(self) -> List[Path]:
        return self._required_upgrades

    def __init__(self, file: PathLike) -> None:
        super().__init__(file)
        if (self.file.parent.name not in FACTIONS
                or self.file.parent.parent.name != "Upgrades"):
            raise ValueError(f"Invalid input file: {self.file}")
        self._tier = self.root.attrib.get("position")
        self._tier = int(self._tier) if self._tier else 0
        self._required_upgrades = [Path(self.origin.category) / el.attrib["name"] for el
                                   in self.root.findall("requiredUpgrades/upgrade")]


def parse_upgrades() -> List[UpgradeParser]:
    # required correcting a malformed original file:
    # xml/World/Upgrades/Tau/RipykaVa.xml (doubly defined 'icon' attribute)
    rootdir = Path(r"xml/World/Upgrades")
    return [UpgradeParser(f) for p in rootdir.iterdir() if p.is_dir() for f in p.iterdir()]


class TraitParser(_ReferenceXmlParser):
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
    def sub_category(self) -> str | None:
        return self._sub_category

    @property
    def modifiers(self) -> Tuple[Modifier | AreaModifier, ...]:
        return self._modifiers

    def __init__(self, file: PathLike) -> None:
        super().__init__(file)
        if (self.file.parent.name != "Traits"
                and self.file.parent.parent.name != "Traits"):
            raise ValueError(f"Invalid input file: {self.file}")
        self._sub_category = self.root.attrib.get("category")
        self._modifiers = self._parse_modifiers()

    @classmethod
    def to_effect(cls, element: Element) -> Effect:  # recursive
        name = element.tag
        params = tuple(Parameter(attr, element.attrib[attr]) for attr in element.attrib)
        sub_effects = tuple(cls.to_effect(sub_el) for sub_el in element)
        return Effect(name, params, sub_effects)

    def _parse_modifiers(self) -> Tuple[Modifier | AreaModifier, ...]:
        modifier_tags = {mod_type.value for mod_type in ModifierType}
        modifiers = []
        for el in self.root:
            if el.tag in modifier_tags:
                type_ = ModifierType.from_tag(el.tag)
                area_el = el.find("area")
                if area_el is not None:
                    radius = area_el.attrib.get("radius")
                    area = Area(
                        area_el.attrib["affects"], int(radius) if radius is not None else None)
                else:
                    area = None

                for modifier_el in el.findall(".//modifier"):
                    effects = [
                        self.to_effect(sub_el) for el in modifier_el.findall("effects")
                        for sub_el in el]
                    conditions = [
                        self.to_effect(sub_el) for el in modifier_el.findall("conditions")
                        for sub_el in el]
                    if area:
                        modifiers.append(
                            AreaModifier(type_, tuple(conditions), tuple(effects), area))
                    else:
                        modifiers.append(
                            Modifier(type_, tuple(conditions), tuple(effects)))

        return tuple(modifiers)


def parse_traits() -> List[TraitParser]:
    # required correcting a malformed original file:
    # xml/World/Traits/ChaosSpaceMarines/RunesOfTheBloodGod.xml (missing whitespace)
    rootdir = Path(r"xml/World/Traits")
    flat = [f for f in rootdir.iterdir() if f.is_file()]
    nested = [f for p in rootdir.iterdir() if p.is_dir() for f in p.iterdir()]
    traits = []
    for f in [*flat, *nested]:
        try:
            traits.append(TraitParser(f))
        except XMLSyntaxError:
            pass
    return traits
