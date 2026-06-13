from typing import Iterable

import bleach
from bleach.css_sanitizer import CSSSanitizer


ALLOWED_TAGS: Iterable[str] = {
    "a",
    "abbr",
    "b",
    "blockquote",
    "body",
    "br",
    "code",
    "col",
    "colgroup",
    "div",
    "em",
    "font",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "i",
    "img",
    "li",
    "ol",
    "p",
    "pre",
    "s",
    "span",
    "strike",
    "strong",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
}

def _allow_img_attribute(tag: str, name: str, value: str) -> bool:
    if name in {"alt", "height", "title", "width"}:
        return True
    if name == "src" and value:
        return value.lower().startswith("cid:")
    return False


ALLOWED_ATTRIBUTES = {
    "*": ["align", "class", "dir", "height", "style", "title", "valign", "width"],
    "a": ["href", "name", "target", "title"],
    "abbr": ["title"],
    "font": ["color", "face", "size"],
    "img": _allow_img_attribute,
    "td": ["colspan", "rowspan", "scope"],
    "th": ["colspan", "rowspan", "scope"],
}

CSS_SANITIZER = CSSSanitizer(
    allowed_css_properties=[
        "background",
        "background-color",
        "border",
        "border-bottom",
        "border-collapse",
        "border-color",
        "border-left",
        "border-right",
        "border-spacing",
        "border-style",
        "border-top",
        "border-width",
        "color",
        "display",
        "font",
        "font-family",
        "font-size",
        "font-style",
        "font-weight",
        "height",
        "line-height",
        "margin",
        "margin-bottom",
        "margin-left",
        "margin-right",
        "margin-top",
        "max-width",
        "mso-line-height-rule",
        "padding",
        "padding-bottom",
        "padding-left",
        "padding-right",
        "padding-top",
        "text-align",
        "text-decoration",
        "vertical-align",
        "white-space",
        "width",
        "word-break",
    ]
)


def sanitize_html(value: str) -> str:
    if not value:
        return ""
    return bleach.clean(
        value,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=["http", "https", "mailto", "cid"],
        css_sanitizer=CSS_SANITIZER,
        strip=True,
    )
