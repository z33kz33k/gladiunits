"""

    gladiunits.dereference.py
    ~~~~~~~~~~~~~~~~~~~~~~~~~
    Dereference data structures.

    @author: z33k

"""
from copy import deepcopy
from dataclasses import fields, is_dataclass
from typing import Any

from gladiunits.data import Parsed, is_unresolved_ref
from gladiunits.parse import parse_all


def get_context() -> tuple:
    upgrades, traits, weapons, units = parse_all()
    upgrades.sort(key=lambda u: u.tier)
    parsed = [*upgrades, *traits, *weapons, *units]
    resolved, unresolved = {}, []
    for parsed_item in parsed:
        if parsed_item.is_resolved:
            resolved[str(parsed_item.category_path)] = parsed_item
        else:
            unresolved.append(parsed_item)
    return (upgrades, traits, weapons, units), resolved, unresolved


class Dereferencer:
    @property
    def base(self) -> Parsed:
        return self._base

    @property
    def context(self) -> dict[str, Parsed]:
        return self._context

    def __init__(self, base: Parsed, context: dict[str, Parsed]) -> None:
        self._base, self._context = base, context
        self._resolved = self._get_resolved()

    def _get_resolved(self) -> dict[str, Parsed]:
        resolved = {}
        for ref, value in self.base.unresolved_references.items():
            obj = self.context.get(str(value))
            if obj:
                resolved[ref] = obj
        return resolved

    def resolve(self) -> None:
        for crumbs, replacer in self._resolved.items():
            current_obj = self.base
            stack = crumbs.split(".")[::-1]
            while stack:
                token = stack.pop()
                if not stack:
                    current_obj.__dict__[token] = replacer
                    break

                if token.isdigit():
                    current_obj = current_obj[int(token)]
                else:
                    current_obj = getattr(current_obj, token)
