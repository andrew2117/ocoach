-- `claude-haiku-5` is not a Claude API model id (Anthropic 404s it).
-- Haiku 4.5 is `claude-haiku-4-5`. Rewrite any preference saved with the
-- old catalog id so chat keeps using the fast Anthropic model.

update public.profiles
set default_model = 'claude-haiku-4-5'
where default_model = 'claude-haiku-5';
