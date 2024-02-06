"""

    gladiunits.parse.py
    ~~~~~~~~~~~~~~~~~~~
    Parse the game XMLs.

    @author: z33k

    There's established order of parsing where previous steps are needed to be completed and
    passed to the next ones:
    1. Upgrades (need no context)
    2. Traits (need Upgrades as context)
    3. Weapons (need Upgrades and Traits as context)
    4. Units (need Upgrades, Traits and Weapons as context)
    5. Buildings (need Upgrades, Traits, Weapons and Units as context)
    6. Resolving Units' producers (need Units and Buildings as context)

    This is done in order to be able to dereference next step's objects with objects parsed
    in the previous step. Dereferencing meaning replacing paths to .xml source files with actual
    parsed objects. This is conducted in two stages: first during the parsing and next in a seperate
    after-parsing stage (using logic contained in `dereference.py` module)

    'strategyModifiers' tags and their content is used by the game AI and as such is not of
    interest for this project.

"""
import logging
import os
import re
from abc import abstractmethod
from collections import deque
from pathlib import Path
from typing import Iterable

import lxml
from lxml.etree import XMLSyntaxError, _Element as Element

from gladiunits.constants import PathLike, T, XML_DIR
from gladiunits.data import (Action, Area, AreaModifier, Building, CATEGORIES, CategoryEffect, Data,
                             Effect, FACTIONS, Modifier, ModifierType, Origin, Parameter, Target,
                             TextsMixin, Trait, Unit, Upgrade, UpgradeWrapper, Weapon, WeaponType)
from gladiunits.dereference import dereference, get_context
from gladiunits.utils import from_iterable

_log = logging.getLogger(__name__)


class File:
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
            raise FileNotFoundError(f"not a file: '{self.file}'")


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
            raise ValueError(f"invalid entry line: '{line}'")
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
            raise ValueError(f"cannot parse {attr!r} in '{text}'")
        return match.group(1)

    def _parse_name(self) -> str:
        text, *_ = self._line.split("value=")
        return self._parse(text.strip(), "name")

    @staticmethod
    def is_valid(line: str) -> bool:
        return all(token in line for token in ("<entry", "name=", "value=", "/>"))


class _CoreFileParser(File):
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
            raise ValueError(f"unknown category: {self.category!r}")
        self._entry_lines = []
        for line in self.lines:
            if _EntryLine.is_valid(line):
                self._entry_lines.append(_EntryLine(line, self.category))


def _parse_displayed_texts() -> dict[str, str]:
    files = (
        XML_DIR / "Core/Languages/English/Actions.xml",
        XML_DIR / "Core/Languages/English/Buildings.xml",
        XML_DIR / "Core/Languages/English/Features.xml",
        XML_DIR / "Core/Languages/English/Items.xml",
        XML_DIR / "Core/Languages/English/Traits.xml",
        XML_DIR / "Core/Languages/English/Units.xml",
        XML_DIR / "Core/Languages/English/Upgrades.xml",
        XML_DIR / "Core/Languages/English/Weapons.xml",
        XML_DIR / "Core/Languages/English/WorldParameters.xml",
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


def get_texts(origin: Origin) -> TextsMixin | None:
    try:
        path = origin.category_path
        name = DISPLAYED_TEXTS[str(path)]
        desc = DISPLAYED_TEXTS.get(f"{str(path)}Description")
        flavor = DISPLAYED_TEXTS.get(f"{str(path)}Flavor")
        return TextsMixin(name, desc, flavor)
    except KeyError:
        return None


class Xml(File):
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
        self._texts = get_texts(self.origin)
        if self.file.suffix.lower() != ".xml":
            raise ValueError(f"not a XML file: '{self.file}'")
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

    @staticmethod
    def _sanitize_line(line: str) -> str:  # GPT4
        # define a function to replace < and > with { and } respectively
        def replace_brackets(match):
            return match.group().replace('<', '{').replace('>', '}')

        # use re.sub with a function as replacer
        return re.sub(r"(?<=value=\")<.*>(?=\")", replace_brackets, line)


class XmlParser:
    """Abstract base parser of Gladius .xml files with logic common for specialized parsers.
    """
    ROOT_TAG = None

    @property
    def xml(self) -> Xml | None:
        return self._xml

    @property
    def root(self) -> Element:
        return self._root

    @property
    def origin(self) -> Origin | None:
        return self.xml.origin if self.xml else None

    @property
    def category(self) -> str | None:
        return self.origin.category if self.origin else None

    @property
    def faction(self) -> str | None:
        return self.origin.faction if self.origin else None

    @property
    def texts(self) -> TextsMixin | None:
        return self.xml.texts if self.xml else None

    @property
    def name(self) -> str | None:
        return self.texts.name if self.texts else None

    def __init__(self, xml: PathLike | Element, context: dict[str, Data] = None) -> None:
        self._xml = Xml(xml) if not isinstance(xml, Element) else None
        self._root = self.xml.root if self.xml else xml
        self._context = context or {}
        self._validate_root_tag()

    def collect_tags(self, root: Element = None) -> list[str]:
        root = self.root if root is None else root
        return sorted({el.tag for el in root.iter(Element)})

    def collect_attrs(self, root: Element = None) -> list[str]:
        root = self.root if root is None else root
        return sorted({attr for el in root.iter(Element) for attr in el.attrib})

    def get_immediate_tags(self, root: Element = None) -> list[str]:
        root = self.root if root is None else root
        immediate_tags = [el.tag for el in root]
        return sorted(t for t in immediate_tags if isinstance(t, str))

    def get_immediate_attrs(self, root: Element = None) -> list[str]:
        root = self.root if root is None else root
        immediate_attrs = {attr for el in root for attr in el.attrib}
        return sorted(t for t in immediate_attrs if isinstance(t, str))

    def _validate_root_tag(self) -> None:
        if self.ROOT_TAG and self.root.tag != self.ROOT_TAG:
            raise ValueError(f"invalid root tag: {self.root.tag!r}")

    def _get_context_value(self, origin: Origin) -> Data | Origin:
        data = self._context.get(str(origin.category_path))
        if data:
            return data
        return origin

    def to_effect(
            self, element: Element,
            parent_category: str = None,
            process_sub_effects=True) -> Effect | CategoryEffect:  # recursive
        name = element.tag
        category = CategoryEffect.get_category(name) or parent_category
        params = tuple(
            self.to_param(attr, value, category) for attr, value in (element.attrib.items()))

        if process_sub_effects:
            sub_effects = tuple(self.to_effect(sub_el, category) for sub_el in element)
        else:
            sub_effects = ()
        if CategoryEffect.is_valid(name):
            return CategoryEffect(name, params, sub_effects)
        return Effect(name, params, sub_effects)

    def to_param(self, attr: str, value: str, category: str | None) -> Parameter:
        value_type = Parameter.TYPES.get(attr)
        value_type = value_type or str
        if attr == "name" and category:
            v = Origin(Path(category) / value)
            return Parameter("name", self._get_context_value(v))
        elif CategoryEffect.is_valid(attr) and value_type is Origin:
            attr_category = CategoryEffect.get_category(attr)

            if attr_category == "Weapons":
                value = WeaponParser.get_name(value)

            v = Origin(Path(attr_category) / value)
            return Parameter(attr, self._get_context_value(v))
        elif attr == "icon":
            v = Origin(Path(value))
            return Parameter("reference", self._get_context_value(v))
        if value_type is bool:
            value = int(value)
        elif value_type is Origin:
            value = Path(value)
            return Parameter(attr, self._get_context_value(value_type(value)))
        elif isinstance(value_type, tuple):  # weaponSlotNames case (collection of origins)
            attr_category = CategoryEffect.get_category(attr)
            category = attr_category if attr_category else category
            return Parameter(attr, tuple(
                self._get_context_value(Origin(Path(category) / v)) for v in value.split()))
        return Parameter(attr, value_type(value))

    def parse_effects(
            self, parent_element: Element,
            container_xpath="effects",
            process_sub_effects=True) -> tuple[Effect | CategoryEffect, ...]:
        return tuple(
            self.to_effect(sub_el, process_sub_effects=process_sub_effects)
            for el in parent_element.findall(container_xpath)
            for sub_el in el)

    def parse_required_upgrade(self, element: Element) -> Upgrade | None:
        required_upgrade = element.attrib.get("requiredUpgrade")
        if required_upgrade:
            required_upgrade = f"Upgrades/{required_upgrade}"
            upgrade = self._context.get(required_upgrade)
            if not upgrade:
                raise ValueError(f"upgrade not retrievable: {required_upgrade!r}")
            return upgrade
        return None

    def _parse_modifier(
            self, modifier_el: Element, type_: ModifierType,
            area: Area = None) -> Modifier | AreaModifier:
        effects = self.parse_effects(modifier_el)
        conditions = self.parse_effects(modifier_el, "conditions")
        required_upgrade = self.parse_required_upgrade(modifier_el)
        if area:
            return AreaModifier(required_upgrade, type_, conditions, effects, area)
        return Modifier(required_upgrade, type_, conditions, effects)

    def parse_modifiers(self, root: Element) -> tuple[Modifier | AreaModifier, ...]:
        modifier_tags = {*{mod_type.value for mod_type in ModifierType}, "areas"}
        modifiers, container_elements = [], [el for el in root if el.tag in modifier_tags]
        for el in container_elements:
            type_ = ModifierType.REGULAR if el.tag == "areas" else ModifierType.from_tag(el.tag)

            for sub_el in el:
                # area modifiers
                if sub_el.tag == "area":
                    area = self._parse_area(sub_el)
                    for modifier_el in sub_el.findall(".//modifier"):
                        modifiers.append(self._parse_modifier(modifier_el, type_, area))
                elif sub_el.tag == "modifier":
                    modifiers.append(self._parse_modifier(sub_el, type_))
                else:
                    for modifier_el in sub_el.findall(".//modifier"):
                        modifiers.append(self._parse_modifier(modifier_el, type_))

        return tuple(modifiers)

    @staticmethod
    def _parse_area(area_el: Element) -> Area:
        radius = area_el.attrib.get("radius")
        exclude_radius = area_el.attrib.get("excludeRadius")
        return Area(
            area_el.attrib["affects"],
            int(radius) if radius is not None else None,
            int(exclude_radius) if exclude_radius is not None else None
        )

    def parse_reference(self, reference_el: Element) -> Data | Origin | None:
        reference = reference_el.attrib.get("icon")
        if not reference:
            return None
        reference = Path(reference)
        if not any(p in CATEGORIES for p in reference.parts):
            return None  # self-reference, e.g. in Traits/Missing.xml
        return self._get_context_value(Origin(reference))

    def parse_target(self, target_el: Element) -> Target:
        is_self_target = "self" in target_el.tag
        max_range = self._get_value_from_attr(target_el, "rangeMax", int)
        min_range = self._get_value_from_attr(target_el, "rangeMin", int)
        line_of_sight = self._get_value_from_attr(target_el, "lineOfSight", int)
        conditions = self.parse_effects(target_el, "conditions")
        modifiers = self.parse_modifiers(target_el)
        return Target(modifiers, is_self_target, max_range, min_range, line_of_sight, conditions)

    def parse_trait(self, trait_el: Element) -> Trait:
        name = trait_el.attrib["name"]
        name = f"Traits/{name}"
        trait = self._context.get(name)
        if not trait:
            raise ValueError(f"trait not retrievable: {name!r}")
        required_upgrade = self.parse_required_upgrade(trait_el)
        if required_upgrade:
            return Trait.with_upgrade(trait, required_upgrade)
        return trait

    def parse_dlc(self) -> str | None:
        dlc = self.root.attrib.get("dlc")
        if not dlc:
            return None
        return DISPLAYED_TEXTS.get(str(Path("WorldParameters") / dlc))

    @staticmethod
    def get_value(element: Element | None, xpath: str, value_type: T) -> T | None:
        if element is None:
            return None
        sub_el = element.find(xpath)
        if sub_el is None:
            return None
        return value_type(sub_el.text)

    @staticmethod
    def _get_value_from_attr(element: Element | None, attr: str, value_type: T) -> T | None:
        if element is None:
            return None
        value = element.attrib.get(attr)
        if value is None:
            return None
        return value_type(value)

    def get_required_upgrade_from_context(self) -> Upgrade | None:
        name = str(Path("Upgrades") / "/".join(self.origin.category_path.parts[1:]))
        return self._context.get(name)

    @abstractmethod
    def to_data(self) -> Data | Action:
        raise NotImplementedError


class UpgradeParser(XmlParser):
    """Parser of Upgrades .xml files.

    Misformed source file:
        * xml/World/Upgrades/Tau/RipykaVa.xml (doubled `icon` attr)

    """
    ROOT_TAG = "upgrade"

    def __init__(self, file: PathLike) -> None:
        super().__init__(file)
        if (self.xml.file.parent.name not in FACTIONS
                or self.xml.file.parent.parent.name != "Upgrades"):
            raise ValueError(f"invalid input file: {self.xml.file}")
        self._reference = self.parse_reference(self.root)
        self._tier = self.root.attrib.get("position")
        self._tier = int(self._tier) if self._tier else None
        self._required_upgrades = [
            Origin(Path("Upgrades") / el.attrib["name"]) for el in self.root.findall(
                "requiredUpgrades/upgrade")]
        self._dlc = self.parse_dlc()

    def to_data(self) -> UpgradeWrapper | Upgrade:  # override
        upgrade = Upgrade(
            self.origin.path,
            self.texts.name,
            self.texts.description,
            self.texts.flavor,
            self._reference,
            self._tier,
            self._dlc,
        )
        if self._required_upgrades:
            return UpgradeWrapper(upgrade, self._required_upgrades)
        return upgrade


def parse_upgrades(sort=False) -> list[Upgrade]:
    _log.info(f"Parsing upgrades...")
    rootdir = XML_DIR / "World/Upgrades"
    upgrades = [UpgradeParser(f).to_data() for p in rootdir.iterdir()
                if p.is_dir() for f in p.iterdir()]
    _log.info(f"Parsed {len(upgrades)} upgrades")
    resolved, unresolved = get_context(upgrades=upgrades)
    upgrades, *_ = dereference(resolved, unresolved)

    if sort:
        return sorted(upgrades, key=str)
    return upgrades


class TraitParser(XmlParser):
    """Parser of Traits .xml files.

    Misformed source file:
        * xml/World/Traits/ChaosSpaceMarines/RunesOfTheBloodGod.xml (missing whitespace)

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

    def __init__(self, file: PathLike, context: dict[str, Upgrade]) -> None:
        super().__init__(file, context)
        if (self.xml.file.parent.name != "Traits"
                and self.xml.file.parent.parent.name != "Traits"):
            raise ValueError(f"invalid input file: {self.xml.file}")
        self._reference = self.parse_reference(self.root)
        self._type = self.root.attrib.get("category")
        self._modifiers = self.parse_modifiers(self.root)
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

    def to_data(self) -> Trait:  # override
        return Trait(
            path=self.origin.path,
            name=self.texts.name,
            description=self.texts.description,
            flavor=self.texts.flavor,
            reference=self._reference,
            modifiers=self._modifiers,
            type=self._type,
            target_conditions=self._target_conditions,
            max_rank=self._max_rank,
            stacking=self._stacking,
            required_upgrade=None,
        )


def parse_traits(upgrades: Iterable[Upgrade], sort=False) -> list[Trait]:
    _log.info(f"Parsing traits...")
    context = {str(u.category_path): u for u in upgrades}
    rootdir = Path(r"xml/World/Traits")
    flat = [f for f in rootdir.iterdir() if f.is_file()]
    nested = [f for p in rootdir.iterdir() if p.is_dir() for f in p.iterdir()]
    traits = []
    for f in [*flat, *nested]:
        try:
            traits.append(TraitParser(f, context).to_data())
        except XMLSyntaxError as e:
            _log.warning(f"Skipping malformed source file: '{e}'")
            pass  # Traits/OrkoidFungusFood.xml (the body commented out)
    _log.info(f"Parsed {len(traits)} traits")
    resolved, unresolved = get_context(upgrades=[*upgrades], traits=traits)
    _, traits, *_ = dereference(resolved, unresolved, "Weapons", "Units", "Buildings")
    if sort:
        return sorted(traits, key=str)
    return traits


class WeaponParser(XmlParser):
    """Parser of Weapons .xml files.
    """
    ROOT_TAG = "weapon"
    ALIASES = {
        "Mechatendrils": "Meltagun",
        "SeekerMissile0": "SeekerMissile",
        "SeekerMissile1": "SeekerMissile",
    }

    def __init__(self, file: PathLike, context: dict[str, Data]) -> None:
        super().__init__(file, context)
        if self.xml.file.parent.name != "Weapons":
            raise ValueError(f"invalid input file: {self.xml.file}")
        self._reference = self.parse_reference(self.root)
        self._modifiers = self.parse_modifiers(self.root)
        self._type = self._parse_type()
        self._target = self._get_target()
        traits_el = self.root.find("traits")
        self._traits = tuple(
            self.parse_trait(el) for el in traits_el) if traits_el is not None else ()

    def _parse_type(self) -> WeaponType:
        model_el = self.root.find("model")
        if model_el is None:
            return WeaponType.REGULAR
        type_el = from_iterable(model_el, lambda sub_el: "weapon" in sub_el.tag.lower())
        if type_el is None:
            return WeaponType.REGULAR
        return WeaponType.from_tag(type_el.tag)

    def _get_target(self) -> Target | None:
        target_el = from_iterable(self.root, lambda el: "target" in el.tag)
        if target_el is None:
            return None
        return self.parse_target(target_el)

    @classmethod
    def get_name(cls, weapon_name: str) -> str:
        return cls.ALIASES.get(weapon_name, weapon_name)

    def to_data(self) -> Weapon:  # override
        return Weapon(
            path=self.origin.path,
            name=self.texts.name,
            description=self.texts.description,
            flavor=self.texts.flavor,
            reference=self._reference,
            modifiers=self._modifiers,
            type=self._type,
            target=self._target,
            traits=self._traits,
            required_upgrade=None,
            count=None,
            enabled=None,
        )


def parse_weapons(
        upgrades: Iterable[Upgrade], traits: Iterable[Trait], sort=False) -> list[Weapon]:
    _log.info("Parsing weapons...")
    context = {str(obj.category_path): obj for obj in [*upgrades, *traits]}
    rootdir = Path(r"xml/World/Weapons")
    weapons = [WeaponParser(f, context).to_data() for f in rootdir.iterdir()]
    _log.info(f"Parsed {len(weapons)} weapons")
    resolved, unresolved = get_context(upgrades=[*upgrades], traits=[*traits], weapons=weapons)
    _, _, weapons, *_ = dereference(resolved, unresolved, "Units", "Buildings")
    if sort:
        return sorted(weapons, key=str)
    return weapons


class _ActionSubParser(XmlParser):
    """Parser for <actions> XML tag's sub-elements.
    """
    @property
    def name(self) -> str:  # override
        return self.root.tag

    @property
    def texts(self) -> TextsMixin | None:  # override
        return self._texts

    def __init__(self, root: Element, context: dict[str, Data], faction: str) -> None:
        super().__init__(root, context)
        self._reference = self.parse_reference(self.root)
        self._texts = self._parse_texts(faction)
        self._params = tuple(
            self.to_param(k, v, "Actions") for (k, v) in self.root.attrib.items()
            if k not in ("requiredUpgrade", "weaponSlotName", "weaponSlotNames"))
        self._modifiers = self.parse_modifiers(self.root)
        self._conditions = self.parse_effects(self.root, "conditions")
        self._targets = self._parse_targets()
        self._required_upgrade = self.parse_required_upgrade(self.root)
        self._required_weapons = self._parse_required_weapons()

    def _parse_texts(self, faction: str) -> TextsMixin | None:
        path = self.root.attrib.get("name")
        if not path:
            name = self.name[0].upper() + self.name[1:]
            t = get_texts(Origin(Path("Actions") / name))
            if t:
                return t
            return get_texts(Origin(Path("Actions") / faction / name))
        t = get_texts(Origin(Path("Actions") / path))
        if t:
            return t
        t = get_texts(Origin(Path("Traits") / path))
        if t:
            return t
        if any("weapon" in attr for attr in self.root.attrib):
            if "/" in path:
                faction, name = path.split("/")
                return get_texts(Origin(Path("Weapons") / name))
        return None

    def _parse_targets(self) -> tuple[Target, ...]:
        root = self.root.find("beginTargets")
        if root is None:
            return ()
        return tuple(self.parse_target(el) for el in root)

    def _parse_required_weapons(self) -> tuple[Weapon, ...]:
        names = []
        name = self.root.attrib.get("weaponSlotName")
        if name:
            names.append(name)
        else:
            result = self.root.attrib.get("weaponSlotNames")
            if result:
                names.extend(result.split())
        if not names:
            return ()

        weapons = []
        for name in names:
            name = f"Weapons/{WeaponParser.get_name(name)}"
            weapon = self._context.get(name)
            if not weapon:
                raise ValueError(f"weapon not retrievable: {name!r}")
            weapons.append(weapon)
        return tuple(weapons)

    def to_data(self) -> Action:
        return Action(
            reference=self._reference,
            modifiers=self._modifiers,
            name=self.name,
            params=self._params,
            texts=self.texts,
            conditions=self._conditions,
            targets=self._targets,
            required_upgrade=self._required_upgrade,
            required_weapons=self._required_weapons,
        )


class UnitParser(XmlParser):
    """Parser of Units .xml files.
    """
    ROOT_TAG = "unit"

    def __init__(self, file: PathLike, context: dict[str, Data]) -> None:
        super().__init__(file, context)
        if (self.xml.file.parent.parent.name != "Units"
                and self.xml.file.parent.parent.parent.name != "Units"):
            raise ValueError(f"invalid input file: {self.xml.file}")
        self._reference = self.parse_reference(self.root)
        group_el = self.root.find("group")
        self._group_size = int(group_el.attrib["size"]) if group_el is not None else 1
        self._modifiers = self.parse_modifiers(self.root)
        weapons_el, traits_el = self.root.find("weapons"), self.root.find("traits")
        self._weapons = tuple(
            self._parse_weapon(el) for el in weapons_el) if weapons_el is not None else ()
        self._actions = tuple(
            _ActionSubParser(el, self._context, self.faction).to_data() for el in self.root.find(
                "actions"))
        self._traits = tuple(
            self.parse_trait(el) for el in traits_el) if traits_el is not None else ()
        self._required_upgrade = self.get_required_upgrade_from_context()
        self._dlc = self.parse_dlc()

    def _parse_weapon(self, weapon_el: Element) -> Weapon:
        name, count, enabled = weapon_el.attrib["name"], weapon_el.attrib.get(
            "count"), weapon_el.attrib.get("enabled")
        name = f"Weapons/{WeaponParser.get_name(name)}"
        valid_attrs = "name", "slotName", "count", "enabled", "requiredUpgrade"
        if any(attr not in valid_attrs for attr in weapon_el.attrib):
            raise ValueError(f"unrecognized weapon attrs among: {[*weapon_el.attrib]}")
        weapon = self._context.get(name)
        if not weapon:
            raise ValueError(f"weapon not retrievable: {name!r}")
        count = int(count) if count else 1
        enabled = True if not enabled else False
        return Weapon.with_additional_data(
            weapon, count, enabled, self.parse_required_upgrade(weapon_el))

    def to_data(self) -> Unit:  # override
        return Unit(
            path=self.origin.path,
            name=self.texts.name,
            description=self.texts.description,
            flavor=self.texts.flavor,
            reference=self._reference,
            modifiers=self._modifiers,
            group_size=self._group_size,
            weapons=self._weapons,
            actions=self._actions,
            traits=self._traits,
            required_upgrade=self._required_upgrade,
            dlc=self._dlc,
            producer=None
        )


def parse_units(
        upgrades: Iterable[Upgrade], traits: Iterable[Trait], weapons: Iterable[Weapon],
        sort=False) -> list[Unit]:
    _log.info("Parsing units...")
    context = {str(obj.category_path): obj for obj in [*upgrades, *traits, *weapons]}
    rootdir = Path(r"xml/World/Units")
    units = [UnitParser(Path(dir_) / f, context).to_data() for dir_, _, files
             in os.walk(rootdir) for f in files]
    _log.info(f"Parsed {len(units)} units")
    resolved, unresolved = get_context(
        upgrades=[*upgrades], traits=[*traits], weapons=[*weapons], units=units)
    *_, units, _ = dereference(resolved, unresolved, "Buildings")
    if sort:
        return sorted(units, key=str)
    return units


class BuildingParser(XmlParser):
    """Parser of Buildings .xml files.
    """
    ROOT_TAG = "building"

    def __init__(self, file: PathLike, context: dict[str, Data]) -> None:
        super().__init__(file, context)
        if (self.xml.file.parent.parent.name != "Buildings"
                and self.xml.file.parent.parent.parent.name != "Buildings"):
            raise ValueError(f"invalid input file: {self.xml.file}")
        self._modifiers = self.parse_modifiers(self.root)
        actions_el = self.root.find("actions")
        self._actions = tuple(
            _ActionSubParser(el, self._context, self.faction).to_data()
            for el in actions_el) if actions_el is not None else ()
        traits_el = self.root.find("traits")
        self._traits = tuple(
            self.parse_trait(el) for el in traits_el) if traits_el is not None else ()
        self._required_upgrade = self.get_required_upgrade_from_context()

    def to_data(self) -> Building:  # override
        return Building(
            path=self.origin.path,
            name=self.texts.name,
            description=self.texts.description,
            flavor=self.texts.flavor,
            modifiers=self._modifiers,
            actions=self._actions,
            traits=self._traits,
            required_upgrade=self._required_upgrade
        )


def parse_buildings(
        upgrades: Iterable[Upgrade], traits: Iterable[Trait], weapons: Iterable[Weapon],
        units: Iterable[Unit], sort=False) -> list[Building]:
    _log.info("Parsing buildings...")
    context = {str(obj.category_path): obj for obj in [*upgrades, *traits, *weapons, *units]}
    rootdir = Path(r"xml/World/Buildings")
    buildings = [BuildingParser(Path(dir_) / f, context).to_data() for dir_, _, files
                 in os.walk(rootdir) for f in files]
    _log.info(f"Parsed {len(buildings)} buildings")
    resolved, unresolved = get_context(
        upgrades=[*upgrades], traits=[*traits], weapons=[*weapons], units=[*units],
        buildings=buildings)
    *_, buildings = dereference(resolved, unresolved)
    if sort:
        return sorted(buildings, key=str)
    return buildings


def parse_all(
        sort=False) -> tuple[list[Upgrade], list[Trait], list[Weapon], list[Unit], list[Building]]:
    upgrades = parse_upgrades(sort=sort)
    traits = parse_traits(upgrades, sort=sort)
    weapons = parse_weapons(upgrades, traits, sort=sort)
    units = parse_units(upgrades, traits, weapons, sort=sort)
    buildings = parse_buildings(upgrades, traits, weapons, units, sort=sort)
    total = sum(1 for _ in [*upgrades, *traits, *weapons, *units, *buildings])
    _log.info(f"Resolving unit producers...")
    units = resolve_producers(units, buildings)
    _log.info(f"All parsing complete. Total {total} objects parsed")
    return upgrades, traits, weapons, units, buildings


def from_origin(origin: Origin, context: dict[str, Data] | None = None) -> Data:
    file = Path("xml") / "World" / f"{str(origin.category_path)}.xml"
    if origin.faction == "Upgrades":
        return UpgradeParser(file).to_data()
    elif origin.faction == "Traits":
        return TraitParser(file, context).to_data()
    elif origin.faction == "Weapons":
        return WeaponParser(file, context).to_data()
    elif origin.faction == "Units":
        return UnitParser(file, context).to_data()
    raise ValueError(f"invalid origin for parsing: '{origin}'")


def resolve_producers(units: Iterable[Unit], buildings: Iterable[Building]) -> list[Unit]:
    context = {}
    for building in buildings:
        for pu in building.produced_units:
            context[str(pu.category_path)] = building

    resolved_with_buildings = []
    for unit in units:
        found = context.get(str(unit.category_path))
        if found:
            resolved_with_buildings.append(Unit.with_producer(unit, found))
        else:
            resolved_with_buildings.append(unit)

    context = {}
    for unit in resolved_with_buildings:
        for action in unit.actions:
            if action.produced_unit:
                context[str(action.produced_unit.category_path)] = unit
                continue

    resolved_with_units = []
    for unit in resolved_with_buildings:
        found = context.get(str(unit.category_path))
        if found:
            resolved_with_units.append(Unit.with_producer(unit, found))
        else:
            resolved_with_units.append(unit)

    return resolved_with_units
