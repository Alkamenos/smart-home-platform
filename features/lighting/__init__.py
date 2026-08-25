from features.lighting import schema, helpers, ui, card  # noqa: F401

FEATURE = {
    "id": "lighting",
    "resolve": schema.resolve_group,
    "helpers": helpers.group_feature_helpers,
    "ui": ui.group_feature_blocks,
    "card": card.group_card,
}
