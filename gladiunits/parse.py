import re
from pathlib import Path
from typing import Dict

import lxml
from lxml.etree import XMLSyntaxError, _Element as Element

from gladiunits.constants import PathLike


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


def _parse_displayed_names(file: PathLike) -> Dict[str, str]:
    xml = XmlParser(file)
    entries = [entry for entry in xml.root.findall(".//entry")
               if not entry.attrib["name"].endswith("Description")
               and not entry.attrib["name"].endswith("Flavor")
               and "{" not in entry.attrib["value"]]
    return {entry.attrib["name"]: entry.attrib["value"] for entry in entries}


DISPLAYED_NAMES = {
    "actions": _parse_displayed_names(r"xml/Core/Languages/English/Actions.xml"),
    "units": _parse_displayed_names(r"xml/Core/Languages/English/Units.xml"),
    "weapons": _parse_displayed_names(r"xml/Core/Languages/English/Weapons.xml"),
}
