from __future__ import annotations

import xml.etree.ElementTree as ET

BNS = "http://api.platform.boomi.com/"

READ_ONLY_ATTRIBUTES = frozenset({
    "folderFullPath",
    "createdDate",
    "createdBy",
    "modifiedDate",
    "modifiedBy",
    "currentVersion",
    "deleted",
    "folderName",
    "branchName",
    "branchId",
    "copiedFromComponentId",
    "copiedFromComponentVersion",
})


def qname(ns: str, local: str) -> str:
    return f"{{{ns}}}{local}"


def local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def parse_xml(text: str) -> ET.Element:
    ET.register_namespace("bns", BNS)
    return ET.fromstring(text)


def tostring(root: ET.Element) -> str:
    ET.register_namespace("bns", BNS)
    return "<?xml version='1.0' encoding='UTF-8'?>\n" + ET.tostring(root, encoding="unicode")


def remove_read_only_attributes(root: ET.Element) -> None:
    for attr in READ_ONLY_ATTRIBUTES:
        if attr in root.attrib:
            del root.attrib[attr]


def iter_local(root: ET.Element, local: str) -> list[ET.Element]:
    results: list[ET.Element] = []
    for elem in root.iter():
        if local_name(elem.tag) == local:
            results.append(elem)
    return results


def remove_dangling_references(root: ET.Element) -> None:
    """Remove SharedCommOverrides and PartnerOverrides that may contain invalid component references."""
    tags_to_remove = ("SharedCommOverrides", "PartnerOverrides")
    _remove_elements_by_local_name(root, tags_to_remove)


def _remove_elements_by_local_name(root: ET.Element, names: tuple[str, ...]) -> None:
    for parent in list(root.iter()):
        to_remove = [child for child in parent if local_name(child.tag) in names]
        for child in to_remove:
            parent.remove(child)
