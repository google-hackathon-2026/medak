# Medak

## Project Overview
Google Hackathon project. Monorepo with frontend and backend.

## Team
- **Filip** — Frontend (`frontend/`)
- **Milan Doslic** — TBD
- **Milan Jovanovic** — TBD
- **Boris Antonijev** — TBD

## Collaboration Rules
- Filip works only on frontend. Do not write backend or other service code for him.
- If frontend needs something from backend/other services, generate a ready-to-send prompt for Filip to forward to the relevant teammate.

## Architecture
- **No database.** All persistence is via browser localStorage. Never suggest DB solutions.
- Backend should be stateless or use in-memory/file-based approaches if needed.

## Structure
- `frontend/` — Next.js 16 (React 19, TypeScript, Tailwind CSS v4, shadcn/ui)
- `backend/` — Java (TBD, Dockerized)

## GCP / Deployment
- **GCP project:** `medak-hackathon`
- **Region:** `us-central1`
- **Service:** Cloud Run (min-instances=0, max-instances=1, 256Mi, CPU throttling — cheapest settings)
- **CI/CD:** GitHub Actions (not Cloud Build)
- **Deploy order:** Backend deploys first, then frontend. Frontend workflow waits for `Deploy Backend` workflow to succeed.
- If only frontend files change, frontend deploys independently.
- **Important:** When creating the backend deploy workflow, name it exactly `Deploy Backend` so the frontend workflow trigger works.
- Frontend Docker image: `gcr.io/medak-hackathon/medak-frontend`
- Frontend service URL: `https://medak-frontend-1083268346966.us-central1.run.app`
- GitHub secret `GCP_SA_KEY` contains the service account key for deployment.

## Frontend Notes
- `output: "standalone"` is set in `next.config.ts` for Docker builds.
- Fonts: `--font-geist-sans` and `--font-geist-mono` CSS variables are set in `layout.tsx`, consumed via Tailwind theme in `globals.css`.
