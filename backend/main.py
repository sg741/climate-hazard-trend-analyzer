
"""
Climate Hazard Trend Analyzer API.
Data source: Open-Meteo Archive API (daily maximum temperature).
Heatwave definition: >=3 consecutive days where daily Tmax exceeds the
95th percentile of daily Tmax for the selected location over the requested
analysis period. This is a transparent demo definition, not an official
climate attribution product.
"""

import os
import hashlib
import math
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient, ASCENDING
from pymongo.errors import PyMongoError


# Load environment variables from backend/.env
load_dotenv(
    os.path.join(os.path.dirname(__file__), ".env"),
    override=True
)

app = FastAPI(
    title="Climate Hazard Trend Analyzer",
    version="1.0.0"
)

origins = [
    x.strip()
    for x in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://localhost:5174"
    ).split(",")
    if x.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"]
)


# -------------------- MongoDB Configuration --------------------

MONGO = None
COLLECTION = None

try:
    uri = os.getenv("MONGODB_URI")

    if uri:
        MONGO = MongoClient(
            uri,
            serverSelectionTimeoutMS=5000
        )

        # Verify the MongoDB connection
        MONGO.admin.command("ping")

        database_name = os.getenv(
            "MONGODB_DATABASE",
            "climate_hazards"
        )

        COLLECTION = MONGO[database_name]["analysis_cache"]

        # Unique cache key and automatic expiration
        COLLECTION.create_index(
            [("key", ASCENDING)],
            unique=True
        )

        COLLECTION.create_index(
            "expires_at",
            expireAfterSeconds=0
        )

        print("MongoDB connected successfully.")
        print(f"Database: {database_name}")
        print("Collection: analysis_cache")

    else:
        print("MongoDB URI not configured. Cache is disabled.")

except Exception as e:
    print("MongoDB initialization error:", repr(e))
    MONGO = None
    COLLECTION = None


CACHE_TTL_HOURS = max(
    1,
    int(os.getenv("CACHE_TTL_HOURS", "168"))
)

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


# -------------------- Cache Functions --------------------

def cache_key(lat, lon, start, end):
    raw = f"{lat:.3f}|{lon:.3f}|{start}|{end}|heatwave-v1"
    return hashlib.sha256(raw.encode()).hexdigest()


def get_cache(key):
    if COLLECTION is None:
        return None

    try:
        doc = COLLECTION.find_one({
            "key": key,
            "expires_at": {
                "$gt": datetime.now(timezone.utc)
            }
        })

        if doc:
            print("MongoDB cache hit:", key)
            return doc.get("payload")

        print("MongoDB cache miss:", key)
        return None

    except PyMongoError as e:
        print("MongoDB cache read error:", repr(e))
        return None


def set_cache(key, payload):
    if COLLECTION is None:
        print("Cache not saved: MongoDB collection is unavailable.")
        return

    try:
        COLLECTION.update_one(
            {"key": key},
            {
                "$set": {
                    "key": key,
                    "payload": payload,
                    "expires_at": (
                        datetime.now(timezone.utc)
                        + timedelta(hours=CACHE_TTL_HOURS)
                    )
                }
            },
            upsert=True
        )

        print("MongoDB cache saved successfully:", key)

    except PyMongoError as e:
        print("MongoDB cache save error:", repr(e))


# -------------------- Geocoding --------------------

async def geocode_city(city: str):
    async with httpx.AsyncClient(timeout=12) as client:
        response = await client.get(
            GEOCODING_URL,
            params={
                "name": city,
                "count": 1,
                "language": "en",
                "format": "json"
            }
        )

        response.raise_for_status()
        results = response.json().get("results") or []

    if not results:
        raise HTTPException(
            404,
            "City not found. Try a nearby larger city or use latitude/longitude."
        )

    place = results[0]

    return {
        "name": place.get("name", city),
        "country": place.get("country", ""),
        "latitude": place["latitude"],
        "longitude": place["longitude"]
    }


# -------------------- Analysis Functions --------------------

def percentile(values, p=0.95):
    values = sorted(
        value
        for value in values
        if value is not None and math.isfinite(value)
    )

    if not values:
        return None

    pos = (len(values) - 1) * p
    low = math.floor(pos)
    high = math.ceil(pos)

    if low == high:
        return values[low]

    return (
        values[low] * (high - pos)
        + values[high] * (pos - low)
    )


def linear_trend(points):
    pts = [
        (int(point["year"]), float(point["events"]))
        for point in points
        if point.get("events") is not None
    ]

    if len(pts) < 2:
        return {
            "slope_events_per_year": None,
            "direction": "insufficient data",
            "r_squared": None
        }

    xs = [point[0] for point in pts]
    ys = [point[1] for point in pts]

    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)

    denominator = sum(
        (x - x_mean) ** 2 for x in xs
    )

    if denominator == 0:
        return {
            "slope_events_per_year": 0,
            "direction": "stable",
            "r_squared": None
        }

    slope = sum(
        (x - x_mean) * (y - y_mean)
        for x, y in zip(xs, ys)
    ) / denominator

    intercept = y_mean - slope * x_mean

    ss_total = sum(
        (y - y_mean) ** 2 for y in ys
    )

    ss_residual = sum(
        (y - (intercept + slope * x)) ** 2
        for x, y in zip(xs, ys)
    )

    r_squared = (
        1 - ss_residual / ss_total
        if ss_total
        else 1.0
    )

    direction = (
        "increasing"
        if slope > 0.05
        else "decreasing"
        if slope < -0.05
        else "approximately stable"
    )

    return {
        "slope_events_per_year": round(slope, 4),
        "direction": direction,
        "r_squared": round(r_squared, 3)
    }


def analyze(data, start, end, location):
    days = data.get("daily", {})
    dates = days.get("time", [])
    temperatures = days.get("temperature_2m_max", [])

    valid = []

    for day, temperature in zip(dates, temperatures):
        if temperature is None:
            continue

        temperature = float(temperature)

        if math.isfinite(temperature):
            valid.append((day, temperature))

    if len(valid) < 30:
        raise HTTPException(
            502,
            "Not enough valid daily temperature observations from the weather provider."
        )

    threshold = percentile(
        [temperature for _, temperature in valid],
        0.95
    )

    events = []
    run = []

    for day, temperature in valid:
        if temperature > threshold:
            if (
                run
                and (
                    date.fromisoformat(day)
                    - date.fromisoformat(run[-1]["date"])
                ).days != 1
            ):
                if len(run) >= 3:
                    events.append(run)

                run = []

            run.append({
                "date": day,
                "tmax": round(temperature, 2)
            })

        else:
            if len(run) >= 3:
                events.append(run)

            run = []

    if len(run) >= 3:
        events.append(run)

    start_year = int(start[:4])
    end_year = int(end[:4])

    by_year = {
        year: {
            "year": year,
            "events": 0,
            "heatwave_days": 0,
            "max_event_duration": 0,
            "mean_event_tmax": None
        }
        for year in range(start_year, end_year + 1)
    }

    yearly_event_temps = {
        year: [] for year in by_year
    }

    for event in events:
        year = int(event[0]["date"][:4])

        if year in by_year:
            by_year[year]["events"] += 1
            by_year[year]["heatwave_days"] += len(event)

            by_year[year]["max_event_duration"] = max(
                by_year[year]["max_event_duration"],
                len(event)
            )

            yearly_event_temps[year].extend(
                item["tmax"] for item in event
            )

    for year in by_year:
        values = yearly_event_temps[year]

        by_year[year]["mean_event_tmax"] = (
            round(sum(values) / len(values), 2)
            if values
            else None
        )

    yearly = list(by_year.values())

    first = yearly[0]["events"] if yearly else 0
    last = yearly[-1]["events"] if yearly else 0

    change_pct = (
        round(((last - first) / first) * 100, 1)
        if first
        else None
    )

    trend = linear_trend(yearly)
    total_events = sum(item["events"] for item in yearly)

    avg_duration = (
        round(
            sum(len(event) for event in events) / len(events),
            1
        )
        if events
        else 0
    )

    return {
        "location": location,
        "period": {
            "start": start,
            "end": end
        },
        "hazard": "heatwave",
        "source": "Open-Meteo Archive API",
        "methodology": {
            "definition": (
                "At least 3 consecutive calendar days with daily "
                "maximum temperature strictly above the 95th percentile."
            ),
            "threshold_celsius": round(threshold, 2),
            "percentile_baseline": f"{start} to {end}",
            "valid_temperature_days": len(valid),
            "missing_days": max(0, len(dates) - len(valid)),
            "caveat": (
                "The threshold is calculated over the selected analysis "
                "period and location. Results are indicative and may "
                "differ from official climate-monitoring products."
            )
        },
        "summary": {
            "total_events": total_events,
            "average_event_duration_days": avg_duration,
            "first_year_events": first,
            "last_year_events": last,
            "first_to_last_year_change_percent": change_pct,
            "trend": trend
        },
        "yearly": yearly,
        "events": [
            {
                "start": event[0]["date"],
                "end": event[-1]["date"],
                "duration_days": len(event),
                "peak_tmax_c": round(
                    max(item["tmax"] for item in event),
                    2
                )
            }
            for event in events
        ]
    }


# -------------------- API Endpoints --------------------

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "database_cache": (
            "mongodb"
            if COLLECTION is not None
            else "disabled (set MONGODB_URI)"
        )
    }


@app.get("/api/geocode")
async def geocode(
    city: str = Query(min_length=2, max_length=100)
):
    try:
        return await geocode_city(city.strip())

    except httpx.HTTPError:
        raise HTTPException(
            502,
            "Geocoding provider is temporarily unavailable."
        )


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
        raise HTTPException(
            400,
            "start must be on or before end."
        )

    if (end - start).days > 366 * 80:
        raise HTTPException(
            400,
            "Choose a period no longer than 80 years."
        )

    if end > today - timedelta(days=5):
        raise HTTPException(
            400,
            "Choose an end date at least 5 days in the past; recent archive data may be incomplete."
        )

    if (latitude is None) != (longitude is None):
        raise HTTPException(
            400,
            "Provide both latitude and longitude."
        )

    if latitude is None and not city:
        raise HTTPException(
            400,
            "Provide a city or both latitude and longitude."
        )

    try:
        if latitude is None:
            location = await geocode_city(city.strip())

            latitude = location["latitude"]
            longitude = location["longitude"]

            location_name = (
                f'{location["name"]}, {location["country"]}'
            ).strip(", ")

        else:
            location_name = (
                f"{latitude:.3f}, {longitude:.3f}"
            )

        key = cache_key(
            latitude,
            longitude,
            start.isoformat(),
            end.isoformat()
        )

        # 1. Try to retrieve the saved analysis
        cached = get_cache(key)

        if cached:
            cached["cache"] = "hit"
            return cached

        # 2. Fetch weather data when no cached result exists
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(
                ARCHIVE_URL,
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "start_date": start.isoformat(),
                    "end_date": end.isoformat(),
                    "daily": "temperature_2m_max",
                    "timezone": "UTC"
                }
            )

            response.raise_for_status()
            weather = response.json()

        # 3. Analyze the weather data
        result = analyze(
            weather,
            start.isoformat(),
            end.isoformat(),
            location_name
        )

        result["coordinates"] = {
            "latitude": latitude,
            "longitude": longitude
        }

        result["cache"] = "miss"

        # 4. Save the analysis in MongoDB
        set_cache(key, result)

        return result

    except HTTPException:
        raise

    except httpx.HTTPStatusError as e:
        raise HTTPException(
            502,
            f"Weather provider returned HTTP {e.response.status_code}. Try a shorter period."
        )

    except (httpx.HTTPError, ValueError, KeyError) as e:
        print("Analysis processing error:", repr(e))

        raise HTTPException(
            502,
            "Unable to retrieve or process weather data. Please retry with a shorter period."
        )
