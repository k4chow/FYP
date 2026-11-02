# NOACF

*Your personal film journal.*

NOACF is an AI-assisted film reflection platform. Instead of rating films and moving
on, it helps you think about what you watched, builds a reflective profile that **you**
control, and uses it to recommend films with explanations you can inspect.

This is a Final Year Project — see `docs/` for the full documentation set
(requirements traceability, architecture, design decisions, evaluation plan).

## Project structure

```
client/              React + Vite + TypeScript frontend
server/              FastAPI backend (Python 3.12)
  app/main.py        API entry point
  app/config.py      Settings (pydantic-settings, reads server/.env)
supabase/migrations/ Database schema (SQL, run in Supabase SQL editor)
docs/                Project documentation (thesis material)
```

## Setup

### Prerequisites
- Node.js 24+ (use `npm.cmd` on Windows if PowerShell blocks `npm.ps1`)
- Python 3.12+ with packages from `server/requirements.txt`
- A free [Supabase](https://supabase.com) project and a free
  [TMDB](https://www.themoviedb.org/settings/api) API key

### Server
```powershell
cd server
pip install -r requirements.txt
copy .env.example .env   # then fill in your Supabase + TMDB keys
python -m uvicorn app.main:app --reload --port 8000
# -> http://localhost:8000/health
```

### Client
```powershell
cd client
npm.cmd install
npm.cmd run dev
# -> http://localhost:5173
```

### Database
Run `supabase/migrations/0001_init.sql` in the Supabase SQL editor. It creates
`users`, `films`, `user_films`, `conversations`, `messages`, `memories` with
indexes and Row Level Security policies.

## Architecture (summary)

1. **Conversation history** — every message is stored verbatim and never
   overwritten (source of truth).
2. **Reflective profile** — insights extracted from conversations are only
   *proposed*; the user confirms, edits or rejects them before they are used.
3. **Reflection & discovery** — confirmed insights drive recommendations, and
   every recommendation explains *why* it was made.

The LLM provider is behind a swappable interface; a mock provider is used until
a real API key is available.

## Security notes

- `.env` files are gitignored — never commit API keys.
- All user-data tables enforce RLS; users can only ever see their own rows.
- Film preferences are kept separate from anything resembling mental-health
  inference; contradictions in the profile are flagged, never silently overwritten.
