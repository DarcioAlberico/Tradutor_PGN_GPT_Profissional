from .list_filters import EditorListFiltersMixin
from .list_page_data import EditorListPageDataMixin
from .list_selection import EditorListSelectionMixin


class EditorPaginationMixin(
    EditorListFiltersMixin,
    EditorListPageDataMixin,
    EditorListSelectionMixin,
):
    pass
