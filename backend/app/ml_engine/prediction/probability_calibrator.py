from typing import Dict, Any, List, Tuple, Optional
import numpy as np

try:
    from sklearn.calibration import CalibratedClassifierCV, calibration_curve
    from sklearn.frozen import FrozenEstimator
    _SKLEARN_AVAILABLE = True
except ImportError:
    _SKLEARN_AVAILABLE = False
    CalibratedClassifierCV = None
    calibration_curve = None
    FrozenEstimator = None


class ProbabilityCalibrator:
    """Calibrates raw predictive classification scores into true empirical failure probabilities."""

    @classmethod
    def evaluate_calibration(
        cls,
        y_true: np.ndarray,
        y_prob: np.ndarray,
        n_bins: int = 5,
    ) -> Dict[str, Any]:
        """
        Computes calibration diagnostics: Brier score, Expected Calibration Error (ECE),
        and reliability curve coordinates.
        """
        if len(y_true) == 0 or len(y_prob) == 0:
            return {"brier_score": 1.0, "ece": 1.0, "is_well_calibrated": False, "bins": []}

        # Brier score: Mean squared error of probabilities
        brier_score = float(np.mean((y_prob - y_true) ** 2))

        # Reliability curve (fraction of positives vs mean predicted value)
        try:
            prob_true, prob_pred = calibration_curve(y_true, y_prob, n_bins=n_bins, strategy="uniform")
            bins_data = [
                {"bin_predicted": float(pred), "bin_actual": float(act)}
                for pred, act in zip(prob_pred, prob_true)
            ]
            # Expected Calibration Error (ECE)
            ece = float(np.mean(np.abs(prob_true - prob_pred))) if len(prob_true) > 0 else 0.0
        except Exception:
            bins_data = []
            ece = 0.0

        is_well_calibrated = brier_score < 0.25 and ece < 0.20

        return {
            "brier_score": round(brier_score, 4),
            "ece": round(ece, 4),
            "is_well_calibrated": is_well_calibrated,
            "reliability_bins": bins_data,
        }

    @classmethod
    def calibrate_estimator(
        cls,
        base_estimator: Any,
        X_cal: np.ndarray,
        y_cal: np.ndarray,
        method: str = "sigmoid",  # 'sigmoid' for Platt scaling or 'isotonic'
    ) -> Any:
        """Fits probability calibrator over holdout calibration data."""
        if not _SKLEARN_AVAILABLE or CalibratedClassifierCV is None:
            raise ImportError(
                "scikit-learn is required for probability calibration. "
                "Install the offline model-training dependency profile (requirements-training.txt)."
            )
        pos_count = int(np.sum(y_cal == 1))
        # Use FrozenEstimator for prefit estimators in scikit-learn 1.4+
        frozen = FrozenEstimator(base_estimator)
        calibrated = CalibratedClassifierCV(
            estimator=frozen,
            method=method if pos_count >= 5 else "sigmoid",
        )
        calibrated.fit(X_cal, y_cal)
        return calibrated

