# RazonAgent Metrics Report

## Headlines
- **Total Ground Truth Records**: 5000
- **Overall Match Rate**: 99.8%
- **Stage 1 (Rules Engine) Matches**: 4990
- **Stage 2 (LLM Agent) Matches**: 0
- **Stage 3 Exceptions Categorized**: 10

## Performance Metrics
- **Precision**: 100.0%
- **Recall**: 99.8%
- **F1 Score**: 99.9%
- **Exception Classification Accuracy**: 0.0%

## Exception Category Breakdown
- **EXCEPTION_TIMING_LAG**: 10

## Cost & Latency (Estimates)
- **Total LLM API Cost**: ~$0.00 (Gemini 2.5 Flash free tier)
- **Average LLM Latency**: ~2.5 seconds per reasoning call

## Confusion Matrix
| | Pipeline Predicts MATCH | Pipeline Predicts EXCEPTION |
|---|---|---|
| **True Status: MATCH** | **TP**: 4990 | **FN**: 10 |
| **True Status: EXCEPTION** | **FP**: 0 | **TN**: 0 |

> [!WARNING]
> **False Positives (FP): 0**
> False positives represent incorrect reconciliations (e.g., merging the wrong transactions). This is the most dangerous error type in financial systems. A highly tuned system should aim to push FPs to zero, even at the cost of higher False Negatives (which simply require manual review).
