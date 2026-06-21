import tempfile
import unittest
from pathlib import Path

import travel_memory


class TravelMemoryTest(unittest.TestCase):
    def test_add_and_list_memory(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "memory.json"
            saved = travel_memory.add_memory({
                "trip_title": "杭州两日游复盘",
                "destination": "杭州",
                "liked": ["城市漫步", "本地小吃"],
                "disliked": "排队网红店",
                "pace_preference": "每天3-4个主要地点最舒适",
                "source_text": "原始复盘",
            }, path=path)

            self.assertTrue(saved["id"])
            memories = travel_memory.list_memories(path)
            self.assertEqual(len(memories), 1)
            self.assertEqual(memories[0]["disliked"], ["排队网红店"])

    def test_retrieve_builds_explainable_context(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "memory.json"
            travel_memory.add_memory({
                "trip_title": "杭州两日游复盘",
                "destination": "杭州",
                "liked": ["城市漫步", "本地小吃", "节奏宽松"],
                "disliked": ["排队网红店", "频繁换乘"],
                "pace_preference": "每天3-4个主要地点最舒适",
                "traffic_preference": "优先同一区域步行和地铁串联",
                "lessons": ["下午应留出休息时间"],
                "source_text": "喜欢小巷美食，不喜欢赶路",
            }, path=path)

            result = travel_memory.retrieve_memories({
                "destination": "成都",
                "travel_style": "轻松型",
                "themes": ["美食巡游", "城市漫步"],
                "extra": "想轻松一点，多吃本地小吃，别频繁换乘",
            }, path=path)

            self.assertEqual(len(result["matches"]), 1)
            self.assertIn("本地小吃", result["context"])
            self.assertIn("只作为偏好证据", result["context"])

    def test_annotate_plan_with_memory(self):
        retrieval = {
            "context": "用户偏好城市漫步。",
            "matches": [{
                "score": 3.5,
                "memory": {
                    "id": "m1",
                    "trip_title": "杭州两日游复盘",
                    "destination": "杭州",
                    "liked": ["城市漫步"],
                    "disliked": ["排队"],
                },
                "reasons": ["关键词相关：城市漫步"],
            }],
        }
        plan = {"summary": {"total_cost": 1000}}
        travel_memory.annotate_plan_with_memory(plan, retrieval)

        self.assertEqual(plan["summary"]["memory_context"], "用户偏好城市漫步。")
        self.assertEqual(plan["summary"]["memory_matches"][0]["trip_title"], "杭州两日游复盘")


if __name__ == "__main__":
    unittest.main()
