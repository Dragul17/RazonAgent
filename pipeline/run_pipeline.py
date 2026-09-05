from ingestion import ingest_data
from rules_engine import apply_rules
from llm_agent import run_agent
from exception_classifier import classify_exceptions
from scorer import generate_report
import logging
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    logger.info("Starting RazonAgent Pipeline")
    start_time = time.time()
    
    logger.info("--- Phase 1: Ingestion ---")
    ingest_data()
    
    logger.info("--- Phase 2: Stage 1 (Rules Engine) ---")
    apply_rules()
    
    logger.info("--- Phase 3: Stage 2 (LLM Agent) ---")
    run_agent()
    
    logger.info("--- Phase 4: Stage 3 (Exception Classifier) ---")
    classify_exceptions()
    
    logger.info("--- Phase 5: Evaluation & Metrics ---")
    generate_report()
    
    duration = time.time() - start_time
    logger.info(f"Pipeline completed in {duration:.2f} seconds.")

if __name__ == "__main__":
    main()
