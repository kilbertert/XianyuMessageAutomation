from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .models import Bounds, TextNode

_BOUNDS = re.compile(r"\[(\d+),(\d+)]\[(\d+),(\d+)]")
_UNREAD = re.compile(r"消息，未读消息数(\d+)")


def parse_bounds(value: str) -> Bounds | None:
    match = _BOUNDS.fullmatch(value)
    if not match:
        return None
    return Bounds(*(int(item) for item in match.groups()))


def text_nodes(xml: str) -> list[TextNode]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError(f"invalid UI hierarchy XML: {exc}") from exc

    result: list[TextNode] = []
    for node in root.iter("node"):
        text = node.attrib.get("text", "").strip()
        description = node.attrib.get("content-desc", "").strip()
        value = description or text
        if not value:
            continue
        result.append(
            TextNode(
                value=value,
                bounds=parse_bounds(node.attrib.get("bounds", "")),
                class_name=node.attrib.get("class", ""),
                clickable=node.attrib.get("clickable") == "true",
            )
        )
    return result


def find_text(xml: str, needle: str, *, case_sensitive: bool = False) -> list[TextNode]:
    if not needle:
        return []
    expected = needle if case_sensitive else needle.casefold()
    matches: list[TextNode] = []
    for node in text_nodes(xml):
        value = node.value if case_sensitive else node.value.casefold()
        if expected in value:
            matches.append(node)
    return matches


def unread_count(xml: str) -> int | None:
    for node in text_nodes(xml):
        match = _UNREAD.search(node.value)
        if match:
            return int(match.group(1))
        if node.value.startswith("消息，") and "无未读" in node.value:
            return 0
    return None
