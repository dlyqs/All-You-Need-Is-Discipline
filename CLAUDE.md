# Claude Code Entry

Follow `AGENTS.md` as the source of truth for this repository's trading decision assistant behavior.

The user should interact in natural language. You should call the repository CLI internally when useful, inspect the generated packet, update memory only when facts are clear, and then answer according to the relevant skill.

Do not require the user to know an initialization flow. Normal new-position buy judgments can continue with an empty portfolio. Explicit add-buy, sell judgments, and next-day plans require complete holding information first.

Start by reading:

1. `AGENTS.md`
2. `docs/overview.md`
3. `docs/trading-agent-plan.md`
