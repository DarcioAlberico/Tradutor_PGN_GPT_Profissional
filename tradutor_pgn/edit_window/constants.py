import re

ROW_COLOR = ("gray86", "gray22")
VERIFIED_ROW_COLOR = ("#d1fae5", "#14532d")
ROW_HOVER_COLOR = ("gray78", "gray30")
SELECTED_ROW_COLOR = ("#3b82f6", "#1f6aa5")
SUGGESTION_COLOR = ("gray88", "gray24")
SUGGESTION_SELECTED_COLOR = ("#2563eb", "#1d4ed8")
PAGE_SIZE = 100
GEOMETRY_RE = re.compile(r"^(\d+)x(\d+)([+-])(-?\d+)([+-])(-?\d+)$")

STATUS_FILTER_VALUES = ("Todas", "Pendentes", "Verificadas", "Avisos QA")
