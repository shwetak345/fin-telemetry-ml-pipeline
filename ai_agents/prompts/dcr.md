## 1. Real-Data Live Streaming
- **Issue**: Need to implement the 'Bronze-Silver-Gold' production pipeline using real SEC EDGAR Azure blobs.
- **Prompt**: "Act as a Data Engineer. Create a new directory structure `backend/live_ingestion/`. Inside, create:
    - `azure_blob_stream.py`: A script using `pyspark` to read raw SEC EDGAR filings directly from the public Azure Blob container (the 'Bronze' layer).
    - `pyspark_processor.py`: A script to perform the 'Silver' layer transformations: cleaning, PII masking, and running the `scikit-learn` Isolation Forest model on the streamed data.
    - Ensure the code is structured for local execution using your laptop's CPU cores, but designed to be enterprise-ready for Azure clusters.
    - Additionally, ensure the `audit_warehouse.db` (Gold layer) is exposed via a FastAPI backend running on port 8000. Update the configuration to support switching between 'Mock' mode and 'Live' mode using an environment variable (`VITE_API_MODE`). Please also generate a `requirements.txt` file."


