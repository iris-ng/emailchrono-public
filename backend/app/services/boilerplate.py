"""Strip common email disclaimer / confidentiality boilerplate from body text.

Ported and generalized from the earlier batch tool (approach1/toDelete.py). The
original used exact string replacement, which was brittle: a single difference in
line wrapping or a smart quote defeated the match. Here each disclaimer is compiled
into a whitespace-tolerant, quote-insensitive regex so it matches regardless of how
the mail client re-wrapped the paragraph.

Stripping is non-destructive at the record level: the caller keeps the original body
in ``raw_json`` and sets the ``boilerplate_stripped`` flag so the UI can explain it.
"""

import re
from typing import List, Pattern, Tuple


# Confidentiality / disclaimer / external-sender notices observed in real corpora.
# Keep these as plain readable text; matching is made flexible at compile time.
DISCLAIMERS: List[str] = [
    "This email and any attachments are confidential and access to this email or "
    "attachment by anyone other than the addressee is unauthorised. If you are not "
    "the intended recipient please notify the sender and permanently delete the email "
    "including any attachments. You must not copy, disclose or distribute any of the "
    "contents to any other person. Personal views or opinions are solely those of the "
    "author and not of the Group or its affiliates. The Group does not guarantee that "
    "the integrity of this communication has been maintained nor that the communication "
    "is free of viruses, interceptions or interference. By communicating with anyone at "
    "the Group by email, you consent to the monitoring or interception of such email by "
    "the Group in accordance with its internal policies. Unless otherwise stated, any "
    "pricing information given in this message is indicative only, is subject to change "
    "and does not constitute an offer to deal at any price quoted.",
    "This email and its contents, together with any attachments, are confidential to the "
    "sender and the intended recipient(s), and may be covered by legal professional "
    "privilege. If you are not the intended recipient of this email and its "
    "attachment(s), you must destroy them immediately. You must take no action based "
    "upon them, nor copy them or show them to anyone. Please contact the sender if you "
    "have received this email in error. Email communication is not secure.",
    "CAUTION: This email originated from outside of the Organization. Do not click links "
    "or open attachments unless you recognize the sender and expecting the email. If in "
    "doubt, contact IT.",
    "CAUTION: This email is originated from outside our organization, Do not click on "
    "links, open attachments, or reply unless you recognized the sender and validate the "
    "content is safe.",
    "This message is from an EXTERNAL SENDER - be CAUTIOUS, particularly with links and "
    "attachments.",
    "WARNING: This message originated outside your organization, please be vigilant.",
    "The information contained in this communication (including any attachments) is "
    "privileged and confidential, and may be legally exempt from disclosure under "
    "applicable law. It is intended only for the specific purpose of being used by the "
    "individual or entity to whom it is addressed. If you are not the addressee indicated "
    "in this message (or are responsible for delivery of the message to such person), you "
    "must not disclose, disseminate, distribute, deliver, copy, circulate, rely on or use "
    "any of the information contained in this transmission.",
    "We apologize if you have received this communication in error; kindly inform the "
    "sender accordingly. Please also ensure that this original message and any record of "
    "it is permanently deleted from your computer system. We do not give or endorse any "
    "opinions, conclusions and other information in this message that do not relate to "
    "our official business.",
]


def _char_pattern(char: str) -> str:
    if char in "'‘’′":
        return r"['‘’′]"
    if char in '"“”':
        return r'["“”]'
    if char in "-–—":
        return r"[-–—]"
    return re.escape(char)


def _word_pattern(word: str) -> str:
    return "".join(_char_pattern(char) for char in word)


def _compile(disclaimer: str) -> Pattern[str]:
    words = disclaimer.split()
    return re.compile(r"\s+".join(_word_pattern(word) for word in words), re.IGNORECASE)


_PATTERNS: List[Pattern[str]] = [_compile(text) for text in DISCLAIMERS]


def strip_boilerplate(text: str) -> Tuple[str, bool]:
    """Return (cleaned_text, removed_anything)."""
    if not text:
        return text, False
    working = text
    removed = False
    for pattern in _PATTERNS:
        cleaned = pattern.sub("", working)
        if cleaned != working:
            removed = True
            working = cleaned
    if not removed:
        return text, False
    # Collapse the blank space left behind by removed blocks.
    working = re.sub(r"[ \t]+\n", "\n", working)
    working = re.sub(r"\n{3,}", "\n\n", working).strip()
    return working, True
