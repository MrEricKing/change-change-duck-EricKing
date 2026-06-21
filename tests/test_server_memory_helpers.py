import unittest

import server


class ServerMemoryHelpersTest(unittest.TestCase):
    def test_as_bool_accepts_frontend_values(self):
        self.assertTrue(server._as_bool(True))
        self.assertTrue(server._as_bool("true"))
        self.assertTrue(server._as_bool("on"))
        self.assertTrue(server._as_bool("是"))
        self.assertFalse(server._as_bool(False))
        self.assertFalse(server._as_bool("false"))
        self.assertTrue(server._as_bool(None, True))

    def test_inject_memory_text_keeps_current_request_first(self):
        text = server._inject_memory_text("想轻松一点", "用户偏好本地小吃")

        self.assertIn("想轻松一点", text)
        self.assertIn("【个人旅行记忆】", text)
        self.assertIn("用户偏好本地小吃", text)
        self.assertIn("以本次要求为准", text)

    def test_empty_memory_context_does_not_change_text(self):
        self.assertEqual(server._inject_memory_text("原始要求", ""), "原始要求")

    def test_selected_memory_ids_distinguishes_legacy_and_empty_selection(self):
        self.assertIsNone(server._selected_memory_ids({}))
        self.assertEqual(server._selected_memory_ids({"selected_memory_ids": []}), [])
        self.assertEqual(server._selected_memory_ids({"selected_memory_ids": "a,b"}), ["a", "b"])

    def test_record_from_post_trip_body_accepts_inline_record(self):
        record = server._record_from_post_trip_body({
            "record": {
                "title": "东京复盘",
                "actual_places": ["浅草寺"],
                "review_text": "视频推荐基本靠谱。",
            }
        }, {"title": "东京四日游攻略", "itinerary": []})

        self.assertEqual(record["title"], "东京复盘")
        self.assertEqual(record["actual_places"], ["浅草寺"])
        self.assertEqual(record["linked_plan"]["title"], "东京四日游攻略")


if __name__ == "__main__":
    unittest.main()
