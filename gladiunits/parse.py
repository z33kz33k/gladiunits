"""

    gladiunits.parse.py
    ~~~~~~~~~~~~~~~~~~~
    Parse the game XMLs.

    @author: z33k

"""
import os
import re
from collections import deque
from pathlib import Path

import lxml
from lxml.etree import XMLSyntaxError, _Element as Element

from gladiunits.constants import PathLike, T
from gladiunits.data import (Action, Area, AreaModifier, Modifier, Origin, Parameter, Target,
                             TextsMixin, CATEGORIES, FACTIONS, Effect, CategoryEffect, ModifierType,
                             Trait, Unit, Upgrade, Weapon, WeaponType)
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


def get_texts(origin: Origin) -> TextsMixin:
    path = origin.category_path
    name = DISPLAYED_TEXTS[str(path)]
    desc = DISPLAYED_TEXTS.get(f"{str(path)}Description")
    flavor = DISPLAYED_TEXTS.get(f"{str(path)}Flavor")
    return TextsMixin(name, desc, flavor)


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
        self._texts = get_texts(self.origin)
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

    def _validate_root_tag(self) -> None:
        if self.ROOT_TAG and self.root.tag != self.ROOT_TAG:
            raise ValueError(f"Invalid root tag: {self.root.tag!r}")

    @classmethod
    def to_effect(
            cls, element: Element,
            parent_category: str | None = None,
            process_sub_effects=True) -> Effect | CategoryEffect:  # recursive
        name = element.tag
        category = CategoryEffect.get_category(name) or parent_category
        params = tuple(
            cls.to_param(attr, value, category) for attr, value in (element.attrib.items()))

        if process_sub_effects:
            sub_effects = tuple(cls.to_effect(sub_el, category) for sub_el in element)
        else:
            sub_effects = ()
        if CategoryEffect.is_valid(name):
            return CategoryEffect(name, params, sub_effects)
        return Effect(name, params, sub_effects)

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
        elif isinstance(value_type, tuple):  # weaponSlotNames case (collection of origins)
            attr_category = CategoryEffect.get_category(attr)
            category = attr_category if attr_category else category
            return Parameter(attr, tuple(Origin(Path(category) / v) for v in value.split()))
        return Parameter(attr, value_type(value))

    @classmethod
    def parse_effects(
            cls, parent_element: Element,
            container_xpath="effects",
            process_sub_effects=True) -> tuple[Effect | CategoryEffect, ...]:
        return tuple(
            cls.to_effect(sub_el, process_sub_effects=process_sub_effects)
            for el in parent_element.findall(container_xpath)
            for sub_el in el)

    @classmethod
    def parse_modifier(
            cls, modifier_el: Element, type_: ModifierType,
            area: Area | None = None) -> Modifier | AreaModifier:
        effects = cls.parse_effects(modifier_el)
        conditions = cls.parse_effects(modifier_el, "conditions")
        if area:
            return AreaModifier(type_, conditions, effects, area)
        return Modifier(type_, conditions, effects)

    @classmethod
    def parse_modifiers(cls, root: Element) -> tuple[Modifier | AreaModifier, ...]:
        modifier_tags = {*{mod_type.value for mod_type in ModifierType}, "areas"}
        modifiers, container_elements = [], [el for el in root if el.tag in modifier_tags]
        for el in container_elements:
            type_ = ModifierType.REGULAR if el.tag == "areas" else ModifierType.from_tag(el.tag)

            for sub_el in el:
                # area modifiers
                if sub_el.tag == "area":
                    area = cls.parse_area(sub_el)
                    for modifier_el in sub_el.findall(".//modifier"):
                        modifiers.append(cls.parse_modifier(modifier_el, type_, area))
                elif sub_el.tag == "modifier":
                    modifiers.append(cls.parse_modifier(sub_el, type_))
                else:
                    for modifier_el in sub_el.findall(".//modifier"):
                        modifiers.append(cls.parse_modifier(modifier_el, type_))

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

    @staticmethod
    def parse_reference(reference_el: Element) -> Origin | None:
        reference = reference_el.attrib.get("icon")
        if not reference:
            return None
        reference = Path(reference)
        if not any(p in CATEGORIES for p in reference.parts):
            return None  # self-reference, e.g. in Traits/Missing.xml
        return Origin(reference)

    @classmethod
    def parse_target(cls, target_el: Element) -> Target:
        is_self_target = "self" in target_el.tag
        max_range = cls.get_value_from_attr(target_el, "rangeMax", int)
        min_range = cls.get_value_from_attr(target_el, "rangeMin", int)
        line_of_sight = cls.get_value_from_attr(target_el, "lineOfSight", int)
        conditions = cls.parse_effects(target_el, "conditions")
        modifiers = cls.parse_modifiers(target_el)
        return Target(modifiers, is_self_target, max_range, min_range, line_of_sight, conditions)

    @staticmethod
    def get_value(element: Element | None, xpath: str, value_type: T) -> T | None:
        if element is None:
            return None
        sub_el = element.find(xpath)
        if sub_el is None:
            return None
        return value_type(sub_el.text)

    @staticmethod
    def get_value_from_attr(element: Element | None, attr: str, value_type: T) -> T | None:
        if element is None:
            return None
        value = element.attrib.get(attr)
        if value is None:
            return None
        return value_type(value)


class UpgradeParser(XmlParser):
    """Parser of 'Upgrades' .xml files.

    'strategyModifiers' tag and its content is used by the game AI and as such is not of
    interest for this project.
    """
    ROOT_TAG = "upgrade"

    @property
    def tier(self) -> int:
        return self._tier

    @property
    def required_upgrades(self) -> tuple[Origin, ...]:
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
        self._reference = self.parse_reference(self.root)
        self._tier = self.root.attrib.get("position")
        self._tier = int(self._tier) if self._tier else 0
        self._required_upgrades = tuple(
            Origin(Path("Upgrades") / el.attrib["name"]) for el in self.root.findall(
                "requiredUpgrades/upgrade"))
        self._dlc = self.root.attrib.get("dlc")
        if self._dlc:
            self._dlc = DISPLAYED_TEXTS.get(str(Path("WorldParameters") / self._dlc))

    def to_upgrade(self) -> Upgrade:
        return Upgrade(
            self.origin.path,
            self.texts.name,
            self.texts.description,
            self.texts.flavor,
            self.reference,
            self.tier,
            self.required_upgrades,
            self.dlc
        )


def parse_upgrades() -> list[Upgrade]:
    # required correcting a malformed original file:
    # Upgrades/Tau/RipykaVa.xml (doubly defined 'icon' attribute)
    rootdir = Path(r"xml/World/Upgrades")
    return [UpgradeParser(f).to_upgrade() for p in rootdir.iterdir()
            if p.is_dir() for f in p.iterdir()]


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

    def to_trait(self) -> Trait:
        return Trait(
            self.origin.path,
            self.texts.name,
            self.texts.description,
            self.texts.flavor,
            self.reference,
            self.modifiers,
            self.type,
            self.target_conditions,
            self.max_rank,
            self.stacking
        )


def parse_traits() -> list[Trait]:
    # required correcting a malformed original file:
    # Traits/ChaosSpaceMarines/RunesOfTheBloodGod.xml (missing whitespace)
    rootdir = Path(r"xml/World/Traits")
    flat = [f for f in rootdir.iterdir() if f.is_file()]
    nested = [f for p in rootdir.iterdir() if p.is_dir() for f in p.iterdir()]
    traits = []
    for f in [*flat, *nested]:
        try:
            traits.append(TraitParser(f).to_trait())
        except XMLSyntaxError:
            pass  # Traits/OrkoidFungusFood.xml (the body commented out)
    return traits


class WeaponParser(XmlParser):
    ROOT_TAG = "weapon"

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
    def traits(self) -> tuple[CategoryEffect, ...]:
        return self._traits

    @property
    def reference(self) -> Origin | None:
        return self._reference

    def __init__(self, file: PathLike) -> None:
        super().__init__(file)
        if self.file.parent.name != "Weapons":
            raise ValueError(f"Invalid input file: {self.file}")
        self._reference = self.parse_reference(self.root)
        self._modifiers = self.parse_modifiers(self.root)
        self._type = self._parse_type()
        self._target = self._get_target()
        self._traits = self.parse_effects(self.root, "traits")

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

    def to_weapon(self) -> Weapon:
        return Weapon(
            self.origin.path,
            self.texts.name,
            self.texts.description,
            self.texts.flavor,
            self.reference,
            self.modifiers,
            self.type,
            self.target,
            self.traits
        )


def parse_weapons() -> list[Weapon]:
    rootdir = Path(r"xml/World/Weapons")
    return [WeaponParser(f).to_weapon() for f in rootdir.iterdir()]


class _ActionSubParser:
    @property
    def root(self) -> Element:
        return self._root

    @property
    def name(self) -> str:
        return self.root.tag

    @property
    def params(self) -> tuple[Parameter, ...]:
        return self._params

    @property
    def reference(self) -> Origin | None:
        return from_iterable(self.params, lambda p: p.type == "reference")

    @property
    def texts(self) -> TextsMixin | None:
        return self._texts

    @property
    def modifiers(self) -> tuple[Modifier, ...]:
        return self._modifiers

    @property
    def conditions(self) -> tuple[Effect, ...]:
        return self._conditions

    @property
    def targets(self) -> tuple[Target, ...]:
        return self._targets

    def __init__(self, root: Element) -> None:
        self._root = root
        self._reference = XmlParser.parse_reference(self.root)
        self._texts = self._parse_texts()
        self._params = tuple(
            XmlParser.to_param(k, v, "Actions") for (k, v) in self.root.attrib.items())
        self._modifiers = XmlParser.parse_modifiers(self.root)
        self._conditions = XmlParser.parse_effects(self.root, "conditions")
        self._targets = self._parse_targets()

    def _parse_texts(self) -> TextsMixin | None:
        path = self.root.attrib.get("name")
        if not path:
            return None
        try:
            return get_texts(Origin(Path("Actions") / path))
        except KeyError:
            try:
                return get_texts(Origin(Path("Traits") / path))
            except KeyError:
                if any("weapon" in attr for attr in self.root.attrib):
                    if "/" in path:
                        faction, name = path.split("/")
                        return get_texts(Origin(Path("Weapons") / name))
                return None

    def _parse_targets(self) -> tuple[Target, ...]:
        root = self.root.find("beginTargets")
        if root is None:
            return ()
        return tuple(XmlParser.parse_target(el) for el in root)

    def to_action(self) -> Action:
        return Action(self.reference, self.modifiers, self.name, self.params, self.texts,
                      self.conditions, self.targets)


class UnitParser(XmlParser):
    ROOT_TAG = "unit"

    @property
    def group_size(self) -> int:
        return self._group_size

    @property
    def modifiers(self) -> tuple[Modifier, ...]:
        return self._modifiers

    @property
    def weapons(self) -> tuple[CategoryEffect, ...]:
        return self._weapons

    @property
    def actions(self) -> tuple[Action, ...]:
        return self._actions

    @property
    def traits(self) -> tuple[CategoryEffect, ...]:
        return self._traits

    @property
    def reference(self) -> Origin | None:
        return self._reference

    def __init__(self, file: PathLike) -> None:
        super().__init__(file)
        if (self.file.parent.parent.name != "Units"
                and self.file.parent.parent.parent.name != "Units"):
            raise ValueError(f"Invalid input file: {self.file}")
        self._reference = self.parse_reference(self.root)
        group_el = self.root.find("group")
        self._group_size = int(group_el.attrib["size"]) if group_el is not None else 1
        self._modifiers = self.parse_modifiers(self.root)
        self._weapons = self.parse_effects(self.root, "weapons", process_sub_effects=False)
        self._actions = tuple(_ActionSubParser(el).to_action() for el in self.root.find("actions"))
        self._traits = self.parse_effects(self.root, "traits")

    def to_unit(self) -> Unit:
        return Unit(
            self.origin.path,
            self.texts.name,
            self.texts.description,
            self.texts.flavor,
            self.reference,
            self.modifiers,
            self.group_size,
            self.weapons,
            self.actions,
            self.traits
        )


def parse_units() -> list[Unit]:
    rootdir = Path(r"xml/World/Units")
    return [UnitParser(Path(dir_) / f).to_unit() for dir_, _, files
            in os.walk(rootdir) for f in files]


def parse_all() -> tuple[list[Upgrade], list[Trait], list[Weapon], list[Unit]]:
    return parse_upgrades(), parse_traits(), parse_weapons(), parse_units()
