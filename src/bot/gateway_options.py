DEFAULT_ALL_SECTIONS_LABEL = "↩️ Все разделы"

_all_sections_enabled = True
_all_sections_label = DEFAULT_ALL_SECTIONS_LABEL


def configure_all_sections_button(*, enabled: bool, label: str) -> None:
    global _all_sections_enabled, _all_sections_label
    _all_sections_enabled = enabled
    _all_sections_label = label.strip() or DEFAULT_ALL_SECTIONS_LABEL


def all_sections_button_label() -> str | None:
    if not _all_sections_enabled:
        return None
    return _all_sections_label
