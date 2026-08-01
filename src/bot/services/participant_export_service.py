import csv
from io import StringIO


def _excel_safe(value: object | None) -> str:
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def build_participants_csv(users: list) -> bytes:
    """Build a UTF-8 CSV that opens correctly in Russian Excel."""
    stream = StringIO(newline="")
    writer = csv.writer(stream, delimiter=";", lineterminator="\r\n")
    writer.writerow(
        [
            "№",
            "ФИО",
            "Город",
            "Телефон",
            "Username",
            "Telegram ID",
            "Имя в Telegram",
            "Анкета",
            "История ФИО",
            "История телефона",
            "История города",
            "Дата регистрации",
            "Статус",
        ]
    )
    role_labels = {"user": "Пользователь", "admin": "Администратор", "banned": "Заблокирован"}
    for index, user in enumerate(users, start=1):
        role_value = getattr(user.role, "value", str(user.role))
        histories: dict[str, list[str]] = {
            "customer_full_name": [],
            "phone_number": [],
            "city": [],
        }
        for change in getattr(user, "profile_changes", []):
            if change.field_name not in histories:
                continue
            changed_at = change.changed_at.strftime("%d.%m.%Y %H:%M") if change.changed_at else ""
            histories[change.field_name].append(
                f"{changed_at}: {change.old_value or 'не заполнено'} → {change.new_value or 'не заполнено'}"
            )
        writer.writerow(
            [
                index,
                _excel_safe(user.customer_full_name),
                _excel_safe(user.city),
                _excel_safe(user.phone_number),
                _excel_safe(f"@{user.username}" if user.username else ""),
                user.telegram_id,
                _excel_safe(user.full_name),
                "Заполнена" if user.phone_number and user.customer_full_name and user.city else "Не полностью",
                _excel_safe(" | ".join(histories["customer_full_name"])),
                _excel_safe(" | ".join(histories["phone_number"])),
                _excel_safe(" | ".join(histories["city"])),
                user.created_at.strftime("%d.%m.%Y %H:%M") if user.created_at else "",
                role_labels.get(role_value, role_value),
            ]
        )
    return stream.getvalue().encode("utf-8-sig")
