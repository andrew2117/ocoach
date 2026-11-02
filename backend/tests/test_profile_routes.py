"""Phase 11: `/api/profile` multi-provider BYOK integration tests.

Exercises `routes/profile.py` end-to-end through FastAPI's `TestClient`,
with `get_current_user` and `get_profile_service` overridden so no real
Supabase/JWT is needed — only the route logic (masking, per-provider
"omit = unchanged" semantics, `default_model` validation, and the
"at least one key" guard) is under test.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from core.security import AuthenticatedUser, get_current_user
from main import app
from services.profiles import ProfileDBService, UserProfile

TEST_USER_ID = "11111111-1111-1111-1111-111111111111"


class FakeProfileService(ProfileDBService):
    """In-memory stand-in for `ProfileDBService` — same public interface,
    no Supabase client. Avoids subclass `__init__` (which requires a
    Supabase url/key) by not calling `super().__init__()`.
    """

    def __init__(self) -> None:  # noqa: super-init-not-called
        self._profile: UserProfile | None = None

    @property
    def is_enabled(self) -> bool:
        return True

    async def get_profile(self, user_id: str) -> UserProfile | None:
        return self._profile

    async def upsert_profile(
        self,
        user_id: str,
        codeforces_handle: str | None,
        anthropic_api_key: str | None = None,
        openai_api_key: str | None = None,
        google_api_key: str | None = None,
        default_model: str | None = None,
    ) -> None:
        existing = self._profile
        self._profile = UserProfile(
            user_id=user_id,
            anthropic_api_key=anthropic_api_key or (existing.anthropic_api_key if existing else None),
            openai_api_key=openai_api_key or (existing.openai_api_key if existing else None),
            google_api_key=google_api_key or (existing.google_api_key if existing else None),
            codeforces_handle=codeforces_handle,
            default_model=default_model or (existing.default_model if existing else "claude-sonnet-5"),
        )


class ProfileRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fake_service = FakeProfileService()
        app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(user_id=TEST_USER_ID)
        # `routes/profile.py` calls `get_profile_service()` as a plain
        # module-level function (not via `Depends(...)`), so
        # `app.dependency_overrides` can't intercept it — patch the name in
        # that module's namespace instead.
        self._patcher = patch("routes.profile.get_profile_service", return_value=self.fake_service)
        self._patcher.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self._patcher.stop()
        app.dependency_overrides.clear()

    def test_get_profile_with_no_row_yet_defaults_cleanly(self) -> None:
        res = self.client.get("/api/profile")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["default_model"], "claude-sonnet-5")
        self.assertFalse(body["has_anthropic_api_key"])
        self.assertFalse(body["has_openai_api_key"])
        self.assertFalse(body["has_google_api_key"])
        self.assertIsNone(body["anthropic_api_key_preview"])
        model_ids = {m["id"] for m in body["available_models"]}
        self.assertIn("gpt-4o", model_ids)
        self.assertIn("gemini-4-argon", model_ids)
        self.assertIn("claude-sonnet-5", model_ids)

    def test_save_requires_at_least_one_key_on_first_save(self) -> None:
        res = self.client.post("/api/profile", json={"codeforces_handle": "tourist"})
        self.assertEqual(res.status_code, 400)

    def test_save_openai_key_only_sets_up_profile(self) -> None:
        res = self.client.post(
            "/api/profile",
            json={"openai_api_key": "sk-openai-fake-key-aaaaaaaaaaaa", "default_model": "gpt-4o"},
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["has_openai_api_key"])
        self.assertFalse(body["has_anthropic_api_key"])
        self.assertEqual(body["default_model"], "gpt-4o")
        self.assertTrue(body["openai_api_key_preview"].startswith("sk-open"))

    def test_adding_a_second_provider_key_does_not_clear_the_first(self) -> None:
        self.client.post("/api/profile", json={"anthropic_api_key": "sk-ant-fake-aaaaaaaaaaaaaaaa"})
        res = self.client.post("/api/profile", json={"google_api_key": "AQ.Ab-fake-key-bbbbbbbbbbbb"})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["has_anthropic_api_key"])
        self.assertTrue(body["has_google_api_key"])
        self.assertFalse(body["has_openai_api_key"])

    def test_deprecated_aiza_gemini_key_is_rejected(self) -> None:
        res = self.client.post(
            "/api/profile",
            json={"google_api_key": "AIza-fake-key-bbbbbbbbbbbb"},
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("AQ.", res.json()["detail"])

    def test_unknown_default_model_is_rejected(self) -> None:
        res = self.client.post(
            "/api/profile",
            json={"anthropic_api_key": "sk-ant-fake-aaaaaaaaaaaaaaaa", "default_model": "not-a-model"},
        )
        self.assertEqual(res.status_code, 400)

    def test_codeforces_handle_can_be_cleared_independently_of_keys(self) -> None:
        self.client.post(
            "/api/profile",
            json={"anthropic_api_key": "sk-ant-fake-aaaaaaaaaaaaaaaa", "codeforces_handle": "tourist"},
        )
        res = self.client.post("/api/profile", json={"codeforces_handle": None})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertIsNone(body["codeforces_handle"])
        # Clearing the handle (no key fields sent) must not touch the
        # already-saved Anthropic key.
        self.assertTrue(body["has_anthropic_api_key"])


if __name__ == "__main__":
    unittest.main()
