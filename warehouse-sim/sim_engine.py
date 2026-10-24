import random

class WarehouseSimulator:
    def __init__(self, task_id: str, seed: int):
        self.task_id = task_id
        self.seed = seed
        self.rng = random.Random(seed)
        self.step_count = 0
        self.max_steps = 40
        self.is_done = False
        
        self.width, self.height = 12, 12
        self.num_amrs = 4
        self.num_orders = 4

        self.charging_pads = [[0, 0], [1, 0], [0, 1], [1, 1]]
        
        # 4 dedicated dropoff stations - one at the head of each lane
        self.pack_stations = [
            [1, self.height - 1],
            [4, self.height - 1],
            [7, self.height - 1],
            [10, self.height - 1]
        ]
        
        # 4 AMRs starting at the bottom of their respective corridors
        self.amrs = {}
        for i in range(self.num_amrs):
            lane_x = i * 3 + 1
            self.amrs[f"AMR_{i+1}"] = {
                "pos": [lane_x, 0],
                "battery": 100.0,
                "carrying": None,
                "deadlocked": False,
                "immobilized": False
            }
            
        # 4 deterministic orders generated strictly within each AMR's dedicated corridor
        self.orders = {}
        for i in range(self.num_orders):
            lane_min_x = i * 3
            lane_max_x = i * 3 + 2
            px = self.rng.randint(lane_min_x, lane_max_x)
            py = self.rng.randint(2, self.height - 3)
            
            self.orders[f"ORD_{i+1}"] = {
                "pickup": [px, py],
                "drop": list(self.pack_stations[i]),
                "deadline": 38,
                "status": "PENDING",
                "fulfilled_at": None
            }
            
        self.collisions_recorded = 0

    def step(self, actions: dict):
        if self.is_done:
            return self.get_state(), True

        self.step_count += 1
        new_positions = {}
        intended_moves = {}

        for amr_id, amr in self.amrs.items():
            if amr["immobilized"]:
                new_positions[amr_id] = list(amr["pos"])
                continue

            cmd = str(actions.get(amr_id, "WAIT")).upper()
            curr_x, curr_y = amr["pos"]
            next_x, next_y = curr_x, curr_y

            if cmd == "MOVE_UP" and curr_y < self.height - 1:
                next_y += 1
            elif cmd == "MOVE_DOWN" and curr_y > 0:
                next_y -= 1
            elif cmd == "MOVE_RIGHT" and curr_x < self.width - 1:
                next_x += 1
            elif cmd == "MOVE_LEFT" and curr_x > 0:
                next_x -= 1

            intended_moves[amr_id] = [next_x, next_y]

        occupied_slots = {}
        for amr_id, target in intended_moves.items():
            t_tuple = tuple(target)

            swap_conflict = False
            for other_id, other_target in intended_moves.items():
                if amr_id != other_id:
                    if target == self.amrs[other_id]["pos"] and intended_moves[other_id] == self.amrs[amr_id]["pos"]:
                        swap_conflict = True
                        break

            if t_tuple in occupied_slots or swap_conflict:
                self.collisions_recorded += 1
                new_positions[amr_id] = list(self.amrs[amr_id]["pos"])
            else:
                occupied_slots[t_tuple] = amr_id
                new_positions[amr_id] = target

        for amr_id, amr in self.amrs.items():
            amr["pos"] = new_positions.get(amr_id, amr["pos"])

            drain = 0.3 if amr["carrying"] else 0.1
            if amr["pos"] in self.charging_pads:
                amr["battery"] = min(100.0, amr["battery"] + 25.0)
            else:
                amr["battery"] = max(0.0, amr["battery"] - drain)

            if amr["battery"] <= 0.0:
                amr["immobilized"] = True

            cmd = str(actions.get(amr_id, "")).upper()
            if cmd == "PICKUP" and not amr["carrying"]:
                for ord_id, ord_info in self.orders.items():
                    if ord_info["status"] == "PENDING" and ord_info["pickup"] == amr["pos"]:
                        ord_info["status"] = "IN_TRANSIT"
                        amr["carrying"] = ord_id
                        break
            elif cmd == "DROPOFF" and amr["carrying"]:
                ord_id = amr["carrying"]
                if self.orders[ord_id]["drop"] == amr["pos"]:
                    self.orders[ord_id]["status"] = "FULFILLED"
                    self.orders[ord_id]["fulfilled_at"] = self.step_count
                    amr["carrying"] = None

        for ord_id, ord_info in self.orders.items():
            if ord_info["status"] in ["PENDING", "IN_TRANSIT"] and self.step_count > ord_info["deadline"]:
                ord_info["status"] = "FAILED_SLA"

        all_fulfilled = all(o["status"] == "FULFILLED" for o in self.orders.values())
        if self.step_count >= self.max_steps or all_fulfilled:
            self.is_done = True

        return self.get_state(), self.is_done

    def get_state(self) -> dict:
        grid = [["." for _ in range(self.width)] for _ in range(self.height)]
        for cx, cy in self.charging_pads:
            grid[cy][cx] = "C"
        for px, py in self.pack_stations:
            grid[py][px] = "P"
        for ord_id, ord_info in self.orders.items():
            if ord_info["status"] == "PENDING":
                grid[ord_info["pickup"][1]][ord_info["pickup"][0]] = "O"
        for amr_id, amr in self.amrs.items():
            tag = amr_id.split("_")[1]
            grid[amr["pos"][1]][amr["pos"][0]] = tag

        ascii_map = "\n".join(["".join(row) for row in reversed(grid)])

        return {
            "step": self.step_count,
            "max_steps": self.max_steps,
            "ascii_map": ascii_map,
            "fleet": {k: {"pos": v["pos"], "battery": round(v["battery"], 1), "carrying": v["carrying"], "stuck": v["immobilized"]} for k, v in self.amrs.items()},
            "orders": {k: {"status": v["status"], "pickup": v["pickup"], "drop": v["drop"], "deadline": v["deadline"]} for k, v in self.orders.items()},
            "collisions": self.collisions_recorded
        }

    def evaluate(self) -> dict:
        total = len(self.orders)
        fulfilled = sum(1 for o in self.orders.values() if o["status"] == "FULFILLED")
        on_time = sum(
            1 for o in self.orders.values() 
            if o["status"] == "FULFILLED" and o.get("fulfilled_at") is not None and o["fulfilled_at"] <= o["deadline"]
        )
        immobilized_count = sum(1 for a in self.amrs.values() if a["immobilized"])

        order_score = (fulfilled / total) * 0.70 if total > 0 else 0.0
        sla_score = (on_time / total) * 0.30 if total > 0 else 0.0
        collision_penalty = min(0.05, self.collisions_recorded * 0.01)
        battery_penalty = min(0.10, immobilized_count * 0.05)

        final_score = max(0.0, min(1.0, order_score + sla_score - collision_penalty - battery_penalty))

        return {
            "score": round(final_score, 2),
            "orders_fulfilled": f"{fulfilled}/{total}",
            "on_time_deliveries": on_time,
            "collisions": self.collisions_recorded,
            "immobilized_amrs": immobilized_count
        }
