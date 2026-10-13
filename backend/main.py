"""
Climate Hazard Trend Analyzer API.
Data source: Open-Meteo Archive API (daily maximum temperature).
Heatwave definition: >=3 consecutive days where daily Tmax exceeds the
95th percentile of daily Tmax for the selected location over the requested
analysis period. This is a transparent demo definition, not an official
climate attribution product.
"""
import os, hashlib, json, math
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient, ASCENDING
from pymongo.errors import PyMongoError

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"), override=True)
app = FastAPI(title="Climate Hazard Trend Analyzer", version="1.0.0")
origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False,
                   allow_methods=["GET"], allow_headers=["*"])


try:
    uri = os.getenv("MONGODB_URI")
    if uri:
        MONGO = MongoClient(uri, serverSelectionTimeoutMS=1200)
        MONGO.admin.command("ping")
        COLLECTION = MONGO[os.getenv("MONGODB_DATABASE", "climate_hazards")]["analysis_cache"]
        COLLECTION.create_index([("key", ASCENDING)], unique=True)
        COLLECTION.create_index("expires_at", expireAfterSeconds=0)
except Exception as e:
    print("MongoDB initialization error:", repr(e))
    MONGO = None
    COLLECTION = None

CACHE_TTL_HOURS = max(1, int(os.getenv("CACHE_TTL_HOURS", "168")))
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

def cache_key(lat, lon, start, end):
    raw = f"{lat:.3f}|{lon:.3f}|{start}|{end}|heatwave-v1"
    return hashlib.sha256(raw.encode()).hexdigest()

def get_cache(key):
    if COLLECTION is None:
        return None
    try:
        doc = COLLECTION.find_one({"key": key, "expires_at": {"$gt": datetime.now(timezone.utc)}})
        return doc.get("payload") if doc else None
    except PyMongoError:
        return None

def set_cache(key, payload):
    if COLLECTION is None:
        return
    try:
        COLLECTION.update_one({"key": key}, {"$set": {
            "key": key, "payload": payload,
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=CACHE_TTL_HOURS)
        }}, upsert=True)
    except PyMongoError:
        pass

async def geocode_city(city: str):
    async with httpx.AsyncClient(timeout=12) as client:
        r = await client.get(GEOCODING_URL, params={"name": city, "count": 1, "language": "en", "format": "json"})
        r.raise_for_status()
        results = r.json().get("results") or []
    if not results:
        raise HTTPException(404, "City not found. Try a nearby larger city or use latitude/longitude.")
    p = results[0]
    return {"name": p.get("name", city), "country": p.get("country", ""), "latitude": p["latitude"], "longitude": p["longitude"]}

def percentile(values, p=0.95):
    values = sorted(v for v in values if v is not None and math.isfinite(v))
    if not values:
        return None
    pos = (len(values) - 1) * p
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return values[lo]
    return values[lo] * (hi - pos) + values[hi] * (pos - lo)

def linear_trend(points):
    pts = [(int(p["year"]), float(p["events"])) for p in points if p.get("events") is not None]
    if len(pts) < 2:
        return {"slope_events_per_year": None, "direction": "insufficient data", "r_squared": None}
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    xm, ym = sum(xs)/len(xs), sum(ys)/len(ys)
    denom = sum((x-xm)**2 for x in xs)
    if denom == 0:
        return {"slope_events_per_year": 0, "direction": "stable", "r_squared": None}
    slope = sum((x-xm)*(y-ym) for x,y in zip(xs,ys))/denom
    intercept = ym - slope*xm
    ss_tot = sum((y-ym)**2 for y in ys)
    ss_res = sum((y-(intercept+slope*x))**2 for x,y in zip(xs,ys))
    r2 = 1 - ss_res/ss_tot if ss_tot else 1.0
    direction = "increasing" if slope > 0.05 else "decreasing" if slope < -0.05 else "approximately stable"
    return {"slope_events_per_year": round(slope, 4), "direction": direction, "r_squared": round(r2, 3)}

def analyze(data, start, end, location):
    days = data.get("daily", {})
    dates = days.get("time", [])
    temps = days.get("temperature_2m_max", [])
    valid = [(d, float(t)) for d,t in zip(dates, temps) if t is not None and math.isfinite(float(t))]
    if len(valid) < 30:
        raise HTTPException(502, "Not enough valid daily temperature observations from the weather provider.")
    threshold = percentile([t for _,t in valid], 0.95)
    events = []
    run = []
    for d,t in valid:
        if t > threshold:
            if run and (date.fromisoformat(d) - date.fromisoformat(run[-1]["date"])).days != 1:
                if len(run) >= 3:
                    events.append(run)
                run = []
            run.append({"date": d, "tmax": round(t, 2)})
        else:
            if len(run) >= 3:
                events.append(run)
            run = []
    if len(run) >= 3:
        events.append(run)

    start_year, end_year = int(start[:4]), int(end[:4])
    by_year = {y: {"year": y, "events": 0, "heatwave_days": 0, "max_event_duration": 0, "mean_event_tmax": None}
               for y in range(start_year, end_year+1)}
    yearly_event_temps = {y: [] for y in by_year}
    for event in events:
        y = int(event[0]["date"][:4])
        if y in by_year:
            by_year[y]["events"] += 1
            by_year[y]["heatwave_days"] += len(event)
            by_year[y]["max_event_duration"] = max(by_year[y]["max_event_duration"], len(event))
            yearly_event_temps[y].extend(x["tmax"] for x in event)
    for y in by_year:
        vals = yearly_event_temps[y]
        by_year[y]["mean_event_tmax"] = round(sum(vals)/len(vals), 2) if vals else None
    yearly = list(by_year.values())
    first = yearly[0]["events"] if yearly else 0
    last = yearly[-1]["events"] if yearly else 0
    change_pct = round(((last-first)/first)*100, 1) if first else None
    trend = linear_trend(yearly)
    total_events = sum(y["events"] for y in yearly)
    avg_duration = round(sum(len(e) for e in events)/len(events), 1) if events else 0
    return {
        "location": location, "period": {"start": start, "end": end},
        "hazard": "heatwave", "source": "Open-Meteo Archive API",
        "methodology": {
            "definition": "At least 3 consecutive calendar days with daily maximum temperature strictly above the 95th percentile.",
            "threshold_celsius": round(threshold, 2),
            "percentile_baseline": f"{start} to {end}",
            "valid_temperature_days": len(valid),
            "missing_days": max(0, len(dates)-len(valid)),
            "caveat": "The threshold is calculated over the selected analysis period and location. Results are indicative and may differ from official climate-monitoring products."
        },
        "summary": {"total_events": total_events, "average_event_duration_days": avg_duration,
                    "first_year_events": first, "last_year_events": last,
                    "first_to_last_year_change_percent": change_pct, "trend": trend},
        "yearly": yearly,
        "events": [{"start": e[0]["date"], "end": e[-1]["date"], "duration_days": len(e),
                    "peak_tmax_c": round(max(x["tmax"] for x in e), 2)} for e in events]
    }

@app.get("/api/health")
def health():
    return {"status": "ok", "database_cache": "mongodb" if COLLECTION is not None else "disabled (set MONGODB_URI)"}

@app.get("/api/geocode")
async def geocode(city: str = Query(min_length=2, max_length=100)):
    try:
        return await geocode_city(city.strip())
    except httpx.HTTPError:
        raise HTTPException(502, "Geocoding provider is temporarily unavailable.")

@app.get("/api/analyze")
async def analyze_heatwaves(
    city: Optional[str] = Query(default=None, max_length=100),
    latitude: Optional[float] = Query(default=None, ge=-90, le=90),
    longitude: Optional[float] = Query(default=None, ge=-180, le=180),
    start: date = Query(default=date(1990, 1, 1)),
    end: date = Query(default=date(2020, 12, 31))
):
    today = date.today()
    if start > end:
        raise HTTPException(400, "start must be on or before end.")
    if (end-start).days > 366*80:
        raise HTTPException(400, "Choose a period no longer than 80 years.")
    if end > today - timedelta(days=5):
        raise HTTPException(400, "Choose an end date at least 5 days in the past; recent archive data may be incomplete.")
    if (latitude is None) != (longitude is None):
        raise HTTPException(400, "Provide both latitude and longitude.")
    if latitude is None and not city:
        raise HTTPException(400, "Provide a city or both latitude and longitude.")
    try:
        if latitude is None:
            loc = await geocode_city(city.strip())
            latitude, longitude = loc["latitude"], loc["longitude"]
            location_name = f'{loc["name"]}, {loc["country"]}'.strip(", ")
        else:
            location_name = f"{latitude:.3f}, {longitude:.3f}"
        key = cache_key(latitude, longitude, start.isoformat(), end.isoformat())
        cached = get_cache(key)
        if cached:
            cached["cache"] = "hit"
            return cached
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(ARCHIVE_URL, params={
                "latitude": latitude, "longitude": longitude,
                "start_date": start.isoformat(), "end_date": end.isoformat(),
                "daily": "temperature_2m_max", "timezone": "UTC"
            })
            response.raise_for_status()
            weather = response.json()
        result = analyze(weather, start.isoformat(), end.isoformat(), location_name)
        result["coordinates"] = {"latitude": latitude, "longitude": longitude}
        result["cache"] = "miss"
        set_cache(key, result)
        return result
    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"Weather provider returned HTTP {e.response.status_code}. Try a shorter period.")
    except (httpx.HTTPError, ValueError, KeyError) as e:
        raise HTTPException(502, "Unable to retrieve or process weather data. Please retry with a shorter period.")
