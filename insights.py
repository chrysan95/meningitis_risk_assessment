import json
import os
import urllib.error
import urllib.request

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash").strip()
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent?key={key}"
)

# ---------------------------------------------------------------------------
# Static knowledge base
# Used as a fallback and also injected into the Gemini prompt
# ---------------------------------------------------------------------------
RISK_INFO = {
    "Low": {
        "summary": (
            "CSF and blood markers sit within, or close to, normal reference "
            "ranges. The pattern is most consistent with no acute bacterial "
            "meningitis — typically a viral picture or an alternative, "
            "non-emergent cause. Probability of a serious, rapidly progressive "
            "infection is low."
        ),
        "recommendations": [
            "Manage supportively: hydration, analgesia and antipyretics as needed.",
            "Outpatient management is reasonable if the patient is clinically stable and reliable for follow-up.",
            "Provide clear safety-netting advice and re-evaluate promptly if symptoms worsen.",
            "Confirm with CSF PCR / culture and correlate with the full clinical picture.",
        ],
    },
    "Moderate": {
        "summary": (
            "The CSF shows atypical findings — often mild pleocytosis, slightly "
            "elevated protein, or borderline glucose. This profile is frequently "
            "associated with viral meningitis, fungal infection, or "
            "early / partially-treated bacterial meningitis, and warrants close "
            "attention until a definitive cause is established."
        ),
        "recommendations": [
            "Admit for close clinical observation.",
            "Consider initiating empirical antiviral therapy (e.g. aciclovir) or antibiotics depending on the patient's presentation and local epidemiology.",
            "Consider a repeat lumbar puncture in 12–24 hours if symptoms progress.",
            "Await PCR and definitive culture results before de-escalating therapy.",
        ],
    },
    "High": {
        "summary": (
            "Markers strongly suggest acute bacterial meningitis or severe "
            "infection — for example marked CSF pleocytosis, high protein, low "
            "glucose, and elevated systemic inflammatory markers. This is a "
            "time-critical pattern where delayed treatment increases the risk of "
            "poor outcome."
        ),
        "recommendations": [
            "Treat as a medical emergency — do not wait for culture results.",
            "Start empirical IV antibiotics immediately (per local protocol), with adjunctive dexamethasone where indicated.",
            "Escalate to senior / infectious-disease review and consider critical-care admission.",
            "Implement isolation precautions and notify public health where reporting is required.",
        ],
    },
}

# Markers used to add small, value-specific observations in the fallback text.
NORMAL_RANGES = {
    "WBC_Count": (4500, 11000, "CSF/total WBC count"),
    "Protein_Level": (15, 45, "CSF protein"),
    "Glucose_Level": (45, 80, "CSF glucose"),
    "CRP_Level": (0, 10, "CRP"),
    "Hemoglobin": (12, 17, "haemoglobin"),
    "Platelets": (150000, 400000, "platelets"),
}


def _abnormal_notes(features: dict) -> list:
    notes = []
    for key, (low, high, label) in NORMAL_RANGES.items():
        val = features.get(key)
        if val is None:
            continue
        try:
            val = float(val)
        except (TypeError, ValueError):
            continue
        if val < low:
            notes.append(f"{label} is below the reference range ({val:g}).")
        elif val > high:
            notes.append(f"{label} is above the reference range ({val:g}).")
    return notes


def _fallback(risk: str, features: dict) -> dict:
    info = RISK_INFO[risk]
    notes = _abnormal_notes(features)
    summary = info["summary"]
    if notes:
        summary += " Notable values: " + " ".join(notes)
    return {
        "summary": summary,
        "recommendations": list(info["recommendations"]),
        "source": "rule-based",
    }

# ---------------------------------------------------------------------------
# AI Insights generation
# Prompt for the single patient view
# ---------------------------------------------------------------------------

def _build_prompt(risk: str, probs: dict, features: dict) -> str:
    info = RISK_INFO[risk]
    return f"""You are a clinical decision-support assistant helping a medical \
professional interpret a meningitis risk-stratification model. The model is a \
cost-sensitive Random Forest trained on CSF and blood markers. It does NOT \
diagnose; it stratifies risk to support clinical judgement.

Predicted risk level: {risk}
Class probabilities: Low {probs.get('Low', 0)}%, Moderate \
{probs.get('Moderate', 0)}%, High {probs.get('High', 0)}%

Patient values:
{json.dumps(features, indent=2)}

Reference guidance for a {risk} result:
- Meaning: {info['summary']}
- Typical next steps: {', '.join(info['recommendations'])}

Write a concise, professional response with EXACTLY this JSON shape and nothing else:
{{
  "summary": "2-4 sentence interpretation of what this {risk} result means for THIS patient, referencing their specific out-of-range markers where relevant.",
  "recommendations": ["3 to 5 short, actionable next-step bullet points for the clinician"]
}}
Be measured and evidence-aligned. Do not invent values. Do not claim a diagnosis."""


def _call_gemini(prompt: str) -> dict:
    url = GEMINI_URL.format(model=GEMINI_MODEL, key=GEMINI_API_KEY)
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.4,
            "responseMimeType": "application/json",
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    text = body["candidates"][0]["content"]["parts"][0]["text"]
    parsed = json.loads(text)
    summary = str(parsed.get("summary", "")).strip()
    recs = [str(r).strip() for r in parsed.get("recommendations", []) if str(r).strip()]
    if not summary or not recs:
        raise ValueError("Incomplete Gemini response")
    return {"summary": summary, "recommendations": recs, "source": "gemini"}


def generate_insights(risk: str, probs: dict, features: dict) -> dict:
    """Return {'summary', 'recommendations', 'source'} for a prediction."""
    if GEMINI_API_KEY:
        try:
            return _call_gemini(_build_prompt(risk, probs, features))
        except (urllib.error.URLError, KeyError, ValueError, TimeoutError, json.JSONDecodeError):
            # Any failure -> graceful fallback, app keeps working.
            pass
    return _fallback(risk, features)


# Exposed so the frontend can render the static reference panel if wanted.
def risk_reference() -> dict:
    return RISK_INFO


# ---------------------------------------------------------------------------
# Batch AI summary
# IMPORTANT: this only ever receives AGGREGATE counts never individual
# patient rows. This keeps the prompt tiny (~200 tokens) and means no
# per-patient data leaves the machine.
# ---------------------------------------------------------------------------
def _batch_fallback(stats: dict) -> dict:
    c = stats["counts"]
    p = stats["percentages"]
    total = stats["processed"]
    valid = total - c.get("Errors", 0)

    summary = (
        f"Across {total} processed record(s), the model stratified {valid} "
        f"patient(s): {c.get('High', 0)} high-risk ({p.get('High', 0)}%), "
        f"{c.get('Moderate', 0)} moderate-risk ({p.get('Moderate', 0)}%), and "
        f"{c.get('Low', 0)} low-risk ({p.get('Low', 0)}%)."
    )
    if c.get("Errors", 0):
        summary += (
            f" {c['Errors']} row(s) could not be scored due to missing or "
            f"invalid values and should be reviewed before inclusion."
        )

    recs = []
    if c.get("High", 0):
        recs.append(
            f"Prioritise the {c['High']} high-risk patient(s) for immediate "
            "clinical review — this group drives the most urgent action."
        )
    if c.get("Moderate", 0):
        recs.append(
            f"Place the {c['Moderate']} moderate-risk patient(s) under close "
            "observation and confirm with PCR / culture before de-escalating."
        )
    if c.get("Low", 0):
        recs.append(
            f"The {c['Low']} low-risk patient(s) are candidates for supportive "
            "or outpatient management with safety-netting advice."
        )
    if c.get("Errors", 0):
        recs.append(
            f"Resolve data-quality issues in the {c['Errors']} flagged row(s) "
            "and re-run to obtain a complete cohort assessment."
        )
    if not recs:
        recs.append("No valid records were scored — check the uploaded file.")

    return {"summary": summary, "recommendations": recs, "source": "rule-based"}


def _build_batch_prompt(stats: dict) -> str:
    return f"""You are a clinical decision-support assistant summarising the \
output of a meningitis risk-stratification model for a medical professional \
reviewing a batch of patients. You are given ONLY aggregate counts, not \
individual patient data.

Cohort results:
- File: {stats.get('filename', 'uploaded file')}
- Records processed: {stats['processed']}
- High risk: {stats['counts'].get('High', 0)} ({stats['percentages'].get('High', 0)}%)
- Moderate risk: {stats['counts'].get('Moderate', 0)} ({stats['percentages'].get('Moderate', 0)}%)
- Low risk: {stats['counts'].get('Low', 0)} ({stats['percentages'].get('Low', 0)}%)
- Rows flagged as errors (unscored): {stats['counts'].get('Errors', 0)}

Write a concise, professional response with EXACTLY this JSON shape and nothing else:
{{
  "summary": "2-4 sentence overview of the cohort's risk distribution and what it implies for triage/workload.",
  "recommendations": ["3 to 5 short, actionable next-step bullets for managing this cohort (triage order, follow-up, data-quality)"]
}}
Be measured and evidence-aligned. Do not invent patient-level details or diagnoses."""


def generate_batch_summary(stats: dict) -> dict:
    """Return {'summary', 'recommendations', 'source'} for a whole batch."""
    if GEMINI_API_KEY:
        try:
            return _call_gemini(_build_batch_prompt(stats))
        except (urllib.error.URLError, KeyError, ValueError, TimeoutError, json.JSONDecodeError):
            pass
    return _batch_fallback(stats)
