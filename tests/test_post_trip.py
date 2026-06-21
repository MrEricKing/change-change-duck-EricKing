import tempfile
import unittest
from pathlib import Path

import post_trip


class PostTripTest(unittest.TestCase):
    def test_add_and_list_record_with_plan_snapshot(self):
        plan = {
            "title": "东京四日游攻略",
            "city": "东京",
            "days": 4,
            "summary": {"total_cost": 3200, "route_logic": "分区游玩"},
            "itinerary": [
                {"day": 1, "stops": [{"place": "浅草寺"}, {"place": "晴空塔"}]},
                {"day": 2, "stops": [{"place": "新宿"}]},
            ],
            "video_contributions": [{"filename": "a.mp4", "contribution": 60}],
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "post_trip_records.json"
            saved = post_trip.add_record({
                "actual_places": "浅草寺\n晴空塔",
                "skipped_places": "新宿，因为太累",
                "actual_cost": "¥3100",
                "review_text": "浅草寺人很多，但晴空塔夜景值得。",
            }, plan=plan, path=path)

            self.assertTrue(saved["id"])
            self.assertEqual(saved["title"], "东京四日游攻略真实复盘")
            self.assertEqual(saved["actual_places"], ["浅草寺", "晴空塔"])
            self.assertEqual(saved["linked_plan"]["planned_places"], ["浅草寺", "晴空塔", "新宿"])

            records = post_trip.list_records(path)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["actual_cost"], "¥3100")

    def test_record_review_text_includes_fact_fields(self):
        text = post_trip.record_review_text({
            "title": "杭州复盘",
            "actual_places": ["西湖"],
            "skipped_places": ["灵隐寺"],
            "added_places": ["本地小吃店"],
            "actual_pace": "偏赶",
            "review_text": "下午明显累了。",
            "photos": [{"name": "westlake.jpg"}],
        })

        self.assertIn("实际去了：西湖", text)
        self.assertIn("没去成：灵隐寺", text)
        self.assertIn("新增发现：本地小吃店", text)
        self.assertIn("照片素材：westlake.jpg", text)


if __name__ == "__main__":
    unittest.main()
