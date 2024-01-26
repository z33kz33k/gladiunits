"""

    gladiunits.dereference.py
    ~~~~~~~~~~~~~~~~~~~~~~~~~
    Dereference data structures.

    @author: z33k

"""
from collections import deque

from gladiunits.data import Data, UpgradeWrapper, Trait, Unit, Upgrade, Weapon


def sift_upgrades(
        *upgrades: UpgradeWrapper | Upgrade) -> tuple[list[Upgrade], list[UpgradeWrapper]]:
    true_upgrades, wrappers = [], []
    for u in upgrades:
        if isinstance(u, UpgradeWrapper):
            wrappers.append(u)
        else:
            true_upgrades.append(u)
    return true_upgrades, wrappers


def get_context(upgrades: list[UpgradeWrapper | Upgrade] = (), traits: list[Trait] = (),
                weapons: list[Weapon] = (),
                units: list[Unit] = ()) -> tuple[dict[str, Data], list[Data]]:
    upgrades = upgrades or []
    upgrades, upgrade_wrappers = sift_upgrades(*upgrades)
    upgrade_wrappers.sort(key=lambda u: u.upgrade.tier)
    parsed = [*upgrades, *upgrade_wrappers, *traits, *weapons, *units]
    resolved, unresolved = {}, []
    for parsed_item in parsed:
        if parsed_item.is_resolved:
            resolved[str(parsed_item.category_path)] = parsed_item
        else:
            unresolved.append(parsed_item)
    return resolved, unresolved


class Dereferencer:
    @property
    def base(self) -> Data:
        return self._base

    @property
    def context(self) -> dict[str, Data]:
        return self._context

    def __init__(self, base: Data, context: dict[str, Data]) -> None:
        self._base, self._context = base, context
        self._resolved = self._get_resolved()

    def _get_resolved(self) -> dict[str, Data]:
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
                    if token.isdigit():
                        current_obj[int(token)] = replacer
                    else:
                        current_obj.__dict__[token] = replacer
                    break

                if token.isdigit():
                    current_obj = current_obj[int(token)]
                else:
                    current_obj = getattr(current_obj, token)


def dereference(resolved: dict[str, Data],
                unresolved: list[Data], *ignored_categories: str
                ) -> tuple[list[Upgrade], list[Trait], list[Weapon], list[Unit]]:
    stack = unresolved[::-1]
    stack = deque(stack)
    while stack:
        obj = stack.pop()
        deref = Dereferencer(obj, context=resolved)
        deref.resolve()
        if obj.is_resolved:
            try:
                resolved[str(obj.category_path)] = obj
            except AttributeError as e:  # an upgrade wrapper
                if "UpgradeWrapper" in str(e):
                    resolved[str(obj.upgrade.category_path)] = obj.to_upgrade()
                else:
                    raise
        else:
            if ignored_categories:
                cats = [ref.category for ref in obj.unresolved_refs.values()]
                if all(c in ignored_categories for c in cats):
                    resolved[str(obj.category_path)] = obj
                    continue
            stack.appendleft(obj)

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
