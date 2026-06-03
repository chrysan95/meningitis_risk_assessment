# Meningitis Risk Assessment

A clinical decision-support web tool that stratifies meningitis risk
(**Low / Moderate / High**) from CSF and blood markers using a
**Cost-Sensitive Random Forest**

> **For research and decision support only. Does not replace clinical diagnosis.**

---

## What it does

- **Single patient** — enter lab values, get a risk level, model confidence,
  per-class probabilities, and **AI-generated clinical insights** that answer
  two questions:
  1. *What does this risk level mean in this context?*
  2. *What should be done next?*
- **Batch upload** — upload a CSV (up to 500 rows), get per-patient results,
  summary counts, a distribution donut, search, filtering, pagination, and a
  downloadable results CSV. Rows with missing/invalid values are flagged, but not blocked.

---

## Project layout

```
meningitis_app/
├── app.py              # Flask server + validation + prediction endpoints
├── train_model.py      # rebuilds the RF model -> model/model.pkl
├── insights.py         # risk knowledge base + Gemini integration (+ fallback)
├── meningitis.csv      # training data
├── model/model.pkl     # saved model bundle (created by train_model.py)
├── requirements.txt
├── templates/index.html
└── static/css/style.css, static/js/app.js
```

---

## Setup

```bash
cd meningitis_app
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 1. train / rebuild the model bundle (only needed once)
python train_model.py

# 2. run the server
python app.py
```

Open <http://localhost:5000>.

---

## Google AI Studio (Gemini) — optional

The **AI Generated Insights** panel uses Google AI Studio when an API key is
present, and falls back to a built-in clinical knowledge base otherwise, so
the app works with or without a key.

```bash
export GEMINI_API_KEY="your-key-from-aistudio.google.com"
export GEMINI_MODEL="gemini-3.5-flash"
python app.py
```

Get a key at <https://aistudio.google.com/apikey>. If the model name changes,
set `GEMINI_MODEL` to a currently available model.

---

## CSV format (batch upload)

Required columns:

```
patient_id, age, gender, wbc_csf, platelets, hemoglobin, crp_level,
wbc_blood, protein_level, glucose, pathogen_present, diagnosis
```

- `gender`: `Male` / `Female`
- `pathogen_present`: `Yes` / `No`
- `diagnosis`: `Viral` / `Bacterial` / `Unknown`

Download a ready-made template from the upload screen.

---

## Reference ranges (shown as form hints / used for soft flagging)

| Field          | Reference          |
|----------------|--------------------|
| WBC Count      | 4,500–11,000 cells/µL |
| Platelets      | 150,000–400,000     |
| Hemoglobin     | 12–17 g/dL          |
| CRP Level      | < 10 mg/L           |
| WBC Blood Count| 4,500–11,000 cells/µL |
| Protein Level  | 15–45 mg/L          |
| Glucose        | 45–80 mg/L          |

Values outside these ranges are **allowed** (abnormal labs are expected) but
highlighted. Values that are non-numeric, negative, or implausible are rejected.
