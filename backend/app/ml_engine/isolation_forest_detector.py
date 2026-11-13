import os
from typing import Dict, Any, List, Optional, Tuple
import numpy as np

try:
    import joblib
    from sklearn.ensemble import IsolationForest
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False
    joblib = None
    IsolationForest = None


class IsolationForestResult:
    """Outcome of multivariate Isolation Forest inference."""
    def __init__(
        self,
        is_anomalous: bool,
        severity: str,
        anomaly_score: float,
        feature_contributions: Dict[str, float],
        top_contributing_signals: List[str],
        summary: str,
        details: Dict[str, Any],
    ):
        self.is_anomalous = is_anomalous
        self.severity = severity
        self.anomaly_score = anomaly_score
        self.feature_contributions = feature_contributions
        self.top_contributing_signals = top_contributing_signals
        self.summary = summary
        self.details = details

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_anomalous": self.is_anomalous,
            "severity": self.severity,
            "anomaly_score": round(self.anomaly_score, 4),
            "feature_contributions": {k: round(v, 4) for k, v in self.feature_contributions.items()},
            "top_contributing_signals": self.top_contributing_signals,
            "summary": self.summary,
            "details": self.details,
        }


class IsolationForestWrapper:
    """Production-grade Isolation Forest model wrapper with persistence and explainability."""

    def __init__(
        self,
        n_estimators: int = 100,
        contamination: float = 0.03,
        random_state: int = 42,
    ):
        self.n_estimators = n_estimators
        self.contamination = contamination
        self.random_state = random_state
        self.model: Optional[IsolationForest] = None
        self.feature_names: List[str] = []
        self.scaling_params: Dict[str, Any] = {}
        self.baseline_feature_means: Dict[str, float] = {}

    def fit(
        self,
        X: np.ndarray,
        feature_names: List[str],
        scaling_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Trains Isolation Forest on normal operational baseline feature matrix."""
        if not _SKLEARN_AVAILABLE or IsolationForest is None:
            raise ImportError(
                "scikit-learn is required to train or fit Isolation Forest models. "
                "Install the offline model-training dependency profile (requirements-training.txt)."
            )

        if X is None or len(X) < 10:
            raise ValueError(f"Insufficient training data: {len(X) if X is not None else 0} samples. Minimum 10 required.")

        self.feature_names = list(feature_names)
        self.scaling_params = scaling_params

        self.model = IsolationForest(
            n_estimators=self.n_estimators,
            contamination=self.contamination,
            random_state=self.random_state,
            bootstrap=False,
            n_jobs=-1,
        )
        self.model.fit(X)

        # Baseline mean vector for explainability
        feature_means = np.mean(X, axis=0)
        self.baseline_feature_means = {
            fname: float(feature_means[i]) for i, fname in enumerate(feature_names)
        }

        # Calculate in-sample metrics
        scores = -self.model.score_samples(X)
        threshold = float(np.percentile(scores, (1.0 - self.contamination) * 100))

        return {
            "sample_count": len(X),
            "feature_count": len(feature_names),
            "score_mean": float(np.mean(scores)),
            "score_std": float(np.std(scores)),
            "score_p95": float(np.percentile(scores, 95)),
            "anomaly_threshold": threshold,
        }

    def predict_vector(self, x_vector: np.ndarray) -> IsolationForestResult:
        """
        Evaluates single feature vector (shape: 1, n_features).
        Returns explainable anomaly detection result.
        """
        if self.model is None:
            raise RuntimeError("Model has not been trained or loaded.")

        if x_vector.shape[1] != len(self.feature_names):
            raise ValueError(f"Expected {len(self.feature_names)} features, got {x_vector.shape[1]}")

        # IsolationForest predict returns -1 for outlier, 1 for inlier
        pred = self.model.predict(x_vector)[0]
        # score_samples returns opposite of anomaly score (higher score = more normal)
        # We invert so higher = more anomalous
        raw_score = -float(self.model.score_samples(x_vector)[0])

        is_anom = pred == -1

        # Calculate feature contributions by measuring deviation from baseline normalized space
        vector_1d = x_vector[0]
        contributions: Dict[str, float] = {}
        total_dev = 0.0

        for i, fname in enumerate(self.feature_names):
            expected = self.baseline_feature_means.get(fname, 0.0)
            dev = abs(float(vector_1d[i]) - expected)
            contributions[fname] = dev
            total_dev += dev

        # Normalize contributions
        normalized_contribs: Dict[str, float] = {}
        if total_dev > 1e-6:
            for k, v in contributions.items():
                normalized_contribs[k] = v / total_dev
        else:
            for k in contributions.keys():
                normalized_contribs[k] = 1.0 / len(contributions)

        # Sort top contributing features
        sorted_contribs = sorted(normalized_contribs.items(), key=lambda item: item[1], reverse=True)
        top_signals = [k.replace("_roll_mean", "").replace("_roll_std", "").replace("_diff", "") for k, _ in sorted_contribs[:3]]
        # Remove duplicates while preserving order
        top_signals_unique = list(dict.fromkeys(top_signals))

        # Determine severity based on raw score
        # Note: score_samples for IsolationForest typically ranges from ~ -0.8 to ~ -0.3
        # raw_score (-score_samples) is in [0.3, 0.8+]. > 0.65 is extreme outlier.
        if raw_score >= 0.70:
            severity = "CRITICAL"
        elif is_anom or raw_score >= 0.58:
            severity = "WARNING"
            is_anom = True
        elif raw_score >= 0.52:
            severity = "INFO"
        else:
            severity = "INFO"

        if is_anom:
            top_desc = ", ".join(f"{k} ({round(v * 100, 1)}%)" for k, v in sorted_contribs[:2])
            summary = (
                f"Multivariate anomaly detected (anomaly score: {round(raw_score, 3)}). "
                f"Primary contributors: {top_desc}."
            )
        else:
            summary = f"Normal multivariate pattern observed (anomaly score: {round(raw_score, 3)})."

        return IsolationForestResult(
            is_anomalous=is_anom,
            severity=severity,
            anomaly_score=raw_score,
            feature_contributions=normalized_contribs,
            top_contributing_signals=top_signals_unique,
            summary=summary,
            details={
                "n_features": len(self.feature_names),
                "contamination": self.contamination,
            },
        )

    def save(self, filepath: str) -> str:
        """Persists trained model and metadata."""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        payload = {
            "model": self.model,
            "feature_names": self.feature_names,
            "scaling_params": self.scaling_params,
            "baseline_feature_means": self.baseline_feature_means,
            "contamination": self.contamination,
            "n_estimators": self.n_estimators,
        }
        if not _SKLEARN_AVAILABLE or joblib is None:
            raise ImportError(
                "joblib and scikit-learn are required to save Isolation Forest models. "
                "Install the offline model-training dependency profile (requirements-training.txt)."
            )
        joblib.dump(payload, filepath)
        return filepath

    @classmethod
    def load(cls, filepath: str) -> "IsolationForestWrapper":
        """Loads model and metadata from disk."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Model artifact not found at {filepath}")
        if not _SKLEARN_AVAILABLE or joblib is None:
            raise ImportError(
                "joblib and scikit-learn are required to load Isolation Forest models. "
                "Install the offline model-training dependency profile (requirements-training.txt)."
            )
        payload = joblib.load(filepath)
        wrapper = cls(
            n_estimators=payload.get("n_estimators", 100),
            contamination=payload.get("contamination", 0.03),
        )
        wrapper.model = payload["model"]
        wrapper.feature_names = payload["feature_names"]
        wrapper.scaling_params = payload.get("scaling_params", {})
        wrapper.baseline_feature_means = payload.get("baseline_feature_means", {})
        return wrapper

