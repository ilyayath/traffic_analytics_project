"""
Composite Pattern (рівень рендера).

Композит уже виражений у моделі ReportSection (parent → children).
Цей модуль додає класичну GoF-реалізацію Component/Leaf/Composite,
яка йде поверх ORM і дозволяє рендерити дерево однаково,
не залежно від того, лист це чи контейнер.

Це і є те, що згадується в методичці:
"застосування Composite для побудови ієрархічних структур у вебінтерфейсах"
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, List


class ReportComponent(ABC):
    """Абстрактний базовий компонент дерева звіту."""

    def __init__(self, title: str):
        self.title = title

    @abstractmethod
    def render(self, indent: int = 0) -> str:
        """Текстове відображення (для CLI/логів/документації)."""

    @abstractmethod
    def total_leaves(self) -> int:
        """Скільки листів містить піддерево (для статистики)."""

    def add(self, child: "ReportComponent") -> None:  # noqa: D401
        """За замовчуванням лист не приймає дітей."""
        raise TypeError(f"{self.__class__.__name__} є листом і не може мати дочірні елементи")


class LeafSection(ReportComponent):
    """Лист — конкретна секція з даними (графік / таблиця / метрика)."""

    def __init__(self, title: str, kind: str, payload: dict):
        super().__init__(title)
        self.kind = kind
        self.payload = payload

    def render(self, indent: int = 0) -> str:
        return f"{'  ' * indent}- [{self.kind}] {self.title}"

    def total_leaves(self) -> int:
        return 1


class CompositeSection(ReportComponent):
    """Композит — група, що містить дочірні компоненти."""

    def __init__(self, title: str):
        super().__init__(title)
        self._children: List[ReportComponent] = []

    @property
    def children(self) -> Iterable[ReportComponent]:
        return tuple(self._children)

    def add(self, child: ReportComponent) -> None:
        self._children.append(child)

    def render(self, indent: int = 0) -> str:
        lines = [f"{'  ' * indent}+ {self.title}/"]
        for child in self._children:
            lines.append(child.render(indent + 1))
        return "\n".join(lines)

    def total_leaves(self) -> int:
        return sum(c.total_leaves() for c in self._children)


def build_tree_from_orm(report) -> CompositeSection:
    """
    Конвертує ORM-секції у дерево GoF-компонентів.
    Корисно для генерації OutLine/PDF звіту або для CLI.
    """
    root = CompositeSection(report.title)
    _attach_children(root, report.root_sections)
    return root


def _attach_children(node: CompositeSection, queryset) -> None:
    for section in queryset:
        if section.is_leaf:
            node.add(LeafSection(
                title=section.title,
                kind=section.section_type,
                payload=section.payload or {},
            ))
        else:
            child = CompositeSection(section.title)
            node.add(child)
            _attach_children(child, section.children.all().order_by("position"))
