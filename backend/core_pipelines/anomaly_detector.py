import logging
import numpy as np
import pandas as pd
from typing import List, Dict, Tuple
from sklearn.ensemble import IsolationForest

# Configure logging for enterprise traceability
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class ComplianceAnomalyDetector:
    """
    An unsupervised Machine Learning configuration utilizing Isolation Forest 
    to detect 'unknown unknown' anomalies in public financial telemetry.
    """
    def __init__(self, contamination: float = 0.01, n_estimators: int = 150, random_state: int = 42):
        self.contamination = contamination
        self.n_estimators = n_estimators
        self.random_state = random_state
        self.model = IsolationForest(
            contamination=self.contamination,
            n_estimators=self.n_estimators,
            random_state=self.random_state,
            n_jobs=-1 # Utilize all available CPU cores
        )
        logger.info(f"Initialized Isolation Forest Engine (Contamination: {contamination}, Trees: {n_estimators})")

    def run_deterministic_rules(self, df: pd.DataFrame) -> pd.Series:
        """
        Layer 1: Deterministic validation to flag known regulation violations (SOX 404 / ASC 606).
        """
        logger.info("Executing deterministic compliance rules...")
        # Example rule: Flag if a company claims revenue recognition (ASC 606) but cash flow is deeply negative
        rule_violations = (df['revenue_growth'] > 0.20) & (df['operating_cash_flow'] < 0)
        return rule_violations.astype(int)

    def train_ml_detector(self, df: pd.DataFrame, feature_cols: List[str]) -> Tuple[np.ndarray, np.ndarray]:
        """
        Layer 2: Unsupervised Machine Learning to catch 'unknown unknown' multi-vector anomalies.
        """
        logger.info(f"Training unsupervised Isolation Forest across {len(feature_cols)} financial vectors...")
        X = df[feature_cols].fillna(0) # Safeguard missing inputs
        
        # fit_predict returns -1 for anomalies and 1 for normal data. Convert to 1 for anomaly, 0 for normal.
        predictions = self.model.fit_predict(X)
        ml_anomalies = np.where(predictions == -1, 1, 0)
        
        # Calculate raw anomaly scores (lower/more negative means more anomalous)
        anomaly_scores = self.model.score_samples(X)
        
        return ml_anomalies, anomaly_scores

    def Execute_dual_layer_pipeline(self, df: pd.DataFrame, feature_cols: List[str]) -> pd.DataFrame:
        """
        Executes the dual-layered engine and structures output data for the DuckDB store.
        """
        processed_df = df.copy()
        
        # Run both layers
        processed_df['known_rule_violation'] = self.run_deterministic_rules(processed_df)
        ml_flags, ml_scores = self.train_ml_detector(processed_df, feature_cols)
        
        processed_df['ml_anomaly_flag'] = ml_flags
        processed_df['ml_anomaly_score'] = ml_scores
        
        # Total Triage Priority Metric
        processed_df['triage_priority'] = processed_df['known_rule_violation'] + processed_df['ml_anomaly_flag']
        
        logger.info(f"Pipeline complete. Detected {processed_df['ml_anomaly_flag'].sum()} statistical anomalies.")
        return processed_df

# Example mock execution block for testing locally
if __name__ == "__main__":
    # Simulate a tiny batch of 15-vector financial data
    np.random.seed(42)
    mock_data = pd.DataFrame({
        'revenue_growth': np.random.normal(0.05, 0.02, 100),
        'operating_cash_flow': np.random.normal(50000, 10000, 100),
        'leverage_ratio': np.random.normal(1.5, 0.2, 100)
    })
    
    # Inject an intentional anomaly
    mock_data.loc[99] = [0.45, -250000, 4.8] # Extreme outlier
    
    features = ['revenue_growth', 'operating_cash_flow', 'leverage_ratio']
    detector = ComplianceAnomalyDetector()
    results = detector.Execute_dual_layer_pipeline(mock_data, features)
    print(results[['known_rule_violation', 'ml_anomaly_flag', 'ml_anomaly_score']].tail())