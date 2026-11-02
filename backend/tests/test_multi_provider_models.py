"""Phase 11: multi-provider BYOK model resolution.

Covers `agent/models.py`'s catalog/lookup helpers and `agent/graph.py`'s
`_resolve_llm` factory — the pieces that decide *which* provider's chat
model gets built for a given user, and that raise clean, typed errors
(rather than an opaque provider-SDK failure) when the selection can't be
satisfied.
"""

from __future__ import annotations

import unittest

from agent.graph import _build_llm, _resolve_llm
from agent.models import (
    DEFAULT_MODEL_ID,
    MODEL_BY_ID,
    MODEL_CATALOG,
    MissingProviderKeyError,
    ModelProvider,
    UnknownModelError,
    resolve_model,
)


class ResolveModelTests(unittest.TestCase):
    def test_falls_back_to_default_when_model_id_is_falsy(self) -> None:
        for empty in (None, ""):
            option = resolve_model(empty)
            self.assertEqual(option.id, DEFAULT_MODEL_ID)

    def test_resolves_each_catalog_entry_by_id(self) -> None:
        for option in MODEL_CATALOG:
            self.assertEqual(resolve_model(option.id), option)

    def test_unknown_model_id_raises(self) -> None:
        with self.assertRaises(UnknownModelError) as ctx:
            resolve_model("not-a-real-model")
        self.assertEqual(ctx.exception.model_id, "not-a-real-model")

    def test_retired_haiku_id_resolves_to_haiku_4_5(self) -> None:
        option = resolve_model("claude-haiku-5")
        self.assertEqual(option.id, "claude-haiku-4-5")
        self.assertEqual(option.provider, ModelProvider.ANTHROPIC)

    def test_retired_gemini_ids_resolve_to_current_models(self) -> None:
        # Every gemini-* id this app has ever offered — the original
        # undated aliases, their dated -002 follow-ups, and the
        # since-retired 2.5 family — should still resolve, remapped to a
        # current (non-Live-API) model.
        for retired_pro_id in ("gemini-1.5-pro", "gemini-1.5-pro-002", "gemini-2.5-pro"):
            option = resolve_model(retired_pro_id)
            self.assertEqual(option.id, "gemini-4-argon")
            self.assertEqual(option.provider, ModelProvider.GOOGLE)

        for retired_flash_id in ("gemini-1.5-flash", "gemini-1.5-flash-002", "gemini-2.5-flash"):
            option = resolve_model(retired_flash_id)
            self.assertEqual(option.id, "gemini-3.8-flash")
            self.assertEqual(option.provider, ModelProvider.GOOGLE)

        lite = resolve_model("gemini-2.5-flash-lite")
        self.assertEqual(lite.id, "gemini-3.5-flash-lite")
        self.assertEqual(lite.provider, ModelProvider.GOOGLE)

    def test_catalog_covers_all_three_providers(self) -> None:
        providers = {option.provider for option in MODEL_CATALOG}
        self.assertEqual(providers, {ModelProvider.ANTHROPIC, ModelProvider.OPENAI, ModelProvider.GOOGLE})

    def test_model_by_id_is_consistent_with_catalog(self) -> None:
        self.assertEqual(len(MODEL_BY_ID), len(MODEL_CATALOG))
        for option in MODEL_CATALOG:
            self.assertIs(MODEL_BY_ID[option.id], option)


class ResolveLlmFactoryTests(unittest.TestCase):
    """`_resolve_llm` is the factory `_agent_node` calls on every turn: reads
    `default_model` + `api_keys` out of a `RunnableConfig.configurable`-shaped
    dict and either returns a tool-bound chat model or raises a clean,
    typed error.
    """

    def test_builds_llm_for_each_provider_when_key_present(self) -> None:
        configurable = {
            "default_model": "gpt-4o",
            "api_keys": {"openai": "sk-fake-openai-key-aaaaaaaaaaaa"},
        }
        llm = _resolve_llm(configurable)
        self.assertTrue(hasattr(llm, "ainvoke"))

    def test_missing_provider_key_raises_with_resolved_model_attached(self) -> None:
        configurable = {
            "default_model": "gemini-4-argon",
            "api_keys": {"anthropic": "sk-ant-fake-aaaaaaaaaaaaaaaa"},
        }
        with self.assertRaises(MissingProviderKeyError) as ctx:
            _resolve_llm(configurable)
        self.assertEqual(ctx.exception.model.id, "gemini-4-argon")
        self.assertEqual(ctx.exception.model.provider, ModelProvider.GOOGLE)

    def test_no_api_keys_at_all_raises_missing_provider_key(self) -> None:
        configurable = {"default_model": "claude-sonnet-5", "api_keys": {}}
        with self.assertRaises(MissingProviderKeyError):
            _resolve_llm(configurable)

    def test_missing_default_model_falls_back_before_checking_keys(self) -> None:
        # No `default_model` at all -> resolves to DEFAULT_MODEL_ID
        # (Anthropic) rather than raising UnknownModelError.
        configurable = {"api_keys": {"anthropic": "sk-ant-fake-aaaaaaaaaaaaaaaa"}}
        llm = _resolve_llm(configurable)
        self.assertTrue(hasattr(llm, "ainvoke"))

    def test_unknown_model_id_propagates_unknown_model_error(self) -> None:
        configurable = {"default_model": "not-a-real-model", "api_keys": {"anthropic": "sk-ant-x"}}
        with self.assertRaises(UnknownModelError):
            _resolve_llm(configurable)

    def test_build_llm_is_cached_per_provider_model_key_triple(self) -> None:
        key = "sk-fake-openai-key-aaaaaaaaaaaa"
        first = _build_llm(ModelProvider.OPENAI, "gpt-4o", key)
        second = _build_llm(ModelProvider.OPENAI, "gpt-4o", key)
        self.assertIs(first, second)

        different_key = _build_llm(ModelProvider.OPENAI, "gpt-4o", "sk-different-key-bbbbbbbbbb")
        self.assertIsNot(first, different_key)


if __name__ == "__main__":
    unittest.main()
