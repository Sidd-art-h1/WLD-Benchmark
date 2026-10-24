import hashlib
from fastapi import FastAPI
from pydantic import BaseModel
from sim_engine import WarehouseSimulator

app = FastAPI()
sessions = {}

class ResetRequest(BaseModel):
    task_id: str
    seed: int

class StepRequest(BaseModel):
    session_id: str
    actions: dict

@app.post("/reset")
def reset(req: ResetRequest):
    session_id = f"{req.task_id}_{req.seed}"
    sim = WarehouseSimulator(task_id=req.task_id, seed=req.seed)
    sessions[session_id] = sim
    
    state_hash = hashlib.sha256(f"{req.task_id}_{req.seed}".encode()).hexdigest()[:8]
    return {
        "session_id": session_id,
        "state_hash": state_hash,
        "state": sim.get_state()
    }

@app.post("/step")
def step(req: StepRequest):
    sim = sessions.get(req.session_id)
    if not sim:
        return {"error": "Invalid session"}
    state, done = sim.step(req.actions)
    return {"state": state, "done": done}

@app.get("/evaluate/{session_id}")
def evaluate(session_id: str):
    sim = sessions.get(session_id)
    if not sim:
        return {"score": 0.0, "error": "Session missing"}
    return sim.evaluate()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7000)