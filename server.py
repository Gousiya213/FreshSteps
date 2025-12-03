from flask import Flask, render_template, request, redirect, jsonify, url_for
from flask_cors import CORS
import pandas as pd
import os, uuid, datetime as dt, difflib, csv

app = Flask(__name__)
CORS(app)

# ---------------- PATHS ----------------
DATASETS_DIR = "datasets"
SUBMISSIONS_FILE = "submissions.csv"

# Ensure submissions.csv exists with consistent columns
if not os.path.exists(SUBMISSIONS_FILE):
    pd.DataFrame(columns=[
        "submission_id","timestamp","fullName","age",
        "city_input","city_matched",
        "from_location","to_location",
        "indoor","outdoor","work",
        "conditions","other","notes",
        "latitude","longitude",
        "pm2_5_latest","pm2_5_avg",
        "pm10_latest","pm10_avg",
        "co2_latest","co2_avg",
        "AT_latest","RH_latest",
        "station_name","state",
        "suggestion_pm25","suggestion_pm10","suggestion_co2",
        "raw_user"
    ]).to_csv(SUBMISSIONS_FILE, index=False)

# ---------------- DATA ----------------
def load_all_datasets():
    frames = []
    if not os.path.isdir(DATASETS_DIR):
        return pd.DataFrame()

    for f in os.listdir(DATASETS_DIR):
        if f.lower().endswith(".csv"):
            path = os.path.join(DATASETS_DIR, f)
            try:
                df = pd.read_csv(path, on_bad_lines="skip")
            except Exception as e:
                print("Failed to read", path, e)
                continue
            df.columns = [c.strip() for c in df.columns]
            if "local_time" in df.columns:
                df["local_time"] = pd.to_datetime(df["local_time"], errors="coerce")
            if "city" in df.columns:
                df["city_clean"] = df["city"].astype(str).str.strip().str.lower()
            if "station_name" in df.columns:
                df["station_name_clean"] = df["station_name"].astype(str).str.strip().str.lower()
            df["_source_file"] = f
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

DATA = load_all_datasets()
print("Loaded dataset rows:", len(DATA))

# ---------------- HELPERS ----------------
def find_best_city_match(city_input: str):
    if not city_input or "city_clean" not in DATA.columns:
        return None
    key = str(city_input).strip().lower()
    cities = DATA["city_clean"].dropna().unique().tolist()
    if key in cities:
        return key
    match = difflib.get_close_matches(key, cities, n=1, cutoff=0.6)
    if match: return match[0]
    for c in cities:
        if key in c: return c
    return None

def pm25_health_message(v):
    try: v = float(v)
    except: return "PM2.5 data unavailable."
    if v <= 15:  return "Excellent air (WHO 24h guideline)."
    if v <= 35:  return "Good — low risk for most people."
    if v <= 55:  return "Moderate — sensitive groups limit outdoor exertion."
    if v <= 150: return "Unhealthy — wear a mask outdoors."
    return "Very unhealthy — avoid outdoor exposure & use purifier."

def pm10_health_message(v):
    try: v = float(v)
    except: return "PM10 data unavailable."
    if v <= 45:   return "Excellent (WHO 24h guideline)."
    if v <= 100:  return "Moderate — sensitive groups take care."
    if v <= 250:  return "Unhealthy — consider limiting outdoor activity."
    return "Very unhealthy — stay indoors if possible."

def co2_message(v):
    try: v = float(v)
    except: return "CO₂ data unavailable."
    if v < 600:   return "Very good ventilation."
    if v < 1000:  return "Acceptable indoor levels."
    if v < 1500:  return "Poor ventilation — open windows."
    return "High CO₂ — ventilate immediately."

def val_or_none(row, key):
    return row[key] if key in row and pd.notna(row[key]) else None

# keep submissions in memory for dashboard navigation (also saved to CSV)
submissions = {}

# ---------------- ROUTES ----------------
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/form")
def form():
    return render_template("form.html")

@app.route("/submit_form", methods=["POST"])
def submit_form():
    # Accept JSON or form-encoded
    data = request.get_json(silent=True)
    if not data:
        data = request.form.to_dict(flat=True)

    fullName = data.get("fullName")
    age = data.get("age")
    city_input = data.get("city")

    from_location = data.get("from_location") or ""
    to_location   = data.get("to_location") or ""
    indoor = float(data.get("indoor") or 0)
    outdoor = float(data.get("outdoor") or 0)
    work = float(data.get("work") or max(0, 24 - (indoor + outdoor)))
    conditions = data.get("condition") or ""
    other = data.get("other") or ""
    notes = data.get("notes") or ""
    latitude = data.get("latitude") or ""
    longitude = data.get("longitude") or ""

    # match city and select latest
    city_key = find_best_city_match(city_input)
    if not city_key:
        return jsonify({"error": "City not found in dataset"}), 404

    city_df = DATA[DATA["city_clean"] == city_key].copy().sort_values("local_time")
    if city_df.empty:
        return jsonify({"error": "No rows for the selected city"}), 404

    latest = city_df.iloc[-1]

    pm2_5_latest = val_or_none(latest, "PM2_5")
    pm10_latest  = val_or_none(latest, "PM10")
    co2_latest   = val_or_none(latest, "CO2")
    at_latest    = val_or_none(latest, "AT")
    rh_latest    = val_or_none(latest, "RH")

    pm2_5_avg = city_df["PM2_5"].mean(skipna=True) if "PM2_5" in city_df else None
    pm10_avg  = city_df["PM10"].mean(skipna=True)  if "PM10" in city_df else None
    co2_avg   = city_df["CO2"].mean(skipna=True)   if "CO2"  in city_df else None

    submission_id = str(uuid.uuid4())
    timestamp = dt.datetime.now().isoformat()

    row = {
        "submission_id": submission_id,
        "timestamp": timestamp,
        "fullName": fullName,
        "age": age,
        "city_input": city_input,
        "city_matched": latest.get("city", None),
        "from_location": from_location,
        "to_location": to_location,
        "indoor": indoor,
        "outdoor": outdoor,
        "work": work,
        "conditions": conditions,
        "other": other,
        "notes": notes,
        "latitude": latitude,
        "longitude": longitude,
        "pm2_5_latest": pm2_5_latest,
        "pm2_5_avg": pm2_5_avg,
        "pm10_latest": pm10_latest,
        "pm10_avg": pm10_avg,
        "co2_latest": co2_latest,
        "co2_avg": co2_avg,
        "AT_latest": at_latest,
        "RH_latest": rh_latest,
        "station_name": latest.get("station_name", None),
        "state": latest.get("state", None),
        "suggestion_pm25": pm25_health_message(pm2_5_latest),
        "suggestion_pm10": pm10_health_message(pm10_latest),
        "suggestion_co2": co2_message(co2_latest),
        "raw_user": str(data)
    }

    # append to CSV
    file_exists = os.path.isfile(SUBMISSIONS_FILE)
    with open(SUBMISSIONS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    # save in-memory for dashboard
    submissions[submission_id] = row

    return redirect(url_for("dashboard", submission_id=submission_id))

@app.route("/dashboard/<submission_id>")
def dashboard(submission_id):
    if submission_id not in submissions:
        return "Invalid submission ID", 404

    result = submissions[submission_id]

    # prepare trend (last 48 rows for city)
    city = str(result.get("city_matched") or "").strip().lower()
    if city and "city_clean" in DATA.columns:
        trend_df = DATA[DATA["city_clean"] == city].dropna(subset=["local_time"]).sort_values("local_time").tail(48)
    else:
        trend_df = pd.DataFrame()

    times   = trend_df["local_time"].dt.strftime("%d %b %H:%M").tolist() if not trend_df.empty else []
    pm25_ts = trend_df["PM2_5"].tolist() if "PM2_5" in trend_df else []
    pm10_ts = trend_df["PM10"].tolist()  if "PM10" in trend_df else []
    co2_ts  = trend_df["CO2"].tolist()   if "CO2"  in trend_df else []

    # weekly: list of dicts containing PM2_5, PM10, CO2 per day (last 7 days)
    weekly = []
    if not trend_df.empty:
        tmp = trend_df.copy()
        tmp["day"] = tmp["local_time"].dt.date
        g = tmp.groupby("day").agg({"PM2_5":"mean","PM10":"mean","CO2":"mean"}).tail(7).reset_index()
        for _, r in g.iterrows():
            weekly.append({
                "day": str(r["day"]),
                "PM2_5": round(r["PM2_5"],1) if pd.notna(r["PM2_5"]) else None,
                "PM10":  round(r["PM10"],1)  if pd.notna(r["PM10"])  else None,
                "CO2":   round(r["CO2"],1)   if pd.notna(r["CO2"])   else None
            })

    # today vs yesterday for this user (from submissions CSV history)
        # today vs yesterday for this user (from submissions CSV history)
    try:
        history = pd.read_csv(SUBMISSIONS_FILE, on_bad_lines="skip")
        history["timestamp"] = pd.to_datetime(history["timestamp"], errors="coerce")
        history["fullName_lower"] = history["fullName"].astype(str).str.lower()

        today = dt.date.today()
        yesterday = today - dt.timedelta(days=1)

        # case-insensitive match on fullName
        user_hist = history[history["fullName_lower"] == str(result.get("fullName")).lower()]

        today_rows = user_hist[user_hist["timestamp"].dt.date == today]
        yest_rows  = user_hist[user_hist["timestamp"].dt.date == yesterday]

        # today_pm  = today_rows["pm2_5_latest"].iloc[-1] if not today_rows.empty else None
        today_pm = result.get("pm2_5_latest")
        today_co2 = result.get("co2_latest")

        yest_pm   = yest_rows["pm2_5_latest"].iloc[-1]  if not yest_rows.empty else None
        # today_co2 = today_rows["co2_latest"].iloc[-1]   if not today_rows.empty else None
        yest_co2  = yest_rows["co2_latest"].iloc[-1]    if not yest_rows.empty else None
    except Exception as e:
        print("History error:", e)
        today_pm = yest_pm = today_co2 = yest_co2 = None


    # exposure breakdown (use submitted values)
    try:
        exposure = {
            "indoor": float(result.get("indoor") or 0),
            "outdoor": float(result.get("outdoor") or 0),
            "work": float(result.get("work") or 0)
        }
    except:
        exposure = {"indoor":0,"outdoor":0,"work":0}

    return render_template("dashboard.html",
                           result=result,
                           submission_id=submission_id,
                           times=times, pm25_ts=pm25_ts, pm10_ts=pm10_ts, co2_ts=co2_ts,
                           weekly=weekly,
                           exposure=exposure,
                           today_pm=today_pm, yest_pm=yest_pm, today_co2=today_co2, yest_co2=yest_co2)

@app.route("/products/<submission_id>")
def products(submission_id):
    if submission_id not in submissions:
        return "Invalid submission ID", 404
    info = submissions[submission_id]

    # Determine recommendations based on exposure
    indoor_h = float(info.get("indoor") or 0)
    outdoor_h = float(info.get("outdoor") or 0)
    pm25 = float(info.get("pm2_5_latest") or info.get("pm2_5_avg") or 0)
    pm10 = float(info.get("pm10_latest") or info.get("pm10_avg") or 0)
    recs = []

    # Recommend only for higher exposure; otherwise show general items
    if indoor_h >= 8 or pm25 > 35:
        recs.append({"name":"HEPA Air Purifier (CADR 250+)","why":"High indoor hours / elevated PM2.5","est_price":"₹8,000–₹15,000","tag":"Home"})
    if pm25 > 35 or outdoor_h >= 2:
        recs.append({"name":"N95 / KN95 Mask (pack of 5)","why":"Good protection for outdoor exposures","est_price":"₹400–₹1,200","tag":"Outdoor/Mask"})
        recs.append({"name":"Surgical/Disposable Masks (pack)","why":"Affordable, daily protection","est_price":"₹150–₹400","tag":"Mask"})
    if pm10 > 100:
        recs.append({"name":"Workplace Respirator / P100","why":"High coarse particle exposures at work","est_price":"₹2,000–₹4,000","tag":"Work"})
    if not recs:
        recs.append({"name":"Carbon Pre-Filter Pack","why":"Extra protection for moderate days","est_price":"₹300–₹800","tag":"General"})

    return render_template("products.html", info=info, recommendations=recs, submission_id=submission_id)

@app.route("/routes/<submission_id>")
def routes(submission_id):
    if submission_id not in submissions:
        return "Invalid submission ID", 404
    info = submissions[submission_id]
    # We'll show mock routes here (front-end draws them)
    return render_template("routes.html", result=info, submission_id=submission_id)

# ---------------- RUN ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
