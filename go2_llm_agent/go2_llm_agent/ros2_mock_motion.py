import time

class MockMotionController:
    def start(self):
        print("[MOCK] Controller started")

    def walk(self, duration_s=0.05, speed_mps=0.3):
        print(f"[MOCK] walk(duration_s={duration_s}, speed_mps={speed_mps})")
        time.sleep(duration_s)

    def turn_in_place(self, duration_s=0.05, angular_z=0.8):
        print(f"[MOCK] turn_in_place(duration_s={duration_s}, angular_z={angular_z})")
        time.sleep(duration_s)

    def sit(self, duration_s=0.05):
        print(f"[MOCK] sit(duration_s={duration_s})")
        time.sleep(duration_s)

    def stretch(self, duration_s=0.05):
        print(f"[MOCK] stretch(duration_s={duration_s})")
        time.sleep(duration_s)

    def stand_up(self):
        print("[MOCK] stand_up()")

    def stand_down(self):
        print("[MOCK] stand_down()")

    def recovery_stand(self):
        print("[MOCK] recovery_stand()")

    def say(self, text: str):
        print(f"[MOCK] say: {text}")

    MOCK_SCENE = {
        "person_1": {"x": 1.23, "y": 0.45},
        "chair_1": {"x": 2.10, "y": -0.30}
    }

    def get_detections(self):
        print("[MOCK] get_detections()")
        return self.MOCK_SCENE

    def find_object(self, label: str):
        print(f"[MOCK] find_object({label})")

        if not label:
            return None

        detections = self.get_detections()

        # exact key match
        if label in detections:
            return detections[label]

        # base label match, like "chair" -> "chair_1"
        for obj_id, obj_data in detections.items():
            if obj_id.split("_")[0].lower() == label.lower():
                return obj_data

        return None