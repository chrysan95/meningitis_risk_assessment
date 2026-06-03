"""
app.py
------------------------------------------------------------------
Flask backend for the Meningitis Risk Assessment tool.

Endpoints
    GET  /                  -> main UI
    GET  /api/config        -> field definitions + validation rules + model meta
    POST /api/predict       -> single-patient prediction (JSON in, JSON out)
    POST /api/predict-batch -> CSV upload, returns per-row results + summary
    GET  /api/template      -> downloadable CSV template
------------------------------------------------------------------
"""

import csv
import io
import os
import pickle

import numpy as np
import pandas as pd
from flask import Flask, Response, jsonify, render_template, request

from insights import generate_batch_summary, generate_insights, risk_reference

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(HERE, "model", "model.pkl")

MAX_BATCH_ROWS = 500

# ---------------------------------------------------------------------------
# Drives: the rendered form, the inline reference hints, client-side
# validation AND server-side validation.  "min"/"max" are HARD plausibility
# bounds (out-of-bounds is rejected); "low"/"high" are the NORMAL reference
# range (out-of-range is allowed but flagged, since abnormal labs are the
# whole point of a risk tool).
# ---------------------------------------------------------------------------
FIELDS = [
    {
        "key": "wbc_csf", "model_key": "WBC_Count", "label": "WBC Count",
        "unit": "cells/\u00b5L", "section": "cbc", "placeholder": "8921",
        "min": 0, "max": 100000, "low": 4500, "high": 11000,
        "hint": "Ref: 4,500\u201311,000",
    },
    {
        "key": "platelets", "model_key": "Platelets", "label": "Platelets",
        "unit": "x10\u00b3/\u00b5L", "section": "cbc", "placeholder": "215231",
        "min": 0, "max": 1000000, "low": 150000, "high": 400000,
        "hint": "Ref: 150,000\u2013400,000",
    },
    {
        "key": "hemoglobin", "model_key": "Hemoglobin", "label": "Hemoglobin",
        "unit": "g/dL", "section": "cbc", "placeholder": "15",
        "min": 0, "max": 25, "low": 12, "high": 17,
        "hint": "Ref: 12\u201317",
    },
    {
        "key": "crp_level", "model_key": "CRP_Level", "label": "CRP Level",
        "unit": "mg/L", "section": "cbc", "placeholder": "5",
        "min": 0, "max": 500, "low": 0, "high": 10,
        "hint": "Normal: <10mg/L",
    },
    {
        "key": "wbc_blood", "model_key": "WBC_Blood_Count", "label": "WBC Blood Count",
        "unit": "cells/\u00b5L", "section": "cbc", "placeholder": "5050",
        "min": 0, "max": 100000, "low": 4500, "high": 11000,
        "hint": "Ref: 4,500\u201311,000",
    },
    {
        "key": "protein_level", "model_key": "Protein_Level", "label": "Protein Level",
        "unit": "mg/L", "section": "csf", "placeholder": "20",
        "min": 0, "max": 1000, "low": 15, "high": 45,
        "hint": "Normal: 15\u201345",
    },
    {
        "key": "glucose", "model_key": "Glucose_Level", "label": "Glucose",
        "unit": "mg/L", "section": "csf", "placeholder": "62",
        "min": 0, "max": 500, "low": 45, "high": 80,
        "hint": "Normal: 45\u201380",
    },
]

AGE_FIELD = {"key": "age", "model_key": "Age", "min": 0, "max": 120}
DIAGNOSIS_OPTIONS = ["Viral", "Bacterial", "Unknown"]
GENDER_OPTIONS = ["Male", "Female"]

# Column names expected in an uploaded batch CSV -> our field keys.
BATCH_COLUMNS = [
    "patient_id", "age", "gender", "wbc_csf", "platelets", "hemoglobin",
    "crp_level", "wbc_blood", "protein_level", "glucose",
    "pathogen_present", "diagnosis",
]

CLASS_NAMES = ["Low", "Moderate", "High"]

# ---------------------------------------------------------------------------
# Load model bundle
# ---------------------------------------------------------------------------
with open(MODEL_PATH, "rb") as f:
    BUNDLE = pickle.load(f)

MODEL = BUNDLE["model"]
FEATURE_ORDER = BUNDLE["feature_order"]
COST_MATRIX = BUNDLE["cost_matrix"]
METRICS = BUNDLE["metrics"]

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Core prediction helpers
# ---------------------------------------------------------------------------
def assemble_feature_vector(values: dict) -> np.ndarray:
    # Build the one-hot feature vector in the model's exact column order
    row = {col: 0 for col in FEATURE_ORDER}

    row["Age"] = values["Age"]
    row["WBC_Count"] = values["WBC_Count"]
    row["Protein_Level"] = values["Protein_Level"]
    row["Glucose_Level"] = values["Glucose_Level"]
    row["Hemoglobin"] = values["Hemoglobin"]
    row["WBC_Blood_Count"] = values["WBC_Blood_Count"]
    row["Platelets"] = values["Platelets"]
    row["CRP_Level"] = values["CRP_Level"]

    if values["Gender"] == "Female":
        row["Gender_Female"] = 1
    else:
        row["Gender_Male"] = 1

    diag = values["Diagnosis"]
    row[f"Diagnosis_{diag}"] = 1

    if values["Pathogen_Present"] == 1:
        row["Pathogen_Present"] = 1
    else:
        row["Pathogen_Not_Present"] = 1

    return pd.DataFrame([[row[col] for col in FEATURE_ORDER]],
                        columns=FEATURE_ORDER, dtype=float)


def predict_one(values: dict) -> dict:
    X = assemble_feature_vector(values)
    probs = MODEL.predict_proba(X)[0]
    expected_costs = probs @ COST_MATRIX.T
    pred_idx = int(np.argmin(expected_costs))
    risk = CLASS_NAMES[pred_idx]
    prob_pct = {CLASS_NAMES[i]: round(float(probs[i]) * 100, 1) for i in range(3)}
    return {
        "risk": risk,
        "probabilities": prob_pct,
        "confidence": prob_pct[risk],
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def _num(raw):
    if raw is None or str(raw).strip() == "":
        return None, "missing"
    try:
        return float(raw), None
    except (TypeError, ValueError):
        return None, "invalid"


def validate_and_collect(payload: dict):
    errors = []   # hard errors that block prediction
    flags = []    # soft notices (out of normal range)
    values = {}

    # Age
    age, err = _num(payload.get("age"))
    if err == "missing":
        errors.append("age")
    elif err == "invalid" or age != age:  # NaN guard
        errors.append("age")
    elif not (AGE_FIELD["min"] <= age <= AGE_FIELD["max"]):
        errors.append("age")
    else:
        values["Age"] = age

    # Numeric lab fields
    for f in FIELDS:
        val, err = _num(payload.get(f["key"]))
        if err == "missing":
            errors.append(f["key"])
            continue
        if err == "invalid":
            errors.append(f["key"])
            continue
        if not (f["min"] <= val <= f["max"]):
            errors.append(f["key"])
            continue
        values[f["model_key"]] = val
        if not (f["low"] <= val <= f["high"]):
            flags.append(f["key"])

    # Gender
    gender = str(payload.get("gender", "")).strip().capitalize()
    if gender not in GENDER_OPTIONS:
        errors.append("gender")
    else:
        values["Gender"] = gender

    # Diagnosis
    diag = str(payload.get("diagnosis", "")).strip().capitalize()
    if diag not in DIAGNOSIS_OPTIONS:
        errors.append("diagnosis")
    else:
        values["Diagnosis"] = diag

    # Pathogen present
    path_raw = str(payload.get("pathogen_present", "")).strip().lower()
    if path_raw in ("yes", "1", "true"):
        values["Pathogen_Present"] = 1
    elif path_raw in ("no", "0", "false"):
        values["Pathogen_Present"] = 0
    else:
        errors.append("pathogen_present")

    return values, errors, flags


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template(
        "index.html",
        fields=FIELDS,
        age_field=AGE_FIELD,
        diagnosis_options=DIAGNOSIS_OPTIONS,
        gender_options=GENDER_OPTIONS,
        metrics=METRICS,
        max_rows=MAX_BATCH_ROWS,
        batch_columns=BATCH_COLUMNS,
    )


@app.route("/api/config")
def api_config():
    return jsonify({
        "fields": FIELDS,
        "age": AGE_FIELD,
        "diagnosis_options": DIAGNOSIS_OPTIONS,
        "gender_options": GENDER_OPTIONS,
        "metrics": METRICS,
        "max_rows": MAX_BATCH_ROWS,
        "batch_columns": BATCH_COLUMNS,
        "risk_reference": risk_reference(),
    })


@app.route("/api/predict", methods=["POST"])
def api_predict():
    payload = request.get_json(silent=True) or {}
    values, errors, flags = validate_and_collect(payload)
    if errors:
        return jsonify({"ok": False, "errors": errors, "flags": flags}), 422

    result = predict_one(values)

    # Build a clean dict of the patient values for the insight prompt
    feat_for_insight = {
        "Age": values["Age"], "Gender": values["Gender"],
        "WBC_Count": values["WBC_Count"], "Platelets": values["Platelets"],
        "Hemoglobin": values["Hemoglobin"], "CRP_Level": values["CRP_Level"],
        "WBC_Blood_Count": values["WBC_Blood_Count"],
        "Protein_Level": values["Protein_Level"],
        "Glucose_Level": values["Glucose_Level"],
        "Diagnosis": values["Diagnosis"],
        "Pathogen_Present": "Yes" if values["Pathogen_Present"] else "No",
    }
    insights = generate_insights(result["risk"], result["probabilities"], feat_for_insight)

    return jsonify({
        "ok": True,
        "patient_id": str(payload.get("patient_id", "")).strip(),
        "result": result,
        "flags": flags,
        "insights": insights,
    })


@app.route("/api/predict-batch", methods=["POST"])
def api_predict_batch():
    upload = request.files.get("file")
    if upload is None:
        return jsonify({"ok": False, "error": "No file uploaded."}), 400

    try:
        text = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        return jsonify({"ok": False, "error": "File must be UTF-8 CSV."}), 400

    reader = csv.DictReader(io.StringIO(text))
    headers = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing_cols = [c for c in BATCH_COLUMNS if c not in headers]
    if missing_cols:
        return jsonify({
            "ok": False,
            "error": "Missing required column(s): " + ", ".join(missing_cols),
        }), 400

    rows = list(reader)
    if len(rows) > MAX_BATCH_ROWS:
        return jsonify({
            "ok": False,
            "error": f"Too many rows ({len(rows)}). Max {MAX_BATCH_ROWS} per upload.",
        }), 400

    results = []
    counts = {"Low": 0, "Moderate": 0, "High": 0, "Errors": 0}

    for i, raw in enumerate(rows, start=1):
        norm = {k.strip().lower(): (v.strip() if isinstance(v, str) else v)
                for k, v in raw.items()}
        pid = norm.get("patient_id") or f"ROW-{i}"
        values, errors, flags = validate_and_collect(norm)

        if errors:
            counts["Errors"] += 1
            # distinguish "missing" from "invalid" 
            missing = [e for e in errors if not str(norm.get(e, "")).strip()]
            invalid = [e for e in errors if e not in missing]
            msg_parts = []
            if missing:
                msg_parts.append("Missing: " + ", ".join(missing))
            if invalid:
                msg_parts.append("Invalid value: " + ", ".join(invalid))
            results.append({
                "patient_id": pid,
                "error": " | ".join(msg_parts),
                "age": norm.get("age", ""),
                "gender": norm.get("gender", ""),
            })
            continue

        pred = predict_one(values)
        counts[pred["risk"]] += 1
        results.append({
            "patient_id": pid,
            "age": int(values["Age"]),
            "gender": values["Gender"],
            "risk": pred["risk"],
            "confidence": pred["confidence"],
            "probabilities": pred["probabilities"],
            "flag": pred["risk"] == "High",
        })

    processed = len(rows)
    total_valid = processed - counts["Errors"]
    pct = {}
    for level in ("Low", "Moderate", "High"):
        pct[level] = round(counts[level] / total_valid * 100, 1) if total_valid else 0.0

    return jsonify({
        "ok": True,
        "filename": upload.filename,
        "processed": processed,
        "counts": counts,
        "percentages": pct,
        "results": results,
    })


@app.route("/api/summarize-batch", methods=["POST"])
def api_summarize_batch():
    payload = request.get_json(silent=True) or {}
    counts = payload.get("counts") or {}
    percentages = payload.get("percentages") or {}
    processed = payload.get("processed")

    if not counts or processed is None:
        return jsonify({"ok": False, "error": "Missing aggregate stats."}), 400

    stats = {
        "filename": str(payload.get("filename", "uploaded file")),
        "processed": int(processed),
        "counts": {
            "High": int(counts.get("High", 0)),
            "Moderate": int(counts.get("Moderate", 0)),
            "Low": int(counts.get("Low", 0)),
            "Errors": int(counts.get("Errors", 0)),
        },
        "percentages": {
            "High": float(percentages.get("High", 0)),
            "Moderate": float(percentages.get("Moderate", 0)),
            "Low": float(percentages.get("Low", 0)),
        },
    }
    summary = generate_batch_summary(stats)
    return jsonify({"ok": True, "summary": summary})


@app.route("/api/template")
def api_template():
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(BATCH_COLUMNS)
    writer.writerow(
        ["MR-001", "42", "Male", "8921", "215231", "15", "5",
         "5050", "20", "62", "Yes", "Viral"]
    )
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=meningitis_template.csv"},
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
