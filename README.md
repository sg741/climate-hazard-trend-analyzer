# Climate Hazard Trend Analyzer

A full-stack case-study implementation for Dygnify Ventures Pvt Ltd. The first supported hazard is **heatwaves**.

## Features

- React + Vite responsive dashboard with annual line/bar charts and annual detail table.
- FastAPI backend, input validation, clear JSON response shape, error handling, CORS allowlist.
- Open-Meteo Geocoding and Archive APIs for city lookup and daily maximum temperature.
- Heatwave event detection, yearly frequency/duration metrics, linear regression slope and R².
- MongoDB-backed cache with TTL expiry when `MONGODB_URI` is configured.
- CSV export from the browser.
- Notes in the UI explaining methodology and caveats.

## Architecture

```text
React (Vite + Chart.js)
       | GET /api/analyze
       v
FastAPI ---- geocoding-api.open-meteo.com (city -> coordinates)
   |  \
   |   \---- archive-api.open-meteo.com (daily Tmax)
   |
   +---- MongoDB cache (optional; TTL index)
```

The API remains usable without MongoDB, but cache persistence is disabled in that mode. For the evaluation requirement, configure a MongoDB Atlas URI or local MongoDB instance.

## Data source

- Open-Meteo Geocoding API: https://geocoding-api.open-meteo.com/v1/search
- Open-Meteo Historical Weather / Archive API: https://archive-api.open-meteo.com/v1/archive
- The app requests `daily=temperature_2m_max` and uses Celsius values returned by the provider.
- Weather API usage and historical coverage can vary; errors are surfaced rather than replaced with fabricated results.

## Heatwave logic and assumptions

1. For the selected coordinates and requested date range, calculate the 95th percentile of all valid daily maximum temperatures.
2. A qualifying day has Tmax **strictly greater than** that threshold.
3. An event consists of at least 3 consecutive calendar days that qualify. Missing observations break a run; missing values are not imputed.
4. Events are assigned to the year in which they start. The full event duration contributes to that start year.
5. Yearly metrics include event count, heatwave days, longest event, and mean Tmax across event days.
6. Trend direction uses ordinary least-squares regression of annual event count against calendar year. The slope is the estimated events/year; R² is included as a descriptive fit measure, not proof of statistical significance.
7. First-to-last percentage compares the first and last individual year. It is omitted when the first year has zero events; this comparison is volatile and is not described as the whole-period climate change percentage.
8. The percentile baseline is the selected analysis period, for a simple reproducible case-study implementation. A fixed climatological baseline (e.g. 1991–2020), seasonal thresholds, spatial aggregation, and formal significance tests would be more defensible for operational climate science.

## Run locally

Prerequisites: Python 3.10+ and Node.js 18+.

### 1. Backend

```bash
cd backend
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload --port 8000
```

`cp` can be replaced with copying `.env.example` to `.env` on Windows. Set `MONGODB_URI` in `.env` to enable persistent caching. For example, local MongoDB: `mongodb://localhost:27017`. The app creates the cache collection indexes automatically.

### 2. Frontend

In a second terminal:

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Open the Vite URL printed in the terminal (normally http://localhost:5173). The backend docs are at http://localhost:8000/docs.

## Deploy

- **Backend**: deploy `backend/` to Render as a Python web service. Build command: `pip install -r requirements.txt`; start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`. Set `MONGODB_URI`, `MONGODB_DATABASE`, `CACHE_TTL_HOURS`, and `CORS_ORIGINS` in the service environment.
- **Database**: create a MongoDB Atlas cluster and add the backend deployment's outbound access as appropriate. Use a least-privilege database user and never commit its URI.
- **Frontend**: deploy `frontend/` to Vercel or Netlify. Build command `npm run build`; output directory `dist`. Set `VITE_API_URL` to the deployed backend origin, without a trailing slash.
- After deploying, set `CORS_ORIGINS` on the backend to the exact deployed frontend origin(s), then redeploy/restart the backend.

## Security and performance

- Inputs are bounded and coordinates are validated; the API does not accept arbitrary upstream URLs.
- CORS is allowlisted by environment variable.
- HTTP requests have timeouts; upstream failures return controlled errors.
- Cache keys include coordinates, date range and algorithm version. MongoDB documents expire using a TTL index.
- In production, add an IP/user-based rate limiter (e.g. slowapi or gateway rules), request-level quotas, structured logs, observability, and a background refresh job. The current app limits date range to 80 years and relies on provider timeouts rather than a distributed rate limiter.

## AI tools disclosure

This project scaffold and portions of the implementation were created with assistance from **ChatGPT (OpenAI)**. It was used to draft application structure, implementation code, and documentation. The developer should personally run the application, validate the analysis against sample cases, review and understand all code, and make any necessary changes before submission. Any further AI tools used should also be disclosed in the submission form and this README.

## What I would improve with more time

- Use a fixed 30-year climatological reference period and seasonally varying percentile thresholds.
- Add unit tests for missing dates, boundary events, leap years, percentile calculations and zero-event trend handling.
- Add rate limiting, structured logs, retries/backoff, monitoring and provider quota awareness.
- Add bounding-box aggregation with explicit spatial averaging/interpolation rather than treating a city coordinate as a whole region.
- Add Leaflet region selection, drought and heavy-rainfall logic, PDF report generation, and Mann–Kendall trend testing.
- Add reproducible data provenance, schema versioning and a dedicated data-ingestion worker.

## Before submitting

- Run backend and frontend locally and verify a real location/time range.
- Configure MongoDB and verify the API reports `database_cache: mongodb`.
- Add screenshots/demo video if useful.
- Push source to a public GitHub repository and deploy both services.
- Update the AI disclosure to match your actual usage, and only claim tests/deployment you have actually completed.
