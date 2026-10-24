import os, json, time
from datetime import datetime, timezone
import requests
from openai import OpenAI
from baselines import run_noop_baseline, run_oracle_baseline

MODEL = os.getenv("MODEL", "gpt-luna")
API_KEY = os.getenv("API_KEY")
BASE_URL = os.getenv("BASE_URL")
TASK_ID = os.getenv("TASK_ID", "task_3_cross_aisle_deadlock")
SEED = int(os.getenv("SEED", "42"))
APPEND_FILE = os.getenv("APPEND_FILE", "inputs/append.txt")
MODE = os.getenv("MODE", "full")
SIM_URL = "http://warehouse-sim:7000"

TOOL_CALL_TIMEOUT = 60          # spec: single tool call 60s
MAX_TOOL_CALLS = 10             # spec: max 10 per reply
CONTEXT_BUDGET_TOKENS = 60_000  # leave headroom under 64K
KEEP_LAST_STEPS = 8             # full fidelity for last N steps
STEP_CAP = 40
WALLCLOCK_CAP = 600


TASK_REGISTRY = {
    "task_1_single_picker":        {"tier":1},
    "task_2_battery_critical":     {"tier":1},
    "task_3_cross_aisle_deadlock": {"tier":2},
    "task_4_express_dispatch":     {"tier":2},
    "task_5_fleet_surge":          {"tier":3},
}

if not os.path.exists(APPEND_FILE) or os.path.getsize(APPEND_FILE) == 0:
    raise RuntimeError(f"'{APPEND_FILE}' missing or empty; terminating.")
with open(APPEND_FILE) as f:
    appended_instructions = f.read()

os.makedirs("logs", exist_ok=True)
log_file = open(f"logs/run_{int(time.time())}.jsonl", "w")

def emit(rec):
    log_file.write(json.dumps(rec) + "\n"); log_file.flush()

def approx_tokens(msgs):
    # cheap heuristic: 4 chars ~ 1 token
    return sum(len(str(m)) for m in msgs) // 4

def trim_context(messages, system_msg, initial_user_msg, recent_steps):
    """Keep system + initial task + last N full steps. Summarise older steps."""
    head = [system_msg, initial_user_msg]
    if len(recent_steps) <= KEEP_LAST_STEPS:
        return head + recent_steps
    older = recent_steps[:-KEEP_LAST_STEPS]
    recent = recent_steps[-KEEP_LAST_STEPS:]
    summary = {
        "role": "user",
        "content": f"[Earlier steps summarised: {len(older)} steps executed. "
                   f"Last known collision count and fleet positions collapsed. "
                   f"Continue from the most recent observation below.]",
    }
    return head + [summary] + recent

def run_one_task(task_id, seed):
    """Runs gate + model on one task. Returns (noop, oracle, final_score)."""
    print(f"\n=== TASK {task_id} seed={seed} ===")
    noop = run_noop_baseline(SIM_URL, task_id, seed)
    oracle = run_oracle_baseline(SIM_URL, task_id, seed)
    print(f"Gate -> No-Op: {noop:.2f} (<=0.05)  Oracle: {oracle:.2f} (>=0.95)")
    gate_ok = (noop <= 0.05) and (oracle >= 0.95)
    os.makedirs("baseline-results", exist_ok=True)
    per_task = {
        "task_id": task_id, "seed": seed,
        "noop": noop, "oracle": oracle, "passed": gate_ok,
    }
    with open(f"baseline-results/gate_{task_id}.json", "w") as f:
        json.dump(per_task, f, indent=2)
    
    with open("baseline-results/gate.json", "w") as f:
        json.dump({"noop": noop, "oracle": oracle, "passed": gate_ok}, f, indent=2)
    if not gate_ok:
        raise RuntimeError(f"Gate failed on {task_id}")
    if MODE == "baselines":
        return noop, oracle, None

    # --- model run ---
    reset = requests.post(f"{SIM_URL}/reset",
                          json={"task_id": task_id, "seed": seed},
                          timeout=30).json()
    session_id = reset["session_id"]
    init_state = reset["state"]

    tools = [{
        "type": "function",
        "function": {
            "name": "dispatch_fleet",
            "description": "Send atomic step actions to AMRs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "actions": {
                        "type": "object",
                        "minProperties": 1,
                        "additionalProperties": {"type": "string"},
                    }
                },
                "required": ["actions"],
            },
        },
    }]

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    system_msg = {
        "role": "system",
        "content": (
            "You are the Automated Warehouse Dispatcher AI.\n"
            "You control a fleet of Autonomous Mobile Robots (AMRs).\n"
            "You MUST use the `dispatch_fleet` tool on EVERY turn to move the robots.\n"
            "Do not reply with plain text. Output a tool call.\n\n"
            "Available actions: MOVE_UP, MOVE_DOWN, MOVE_LEFT, MOVE_RIGHT, WAIT, PICKUP, DROPOFF.\n"
            "Example: dispatch_fleet(actions={\"AMR_1\": \"MOVE_UP\", \"AMR_2\": \"WAIT\"})\n\n"
            "Goal:\n"
            "1. Move an AMR to the 'O' (Order) cell.\n"
            "2. Use PICKUP.\n"
            "3. Move to the 'P' (Pack Station) cell.\n"
            "4. Use DROPOFF.\n"
            + appended_instructions
        ),
    }
    initial_user_msg = {
        "role": "user",
        "content": (f"Task: {task_id}. Seed: {seed}.\n"
                    f"Radar Map:\n{init_state['ascii_map']}\n\n"
                    f"Fleet: {json.dumps(init_state['fleet'])}\n"
                    f"Orders: {json.dumps(init_state['orders'])}"),
    }

    recent_steps = [initial_user_msg]
    start = time.time()
    step = 0
    done = False

    while step < STEP_CAP and (time.time() - start) < WALLCLOCK_CAP and not done:
        step += 1
        ctx = trim_context(None, system_msg, initial_user_msg, recent_steps)
        if approx_tokens(ctx) > CONTEXT_BUDGET_TOKENS:
            # hard fail-safe: drop oldest steps
            recent_steps = recent_steps[-4:]

        call_start = time.time()
        try:
            resp = client.chat.completions.create(
                model=MODEL, messages=ctx, tools=tools,
                tool_choice={"type": "function", "function": {"name": "dispatch_fleet"}},
                timeout=120,
            )
            latency = int((time.time() - call_start) * 1000)
        except Exception as e:
            emit({"step": step, "error": str(e), "termination": "model_error"})
            break

        msg = resp.choices[0].message
        parsed, tool_results, parse_error = [], [], None

        assistant_msg = {
            "role": "assistant",
            "content": msg.content or "",
        }
        if msg.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        recent_steps.append(assistant_msg)

        if not msg.tool_calls:
            tool_results.append("No tool call issued. Reply with a dispatch_fleet tool call.")
        else:
            for tc in msg.tool_calls[:MAX_TOOL_CALLS]:
                try:
                    args = json.loads(tc.function.arguments)
                    if tc.function.name != "dispatch_fleet":
                        raise ValueError(f"unknown tool {tc.function.name}")
                except Exception as e:
                    parse_error = f"Unreadable tool call: {e}. Defaulting to WAIT."
                    parsed.append({"tool": "dispatch_fleet",
                                   "args": {"actions": {}},
                                   "parse_error": parse_error})
                    recent_steps.append({
                        "role": "tool", "tool_call_id": tc.id,
                        "content": parse_error,
                    })
                    continue

                parsed.append({"tool": tc.function.name, "args": args})
                try:
                    sr = requests.post(f"{SIM_URL}/step",
                                       json={"session_id": session_id,
                                             "actions": args.get("actions", {})},
                                       timeout=TOOL_CALL_TIMEOUT).json()
                except requests.Timeout:
                    recent_steps.append({
                        "role": "tool", "tool_call_id": tc.id,
                        "content": "Tool timeout after 60s; step skipped.",
                    })
                    continue

                st = sr["state"]; done = sr.get("done", False)
                obs = (f"Step {st['step']}/{st['max_steps']}. "
                       f"Collisions: {st['collisions']}\nMap:\n{st['ascii_map']}\n"
                       f"Fleet: {json.dumps(st['fleet'])}\n"
                       f"Orders: {json.dumps(st['orders'])}")
                tool_results.append(obs)
                recent_steps.append({"role": "tool",
                                     "tool_call_id": tc.id, "content": obs})

        emit({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "step": step, "task_id": task_id, "seed": seed,
            "model_input": ctx,
            "model_output_raw": msg.content or "",
            "parsed_actions": parsed,
            "tool_result": tool_results,
            "state_hash": init_state.get("state_hash"),
            "errors": [parse_error] if parse_error else [],
            "latency_ms": latency,
            "done": done,
        })
        if done:
            break

    final = requests.get(f"{SIM_URL}/evaluate/{session_id}", timeout=30).json()
    emit({"timestamp": datetime.now(timezone.utc).isoformat(),
          "task_id": task_id, "seed": seed, "final": final,
          "termination": "success" if done else "step_cap"})
    print(f">>> {task_id} final score: {final.get('score')}")
    return noop, oracle, final.get("score")


if __name__ == "__main__":
    if MODE == "all":
        results = {}
        for tid in TASK_REGISTRY:
            results[tid] = run_one_task(tid, SEED)
        print("\nALL RESULTS:", json.dumps(results, indent=2))
    else:
        run_one_task(TASK_ID, SEED)