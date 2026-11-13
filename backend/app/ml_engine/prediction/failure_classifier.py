import os
from typing import Dict, Any, List, Optional, Tuple
import numpy as np

try:
    import joblib
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import (
        precision_score,
        recall_score,
        f1_score,
        roc_auc_score,
        average_precision_score,
        confusion_matrix,
    )
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False
    joblib = None
    RandomForestClassifier = None
    GradientBoostingClassifier = None
    LogisticRegression = None

from app.ml_engine.prediction.probability_calibrator import ProbabilityCalibrator


class FailureClassifierWrapper:
    """Supervised failure classification model wrapper with probability calibration."""

    MIN_POSITIVE_SAMPLES = 3

    def __init__(
        self,
        algorithm: str = "RANDOM_FOREST",
        prediction_horizon_hours: int = 168,
        hyperparameters: Optional[Dict[str, Any]] = None,
    ):
        self.algorithm = algorithm.upper()
        self.prediction_horizon_hours = prediction_horizon_hours
        self.hyperparameters = hyperparameters or {}
        self.model: Optional[Any] = None
        self.calibrated_model: Optional[Any] = None
        self.feature_names: List[str] = []
        self.is_calibrated: bool = False

    def _init_model(self) -> Any:
        if not _SKLEARN_AVAILABLE:
            raise ImportError(
                "scikit-learn is required to instantiate and train failure classification models. "
                "Install the offline model-training dependency profile (requirements-training.txt)."
            )
        if self.algorithm == "GRADIENT_BOOSTING":
            return GradientBoostingClassifier(
                n_estimators=self.hyperparameters.get("n_estimators", 100),
                learning_rate=self.hyperparameters.get("learning_rate", 0.1),
                max_depth=self.hyperparameters.get("max_depth", 4),
                random_state=42,
            )
        elif self.algorithm == "LOGISTIC_REGRESSION":
            return LogisticRegression(
                max_iter=1000,
                class_weight="balanced",
                random_state=42,
            )
        else:  # Default RANDOM_FOREST
            return RandomForestClassifier(
                n_estimators=self.hyperparameters.get("n_estimators", 100),
                max_depth=self.hyperparameters.get("max_depth", 6),
                class_weight="balanced",
                random_state=42,
                n_jobs=-1,
            )

    def fit_and_validate(
        self,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
        feature_names: List[str],
        calibrate: bool = True,
    ) -> Dict[str, Any]:
        """Trains model, calibrates probability output, and evaluates validation metrics."""
        self.feature_names = list(feature_names)
        pos_train = int(np.sum(y_train == 1))
        pos_val = int(np.sum(y_val == 1))

        if pos_train < self.MIN_POSITIVE_SAMPLES:
            raise ValueError(
                f"Insufficient historical failure labels: found {pos_train} positive events in training set. "
                f"Minimum {self.MIN_POSITIVE_SAMPLES} confirmed/suspected failure records required for supervised training."
            )

        self.model = self._init_model()
        self.model.fit(X_train, y_train)

        # In-sample & Validation Predictions
        val_probs_raw = self.model.predict_proba(X_val)[:, 1] if len(X_val) > 0 else np.empty(0)

        # Calibrate if requested and validation set has samples
        calibration_results = {}
        if calibrate and len(X_val) >= 10 and pos_val >= 2:
            try:
                self.calibrated_model = ProbabilityCalibrator.calibrate_estimator(
                    base_estimator=self.model,
                    X_cal=X_val,
                    y_cal=y_val,
                )
                self.is_calibrated = True
                val_probs_cal = self.calibrated_model.predict_proba(X_val)[:, 1]
                calibration_results = ProbabilityCalibrator.evaluate_calibration(y_val, val_probs_cal)
            except Exception:
                self.calibrated_model = self.model
                self.is_calibrated = False
                calibration_results = ProbabilityCalibrator.evaluate_calibration(y_val, val_probs_raw)
        else:
            self.calibrated_model = self.model
            self.is_calibrated = False
            if len(X_val) > 0:
                calibration_results = ProbabilityCalibrator.evaluate_calibration(y_val, val_probs_raw)

        # Compute validation classification metrics
        val_metrics: Dict[str, Any] = {}
        if len(X_val) > 0 and len(np.unique(y_val)) > 1:
            val_preds = (val_probs_raw >= 0.5).astype(int)
            val_metrics["precision"] = round(float(precision_score(y_val, val_preds, zero_division=0)), 4)
            val_metrics["recall"] = round(float(recall_score(y_val, val_preds, zero_division=0)), 4)
            val_metrics["f1"] = round(float(f1_score(y_val, val_preds, zero_division=0)), 4)
            try:
                val_metrics["roc_auc"] = round(float(roc_auc_score(y_val, val_probs_raw)), 4)
            except Exception:
                val_metrics["roc_auc"] = 0.5
            try:
                val_metrics["pr_auc"] = round(float(average_precision_score(y_val, val_probs_raw)), 4)
            except Exception:
                val_metrics["pr_auc"] = 0.0

            tn, fp, fn, tp = confusion_matrix(y_val, val_preds, labels=[0, 1]).ravel()
            val_metrics["confusion_matrix"] = {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)}
            val_metrics["false_alarm_rate"] = round(float(fp / (fp + tn)), 4) if (fp + tn) > 0 else 0.0
        else:
            val_metrics = {
                "precision": 0.0,
                "recall": 0.0,
                "f1": 0.0,
                "roc_auc": 0.5,
                "pr_auc": 0.0,
                "note": "Validation set contained single class or was empty.",
            }

        # Feature importances
        feature_importances: Dict[str, float] = {}
        if hasattr(self.model, "feature_importances_"):
            for fname, imp in zip(self.feature_names, self.model.feature_importances_):
                feature_importances[fname] = round(float(imp), 4)

        return {
            "validation_metrics": val_metrics,
            "calibration_metrics": calibration_results,
            "feature_importances": dict(sorted(feature_importances.items(), key=lambda x: x[1], reverse=True)[:10]),
            "training_samples": len(X_train),
            "positive_samples": pos_train,
            "is_calibrated": self.is_calibrated,
        }

    def predict_risk(self, x_vector: np.ndarray) -> Tuple[float, float, Dict[str, float]]:
        """
        Infers failure probability for single feature vector.
        Returns:
            calibrated_prob: float (0.0 to 1.0)
            raw_score: float (0.0 to 1.0)
            feature_contributions: dict of feature attributions
        """
        if self.model is None:
            raise RuntimeError("Model has not been trained or loaded.")

        raw_prob = float(self.model.predict_proba(x_vector)[0][1])
        if self.calibrated_model is not None and self.is_calibrated:
            calibrated_prob = float(self.calibrated_model.predict_proba(x_vector)[0][1])
        else:
            calibrated_prob = raw_prob

        # Approximate feature contributions using vector magnitude * feature importance
        contributions: Dict[str, float] = {}
        if hasattr(self.model, "feature_importances_"):
            raw_weights = self.model.feature_importances_ * np.abs(x_vector[0])
            total = float(np.sum(raw_weights))
            if total > 1e-6:
                for fname, w in zip(self.feature_names, raw_weights):
                    contributions[fname] = round(float(w / total), 4)
            else:
                for fname in self.feature_names:
                    contributions[fname] = round(1.0 / len(self.feature_names), 4)

        return calibrated_prob, raw_prob, contributions

    def save(self, model_path: str, calibrator_path: Optional[str] = None) -> Tuple[str, Optional[str]]:
        """Saves model and calibrator artifacts."""
        os.makedirs(os.path.dirname(model_path), exist_ok=True)
        payload = {
            "model": self.model,
            "algorithm": self.algorithm,
            "prediction_horizon_hours": self.prediction_horizon_hours,
            "feature_names": self.feature_names,
            "hyperparameters": self.hyperparameters,
            "is_calibrated": self.is_calibrated,
        }
        if not _SKLEARN_AVAILABLE or joblib is None:
            raise ImportError(
                "joblib and scikit-learn are required to serialize failure classification models. "
                "Install the offline model-training dependency profile (requirements-training.txt)."
            )
        joblib.dump(payload, model_path)

        saved_cal_path = None
        if self.calibrated_model and calibrator_path:
            os.makedirs(os.path.dirname(calibrator_path), exist_ok=True)
            joblib.dump(self.calibrated_model, calibrator_path)
            saved_cal_path = calibrator_path

        return model_path, saved_cal_path

    @classmethod
    def load(cls, model_path: str, calibrator_path: Optional[str] = None) -> "FailureClassifierWrapper":
        """Loads serialized model artifact from disk."""
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model artifact not found at {model_path}")
        if not _SKLEARN_AVAILABLE or joblib is None:
            raise ImportError(
                "joblib and scikit-learn are required to load failure classification models. "
                "Install the offline model-training dependency profile (requirements-training.txt)."
            )
        payload = joblib.load(model_path)
        wrapper = cls(
            algorithm=payload.get("algorithm", "RANDOM_FOREST"),
            prediction_horizon_hours=payload.get("prediction_horizon_hours", 168),
            hyperparameters=payload.get("hyperparameters", {}),
        )
        wrapper.model = payload["model"]
        wrapper.feature_names = payload.get("feature_names", [])
        wrapper.is_calibrated = payload.get("is_calibrated", False)

        if calibrator_path and os.path.exists(calibrator_path):
            wrapper.calibrated_model = joblib.load(calibrator_path)
        else:
            wrapper.calibrated_model = wrapper.model

        return wrapper

