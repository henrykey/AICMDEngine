# Repository Guidelines

## Project Structure & Module Organization
- `src/` hosts the FastAPI backend (routers in `src/routers/`, models in `src/models/`, config in `src/core/`).
- `ui/` contains the React + Vite frontend (`ui/src/pages/` for screens, `ui/src/lib/` for API helpers).
- `scripts/` and `seed_db.py` provide data seeding helpers.
- `docs/` holds architecture and API reference material.
- `config.yml` is the primary local configuration file; environment variables can override values.

## Build, Test, and Development Commands
- Backend run: `python src/main.py` (starts FastAPI on `0.0.0.0:8000` with reload).
- Backend deps: `pip install -r requirements.txt`.
- Seed sample data: `python scripts/seed_db.py` (expects MongoDB running).
- Frontend dev: `cd ui && npm run dev` (Vite dev server).
- Frontend build: `cd ui && npm run build`.
- Frontend lint: `cd ui && npm run lint`.

## Coding Style & Naming Conventions
- Python: 2-space indentation, PEP 8 style, `snake_case` for modules and functions.
- TypeScript/React: follow ESLint (`ui/eslint.config.js`); components use `PascalCase` (e.g., `CommandSets.tsx`).
- Prefer descriptive names tied to domain concepts (e.g., `command_sets`, `tasks`).

## Code Modification Rules
- Do not modify code unless the user gives an explicit code-modification instruction.
- Requests to inspect, investigate, explain, compare specs, or identify causes are read-only by default.
- Do not infer permission to edit from a reported bug or inconsistency; report findings first unless the user explicitly asks to change code.
- Documentation changes also require an explicit instruction to modify documentation or the relevant file.
- Do not build, start, or restart containers; if that is needed, tell the user what to run.

## Testing Guidelines
- No dedicated test framework is configured in this repo.
- Use `node test_llm.js` for quick LLM connectivity checks when needed.
- If adding tests, place them alongside the relevant layer (`src/` for backend, `ui/` for frontend) and document new commands here.

## Commit & Pull Request Guidelines
- Commit history is lightweight and sentence-case (e.g., "Release v1.0.0..."). Keep summaries short and clear.
- PRs should include a brief summary, testing notes, and screenshots for UI changes.
- Link related issues or design docs from `docs/` when applicable.

## Configuration & Security Tips
- Backend config loads from `config.yml` and `.env` values (e.g., `MONGODB_URI`, `OPENAI_API_KEY`).
- Avoid committing secrets; keep API keys in environment variables or local config only.
