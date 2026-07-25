from __future__ import annotations

import base64

_CAPTION_PREFIX = "LOCAL_CAPTION_B64:"


def attach_local_caption(prompt: str, caption: str) -> str:
    encoded = base64.urlsafe_b64encode(caption.encode("utf-8")).decode("ascii")
    return f"{_CAPTION_PREFIX}{encoded}\n{prompt}"


def split_local_caption(prompt: str) -> tuple[str, str | None]:
    first_line, separator, remainder = prompt.partition("\n")
    if not first_line.startswith(_CAPTION_PREFIX):
        return prompt, None
    encoded = first_line.removeprefix(_CAPTION_PREFIX)
    try:
        caption = base64.urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return prompt, None
    return remainder if separator else "", caption
