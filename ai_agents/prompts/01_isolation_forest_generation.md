# AI Agent Prompt: Isolation Forest Configuration Generation

**System Role:** Senior Machine Learning Engineer / Financial Quant Analyst
**Model Utilized:** Claude 3.5 Sonnet (via Claude CLI)
**Objective:** Generate a production-grade, unsupervised anomaly detection configuration utilizing scikit-learn's Isolation Forest to flag financial telemetry outliers.

## The Prompt Used
```text
Act as a Principal Financial Data Scientist. Generate a highly configurable Python module (`anomaly_detector.py`) using scikit-learn's Isolation Forest. 

The script must:
1. Accept a structured dataframe containing 15 corporate financial telemetry vectors (e.g., asset growth, leverage ratios, cash-to-revenue variance).
2. Train an unsupervised Isolation Forest model, allowing explicit tuning parameters for `contamination` and `n_estimators`.
3. Separate rule-based, deterministic threshold violations (like a hardcoded compliance breach) from statistical ML anomalies.
4. Export the resulting anomaly scores and individual tree isolation depth metrics into a structured format ready for a DuckDB data store.
5. Code must be highly modular, include type hinting, logging, and error handling.