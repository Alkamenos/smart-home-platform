"""Реестр фичи: используется тулингом (генераторы); в склейку НЕ входит."""
from features.lighting.schema import resolve_group  # noqa: F401
from features.lighting.helpers import group_feature_helpers  # noqa: F401
from features.lighting.ui import group_feature_blocks  # noqa: F401
from features.lighting.card import group_card  # noqa: F401

FEATURE = {
    "id": "lighting",
    "resolve": resolve_group,
    "helpers": group_feature_helpers,
    "ui": group_feature_blocks,
    "card": group_card,
}
