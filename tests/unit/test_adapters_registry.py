import pytest

from stw.adapters import get_adapter, get_adapter_for_mode, registry


def test_registry_contains_all_builtins():
    reg = registry()
    for name in ("hac", "dynamo-preview", "pytom-preview", "protomo-preview"):
        assert name in reg


def test_get_adapter_unknown_raises():
    with pytest.raises(KeyError):
        get_adapter("not-a-real-package")


def test_get_adapter_for_mode_preview_prefers_suffixed_variant():
    adapter = get_adapter_for_mode("dynamo", "preview")
    assert adapter.name == "dynamo-preview"


def test_get_adapter_for_mode_preview_falls_back_when_no_preview_variant():
    adapter = get_adapter_for_mode("hac", "preview")
    assert adapter.name == "hac"


def test_get_adapter_for_mode_native_never_resolves_preview_suffix():
    with pytest.raises(KeyError):
        get_adapter_for_mode("dynamo", "native")


def test_get_adapter_for_mode_unknown_raises():
    with pytest.raises(KeyError):
        get_adapter_for_mode("not-a-real-package", "native")
