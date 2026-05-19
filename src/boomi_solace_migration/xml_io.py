from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from collections.abc import Iterable

BNS = "http://api.platform.boomi.com/"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
READ_ONLY_ATTRIBUTES = {
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
}

ET.register_namespace("bns", BNS)
ET.register_namespace("xsi", XSI)


def qname(namespace: str, local: str) -> str:
    return f"{{{namespace}}}{local}"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def strip_xml_declaration(xml: str) -> str:
    text = xml.lstrip()
    if text.startswith("<?xml"):
        return text[text.index("?>") + 2 :].lstrip()
    return xml


def parse_xml(xml: str) -> ET.Element:
    return ET.fromstring(strip_xml_declaration(xml))


def iter_local(root: ET.Element, name: str) -> Iterable[ET.Element]:
    for elem in root.iter():
        if local_name(elem.tag) == name:
            yield elem


def find_child_local(elem: ET.Element, name: str) -> ET.Element | None:
    for child in elem:
        if local_name(child.tag) == name:
            return child
    return None


def remove_read_only_attributes(elem: ET.Element) -> None:
    for attr in READ_ONLY_ATTRIBUTES:
        elem.attrib.pop(attr, None)


def tostring(root: ET.Element) -> str:
    return "<?xml version='1.0' encoding='UTF-8'?>\n" + ET.tostring(root, encoding="unicode")


def canonical_xml(xml: str) -> str:
    try:
        return ET.canonicalize(xml_data=xml)
    except Exception:
        return ET.tostring(parse_xml(xml), encoding="unicode")


def sha256_text(text: str) -> str:
    return hashlib.sha256(canonical_xml(text).encode("utf-8")).hexdigest()
