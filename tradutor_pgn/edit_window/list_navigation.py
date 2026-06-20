from .pagination import EditorPaginationMixin
from .persistence import EditorPersistenceMixin
from .quality_navigation import EditorQualityNavigationMixin


class EditorListNavigationMixin(
    EditorPaginationMixin,
    EditorPersistenceMixin,
    EditorQualityNavigationMixin,
):
    pass
