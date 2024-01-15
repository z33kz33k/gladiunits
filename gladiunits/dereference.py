"""

    gladiunits.dereference.py
    ~~~~~~~~~~~~~~~~~~~~~~~~~
    Dereference data structures.

    @author: z33k

"""
from collections import deque

from gladiunits.data import Parsed, Trait, Unit, Upgrade, Weapon


def get_context(upgrades: list[Upgrade], traits: list[Trait],
                weapons: list[Weapon], units: list[Unit]) -> tuple[dict[str, Parsed], list[Parsed]]:
    upgrades.sort(key=lambda u: u.tier)
    parsed = [*upgrades, *traits, *weapons, *units]
    resolved, unresolved = {}, []
    for parsed_item in parsed:
        if parsed_item.is_resolved:
            resolved[str(parsed_item.category_path)] = parsed_item
        else:
            unresolved.append(parsed_item)
    return resolved, unresolved


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
        for ref, value in self.base.unresolved_refs.items():
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


def dereference(resolved: dict[str, Parsed],
                unresolved: list[Parsed]
                ) -> tuple[list[Upgrade], list[Trait], list[Weapon], list[Unit]]:
    stack = unresolved[::-1]
    stack = deque(stack)
    _counter = 0
    while stack:
        obj = stack.pop()
        deref = Dereferencer(obj, context=resolved)
        deref.resolve()
        if obj.is_resolved:
            resolved[str(obj.category_path)] = obj
        else:
            stack.appendleft(obj)

        _counter += 1

        if _counter % 1000 == 0:
            pass

    upgrades, traits, weapons, units = [], [], [], []
    for v in resolved.values():
        if isinstance(v, Upgrade):
            upgrades.append(v)
        elif isinstance(v, Trait):
            traits.append(v)
        elif isinstance(v, Weapon):
            weapons.append(v)
        else:
            units.append(v)

    for lst in upgrades, traits, weapons, units:
        lst.sort(key=str)

    return upgrades, traits, weapons, units
