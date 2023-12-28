import re
from abc import ABC
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

import lxml
from lxml.etree import _Element as Element
from lxml.etree import XMLSyntaxError


PathLike = Path | str


class XmlParser:
    @property
    def file(self) -> Path:
        return self._file

    @property
    def root(self) -> Element:
        return self._root

    def __init__(self, file: PathLike) -> None:
        self._file = Path(file)
        try:
            self._root: Element = lxml.etree.parse(self.file).getroot()
        except XMLSyntaxError:
            with self.file.open(encoding="utf8") as f:
                lines = [self.sanitize_line(line) for line in f]
                self._root = lxml.etree.fromstring("".join(lines[1:]))

    @staticmethod
    def sanitize_line(line: str) -> str:  # GPT4
        # define a function to replace < and > with { and } respectively
        def replace_brackets(match):
            return match.group().replace('<', '{').replace('>', '}')

        # use re.sub with a function as replacer
        return re.sub(r"(?<=value=\")<.*>(?=\")", replace_brackets, line)


@dataclass(frozen=True)
class Weapon:
    name: str


@dataclass(frozen=True)
class Action:
    name: str
    cooldown: int | None

    def __post__init__(self) -> None:
        if self.cooldown and self.cooldown < 0:
            raise ValueError("Cooldown must not be negative")


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
class Trait:
    name: str
    required_upgrade: str | None


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

    @property
    def total_hitpoints(self) -> float:
        return self.hitpoints * self.group_size


def _parse_displayed_unit_names() -> Dict[str, str]:
    xml = XmlParser(r"xml/Core/Languages/English/Units.xml")
    entries = [entry for entry in xml.root.findall(".//entry")
               if not entry.attrib["name"].endswith("Description")
               and not entry.attrib["name"].endswith("Flavor")
               and "{" not in entry.attrib["value"]]
    return {entry.attrib["name"]: entry.attrib["value"] for entry in entries}


DISPLAYED_UNIT_NAMES = _parse_displayed_unit_names()
