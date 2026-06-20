from .constants import GEOMETRY_RE, ROW_COLOR, VERIFIED_ROW_COLOR


def safe_geometry(win, geometry):
    match = GEOMETRY_RE.match(geometry or "")
    if not match:
        return geometry

    width = int(match.group(1))
    height = int(match.group(2))
    x = int(match.group(4))
    y = int(match.group(6))

    if match.group(3) == "-" and x >= 0:
        x = -x
    if match.group(5) == "-" and y >= 0:
        y = -y
    screen_width = win.winfo_screenwidth()
    screen_height = win.winfo_screenheight()

    width = min(max(width, 980), screen_width)
    height = min(max(height, 620), screen_height)
    max_x = max(0, screen_width - width)
    max_y = max(0, screen_height - height)
    x = min(max(0, x), max_x)
    y = min(max(0, y), max_y)

    return f"{width}x{height}+{x}+{y}"


def preview(text, limit=120):
    value = " ".join((text or "").split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."


def row_label(row):
    status = "OK" if len(row) > 3 and row[3] == 1 else "PEND"
    return f"{status}  |  {row[0]}  |  {preview(row[1], 105)}  |  {preview(row[2], 105)}"


def row_color(row):
    if len(row) > 3 and row[3] == 1:
        return VERIFIED_ROW_COLOR
    return ROW_COLOR


def format_timestamp(value):
    from datetime import datetime

    if not value:
        return "-"
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime(
            "%d/%m/%Y %H:%M:%S"
        )
    except ValueError:
        return value


def history_action_label(action):
    labels = {
        "edit": "Edicao",
        "edit_verify": "Edicao + verificacao",
        "verify": "Verificacao",
        "mark_pending": "Voltou para pendente",
        "fill_empty": "Preenchimento inicial",
        "restore": "Restauracao",
        "status": "Status",
    }
    return labels.get(action or "", action or "Alteracao")


def history_status_label(value):
    return "verificada" if value == 1 else "pendente"
