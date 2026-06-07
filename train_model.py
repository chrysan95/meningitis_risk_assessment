import os
import pickle

import numpy as np
import pandas as pd
from imblearn.over_sampling import SMOTE
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import train_test_split

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(HERE, "meningitis.csv")
OUT_PATH = os.path.join(HERE, "model", "model.pkl")

RISK_MAPPING = {"Low Risk": 0, "Moderate Risk": 1, "High Risk": 2}
CLASS_NAMES = ["Low", "Moderate", "High"]


COST_MATRIX = np.array(
    [
        [0.0, 0.2, 0.4],  # True Low
        [0.4, 0.0, 0.2],  # True Moderate
        [1.0, 0.6, 0.0],  # True High
    ]
)


def build_features(data: pd.DataFrame) -> pd.DataFrame:
    x = data[
        [
            "Age",
            "Gender",
            "WBC_Count",
            "Protein_Level",
            "Glucose_Level",
            "Hemoglobin",
            "WBC_Blood_Count",
            "Platelets",
            "CRP_Level",
            "Diagnosis",
            "Pathogen_Present",
        ]
    ]
    x = pd.get_dummies(
        data=x, columns=["Gender", "Diagnosis", "Pathogen_Present"], dtype=int
    )
    x = x.rename(
        columns={
            "Pathogen_Present_0": "Pathogen_Not_Present",
            "Pathogen_Present_1": "Pathogen_Present",
        }
    )
    return x


def main() -> None:
    data = pd.read_csv(DATA_PATH).drop(["Outcome"], axis=1)
    data["Pathogen_Present"] = data["Pathogen_Present"].map({"No": 0, "Yes": 1})

    y = data["Risk_Level"].map(RISK_MAPPING).values
    x = build_features(data)
    feature_order = list(x.columns)

    # 70 / 15 / 15 split (stratified) 
    X_train, X_temp, y_train, y_temp = train_test_split(
        x, y, test_size=0.30, random_state=42, stratify=y
    )
    X_val, X_test, y_val, y_test = train_test_split(
        X_temp, y_temp, test_size=0.50, random_state=42, stratify=y_temp
    )

    # Balance the training set
    smote = SMOTE(sampling_strategy="not majority", random_state=42)
    X_train_res, y_train_res = smote.fit_resample(X_train, y_train)

    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train_res, y_train_res)

    # Cost-sensitive prediction on the held-out test set
    probs = model.predict_proba(X_test)
    expected_costs = probs @ COST_MATRIX
    y_pred = np.argmin(expected_costs, axis=1)

    rec = recall_score(y_test, y_pred, average="macro")
    f1 = f1_score(y_test, y_pred, average="macro")
    acc = accuracy_score(y_test, y_pred)
    prec = precision_score(y_test, y_pred, average="macro", zero_division=0)

    # Custom weighted score (w2 >= w1 > w3 >= w4, sum = 100)
    w1, w2, w3, w4 = 30, 40, 20, 10
    custom_score = (w1 * rec) + (w2 * f1) + (w3 * acc) + (w4 * prec)

    metrics = {
        "accuracy": round(acc * 100, 2),
        "precision": round(prec * 100, 2),
        "recall": round(rec * 100, 2),
        "f1": round(f1 * 100, 2),
        "custom_score": round(custom_score, 2),
        "test_size": int(len(X_test)),
    }

    bundle = {
        "model": model,
        "feature_order": feature_order,
        "cost_matrix": COST_MATRIX,
        "class_names": CLASS_NAMES,
        "metrics": metrics,
    }

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "wb") as f:
        pickle.dump(bundle, f)

    print("Saved model bundle ->", OUT_PATH)
    print("Feature order:", feature_order)
    print("Metrics:", metrics)


if __name__ == "__main__":
    main()
