import requests
from verifier import verify_warehouse_run

def run_noop_baseline(base_url: str, task_id: str, seed: int) -> float:
    res = requests.post(f"{base_url}/reset", json={"task_id": task_id, "seed": seed}).json()
    session_id = res["session_id"]

    for _ in range(40):
        step_res = requests.post(f"{base_url}/step", json={"session_id": session_id, "actions": {}}).json()
        if step_res.get("done"):
            break

    eval_res = verify_warehouse_run(base_url, session_id)
    return float(eval_res["score"])

def run_oracle_baseline(base_url: str, task_id: str, seed: int) -> float:
    res = requests.post(f"{base_url}/reset", json={"task_id": task_id, "seed": seed}).json()
    session_id = res["session_id"]
    state = res["state"]
    max_steps = state["max_steps"]

    amr_order_map = {
        "AMR_1": "ORD_1",
        "AMR_2": "ORD_2",
        "AMR_3": "ORD_3",
        "AMR_4": "ORD_4",
    }

    for _ in range(max_steps):
        actions = {}
        fleet = state["fleet"]
        orders = state["orders"]

        for amr_id, amr in fleet.items():
            cx, cy = amr["pos"]
            ord_id = amr_order_map.get(amr_id)

            if not ord_id or ord_id not in orders or orders[ord_id]["status"] == "FULFILLED":
                actions[amr_id] = "WAIT"
                continue

            ord_info = orders[ord_id]

            if not amr["carrying"]:
                tx, ty = ord_info["pickup"]
                if cx == tx and cy == ty:
                    actions[amr_id] = "PICKUP"
                    continue
            else:
                tx, ty = ord_info["drop"]
                if cx == tx and cy == ty:
                    actions[amr_id] = "DROPOFF"
                    continue

            # Direct navigation: align X coordinate, then move along Y
            if cx < tx:
                actions[amr_id] = "MOVE_RIGHT"
            elif cx > tx:
                actions[amr_id] = "MOVE_LEFT"
            elif cy < ty:
                actions[amr_id] = "MOVE_UP"
            elif cy > ty:
                actions[amr_id] = "MOVE_DOWN"
            else:
                actions[amr_id] = "WAIT"

        step_res = requests.post(f"{base_url}/step", json={"session_id": session_id, "actions": actions}).json()
        state = step_res["state"]
        if step_res.get("done"):
            break

    eval_res = verify_warehouse_run(base_url, session_id)
    return float(eval_res["score"])
