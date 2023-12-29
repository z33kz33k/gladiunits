import re
from collections import deque
from pathlib import Path
from typing import Dict, List

import lxml
from lxml.etree import XMLSyntaxError, _Element as Element

from gladiunits.constants import PathLike
from gladiunits.data import Origin, CATEGORIES


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


class XmlParser(FileParser):
    @property
    def root(self) -> Element:
        return self._root

    def __init__(self, file: PathLike) -> None:
        super().__init__(file)
        try:
            self._root: Element = lxml.etree.parse(self.file).getroot()
        except XMLSyntaxError as e:
            if "Unescaped '<' not allowed" in str(e):
                with self.file.open(encoding="utf8") as f:
                    lines = [self.sanitize_line(line) for line in f][1:]

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
                            self._root = lxml.etree.fromstring("".join(truly_sanitized))
                        else:
                            raise
            else:
                raise

    @staticmethod
    def sanitize_line(line: str) -> str:  # GPT4
        # define a function to replace < and > with { and } respectively
        def replace_brackets(match):
            return match.group().replace('<', '{').replace('>', '}')

        # use re.sub with a function as replacer
        return re.sub(r"(?<=value=\")<.*>(?=\")", replace_brackets, line)


class _EntryLine:
    PATTERN_TEMPLATE = r'{}=\"(.*)\"'

    @property
    def name(self) -> str:
        return self._name

    @property
    def category(self) -> str:
        return self._category

    @property
    def name_origin(self) -> Origin:
        path = Path(self.category) / self.name
        return Origin(path)

    @property
    def value(self) -> str:
        return self._value

    @property
    def ref(self) -> Origin | None:
        return self._ref

    def __init__(self, line: str, category: str) -> None:
        if not self.is_valid(line):
            raise ValueError(f"Invalid entry line: '{line}'")
        self._line, self._category = line, category
        self._ref = None
        self._name = self._parse_name()
        self._value = self._parse(self._line, "value")
        if self.value.startswith("<string name="):
            self._ref = Origin(Path(self._parse(self.value, "name", double_quotes=False)))

    def __repr__(self) -> str:
        text = f"{self.__class__.__name__}(origin='{self.name_origin.path}'"
        if self.ref:
            text += f", ref='{self.ref.path}')"
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
        return not any(token not in line for token in ("<entry", "name=", "value=", "/>"))


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
    def refs(self) -> List[Origin]:
        return sorted({el.ref for el in self.reffed_lines}, key=lambda r: str(r.path))

    def __init__(self, file: PathLike) -> None:
        super().__init__(file)
        if self.category not in CATEGORIES:
            raise ValueError(f"Unknown category: {self.category!r}")
        self._entry_lines = []
        for line in self.lines:
            if _EntryLine.is_valid(line):
                self._entry_lines.append(_EntryLine(line, self.category))


def _parse_displayed_texts() -> Dict[Origin, str]:
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

    context = {entry_line.name_origin: entry_line.value for parser in parsers
               for entry_line in parser.plain_lines}

    stack = [entry_line for parser in parsers for entry_line in parser.reffed_lines][::-1]
    stack = deque(stack)
    while stack:
        line = stack.pop()
        found = context.get(line.ref)
        if found:
            context.update({line.name_origin: found})
        else:
            stack.appendleft(line)

    return context


DISPLAYED_TEXTS = _parse_displayed_texts()
