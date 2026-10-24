import requests
from typing import Dict, Any

def verify_warehouse_run(sim_url: str, session_id: str, elapsed_time_sec: float = 0.0) -> Dict[str, Any]:
    default_failure = {
        "score": 0.0,
        "passed": False,
        "orders_fulfilled": "0/0",
        "on_time_deliveries": 0,
        "collisions": 0,
        "immobilized_amrs": 0,
        "error": None
    }

    try:
        res = requests.get(f"{sim_url}/evaluate/{session_id}", timeout=10)
        if res.status_code != 200:
            default_failure["error"] = f"Evaluation returned status code {res.status_code}"
            return default_failure

        data = res.json()
        raw_score = float(data.get("score", 0.0))
        clamped_score = max(0.0, min(1.0, round(raw_score, 2)))

        if elapsed_time_sec > 600.0:
            clamped_score = 0.0
            data["timeout_disqualification"] = True

        data["score"] = clamped_score
        data["passed"] = clamped_score >= 0.95
        return data

    except Exception as e:
        default_failure["error"] = f"Verifier exception: {str(e)}"
        return default_failure