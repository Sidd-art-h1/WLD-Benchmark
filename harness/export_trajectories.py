import json
import glob
import os

os.makedirs("sample-trajectories", exist_ok=True)
log_files = glob.glob("harness/logs/*.jsonl")

for idx, filepath in enumerate(log_files):
    out_path = f"sample-trajectories/trajectory_{idx+1}.md"
    with open(filepath, "r") as f, open(out_path, "w") as out:
        out.write(f"# Trajectory Run {idx+1}\n\n")
        for line in f:
            step_data = json.loads(line)
            step = step_data.get("step")
            out.write(f"## Step {step}\n")
            out.write(f"- **State Hash:** `{step_data.get('state_hash')}`\n")
            out.write(f"- **Actions:** `{step_data.get('parsed_actions')}`\n")
            out.write(f"- **Latency:** {step_data.get('latency_ms')} ms\n")
            if step_data.get("done"):
                out.write(f"- **Final Reward:** {step_data.get('reward')}\n")
                out.write(f"- **Details:** {json.dumps(step_data.get('details'))}\n")
            out.write("\n---\n\n")

print(f"Exported {len(log_files)} readable trajectories to ./sample-trajectories/")