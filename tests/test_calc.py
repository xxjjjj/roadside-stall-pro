import importlib.util
import json
import tempfile
import types
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("stall_calc", BASE / "scripts" / "stall_calc.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

MENU_JSON = (BASE / "tests" / "fixtures" / "menu.json").read_text(encoding="utf-8")


def ns(**kw):
    base = dict(display_name=None, group=None, pricing=None, sells=None,
                note=None, menu_json=None, ensure=False, city=None, address=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


class MarketTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        mod.HOME = Path(self._tmp.name)
        # 通用流程：新摊位直接带着样例价目建档（转发消息即建档）
        mod.cmd_new_vendor(ns(
            vendor="kun-ge-bbq", display_name="坤哥路边烧烤",
            pricing="fixed", menu_json=MENU_JSON,
        ))

    def tearDown(self):
        self._tmp.cleanup()

    def test_empty_home_starts_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod.HOME = Path(tmp)
            self.assertEqual(mod.list_vendors(), [])
            self.assertIn("还没有任何摊位", mod.render_vendors())

    def test_calc_classic_case(self):
        menu = mod.load_menu("kun-ge-bbq")
        out = mod.calculate({"orders": [
            {"person": "晶晶", "item": "羊肉", "qty": 10},
            {"person": "晶晶", "item": "牛肉", "qty": 5},
            {"person": "小刘", "item": "鸡皮", "qty": 3},
            {"person": "小刘", "item": "面筋", "qty": 2},
            {"person": "小刘", "item": "小饼", "qty": 1},
            {"person": "小刘", "item": "鸡皮", "qty": 5, "action": "set"},
        ], "_vendor": "kun-ge-bbq"}, menu)
        self.assertEqual(out["confirmed_total"], "47")
        self.assertEqual([x["subtotal"] for x in out["people"]], ["30", "17"])
        self.assertIn("坤哥", out["group_message"])

    def test_ambiguous_not_counted(self):
        out = mod.calculate({"orders": [{"item": "五花肉", "qty": 4}]}, mod.load_menu("kun-ge-bbq"))
        self.assertEqual(out["confirmed_total"], "0")
        self.assertEqual(len(out["pending"]), 1)

    def test_new_clue_vendor_without_price(self):
        mod.cmd_new_vendor(ns(
            vendor="wang-jie-bing", display_name="王姐饼摊", group="楼下小卖铺群",
            pricing="none", sells="鸡蛋饼、酱香饼",
        ))
        prof = mod.load_profile("wang-jie-bing")
        self.assertEqual(prof["pricing"], "none")
        self.assertEqual(prof["group"], "楼下小卖铺群")
        self.assertIsNone(mod.load_menu("wang-jie-bing"))
        self.assertEqual(len(mod.list_vendors()), 2)

    def test_search_finds_clue_and_menu(self):
        mod.cmd_new_vendor(ns(
            vendor="wang-jie-bing", display_name="王姐饼摊", group="楼下小卖铺群",
            pricing="none", sells="鸡蛋饼、酱香饼",
        ))
        hits = mod.cmd_search("鸡蛋饼")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["id"], "wang-jie-bing")
        hits2 = mod.cmd_search("羊肉")
        self.assertEqual(len(hits2), 1)
        self.assertEqual(hits2[0]["id"], "kun-ge-bbq")
        self.assertIn("鲜羊肉串", hits2[0]["matched_items"])

    def test_menu_diff_and_update_log(self):
        new_menu = json.loads(MENU_JSON)
        for it in new_menu["items"]:
            if it["name"] == "鲜羊肉串":
                it["price_cents"] = 250
        new_menu["items"].append({"name": "烤韭菜", "price_cents": 200, "aliases": ["韭菜"]})
        changes = mod.menu_diff("kun-ge-bbq", new_menu)
        self.assertEqual({c["item"] for c in changes}, {"鲜羊肉串", "烤韭菜"})
        mod.update_menu("kun-ge-bbq", new_menu, source="test")
        log = mod.read_json(mod.vendor_dir("kun-ge-bbq") / "price-log.json", [])
        # 建档一次 + 本次更新一次
        self.assertEqual(len(log), 2)
        self.assertEqual(log[-1]["source"], "test")
        out = mod.calculate({"orders": [{"item": "羊肉", "qty": 10}]}, mod.load_menu("kun-ge-bbq"))
        self.assertEqual(out["confirmed_total"], "25")

    def test_daily_vendor_flow(self):
        day1 = {"items": [{"name": "砀山梨", "price_cents": 300, "aliases": ["梨"]},
                          {"name": "冬枣", "price_cents": 800, "aliases": ["枣"]}]}
        mod.cmd_new_vendor(ns(
            vendor="fruit-stall", display_name="路口水果摊", group="水果到货群",
            pricing="daily", sells="时令水果", menu_json=json.dumps(day1, ensure_ascii=False),
        ))
        out = mod.calculate({"orders": [{"item": "梨", "qty": 2}]}, day1)
        self.assertEqual(out["confirmed_total"], "6")
        day2 = {"items": [{"name": "砀山梨", "price_cents": 250, "aliases": ["梨"]}]}
        changes = mod.menu_diff("fruit-stall", day2)
        self.assertEqual(changes[0]["change"], "price")
        mod.update_menu("fruit-stall", day2, source="日更")
        out2 = mod.calculate({"orders": [{"item": "梨", "qty": 2}]}, mod.load_menu("fruit-stall"))
        self.assertEqual(out2["confirmed_total"], "5")

    def test_save_base_last_stats_per_vendor(self):
        menu = mod.load_menu("kun-ge-bbq")
        first = mod.calculate({"orders": [{"item": "羊肉", "qty": 10}]}, menu)
        mod.save_last("kun-ge-bbq", first)
        base = mod.last_rows("kun-ge-bbq")
        self.assertEqual(base, [{"person": "我", "item": "鲜羊肉串", "qty": 10, "action": "add"}])
        again = mod.calculate({"orders": base + [{"item": "脆骨", "qty": 2}]}, menu)
        self.assertEqual(again["confirmed_total"], "25")
        stats = mod.render_stats("kun-ge-bbq")
        self.assertIn("共 1 单", stats)
        self.assertIn("累计", stats)

    def test_city_recorded_and_searchable(self):
        mod.cmd_new_vendor(ns(
            vendor="gz-fruit", display_name="广州水果摊", group="水果群",
            pricing="daily", sells="水果", city="广州", address="珠江新城",
            menu_json=json.dumps({"items": [{"name": "荔枝", "price_cents": 1500, "aliases": ["妃子笑"]}]}, ensure_ascii=False),
        ))
        # 列表带城市
        row = [r for r in mod.list_vendors() if r["id"] == "gz-fruit"][0]
        self.assertEqual(row["city"], "广州")
        self.assertEqual(row["address"], "珠江新城")
        # 档案带城市
        prof = mod.render_profile("gz-fruit")
        self.assertIn("广州", prof)
        # 按城市搜得到
        hits = mod.cmd_search("广州")
        self.assertEqual([h["id"] for h in hits], ["gz-fruit"])

    def test_vendors_are_isolated(self):
        mod.cmd_new_vendor(ns(
            vendor="fruit-stall", display_name="水果摊", group="g", pricing="daily",
            sells="水果", menu_json=json.dumps({"items": [{"name": "苹果", "price_cents": 500}]}, ensure_ascii=False),
        ))
        mod.save_last("fruit-stall", mod.calculate({"orders": [{"item": "苹果", "qty": 1}]},
                                                   mod.load_menu("fruit-stall")))
        self.assertEqual(mod.last_rows("kun-ge-bbq"), [])
        self.assertEqual(len(mod.load_orders("fruit-stall")["log"]), 1)


if __name__ == "__main__":
    unittest.main()
