#!/usr/bin/env python3
"""路边摊 Pro · 多摊位点单/货源记录脚本。仅标准库，无网络。

写盘只发生在显式操作：--new-vendor / --ensure-vendor / --update-menu / --save / --clear-last。
其余一律只读。数据目录：~/.roadside-stall/（环境变量 ROADSIDE_STALL_HOME 可改）。
"""
import argparse
import json
import os
import re
import shutil
import sys
from collections import OrderedDict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SEEDS = SKILL_DIR / "seeds"
HOME = Path(
    os.environ.get("ROADSIDE_STALL_HOME")
    or str(Path.home() / ".roadside-stall")
)
LOG_LIMIT = 200

# 摊位四档：
# none     线索：只有群名/人名/卖什么，没有价格
# fixed    雷打不动：价目基本不变，变价必须人工确认
# daily    每天更新：每日新价目，入库前要用户确认
# informal 群里随口报：消息里抓当日口头价，输出时标注来源
PRICING_MODES = ("none", "fixed", "daily", "informal")
PRICING_LABELS = {
    "none": "线索（没价格，只记群名/人名/卖什么）",
    "fixed": "雷打不动（价目基本不变，变价要人工确认）",
    "daily": "每天更新（每日新价目，入库并回显差异）",
    "informal": "群里随口报（当日口头价，标注来源）",
}


def die(msg):
    print(msg, file=sys.stderr)
    raise SystemExit(1)


def money(cents):
    return f"{cents / 100:.2f}".rstrip("0").rstrip(".")


def norm(s):
    return "".join(str(s).strip().lower().split()).replace("　", "")


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


# ---------- 摊位存储 ----------

def vendor_dir(vendor):
    if not isinstance(vendor, str) or not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", vendor) or len(vendor) > 64:
        die(f"摊位 id 不合法，须为 kebab-case 英文/数字且不超过64字符: {vendor!r}")
    return HOME / "vendors" / vendor


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise ValueError(f"数据文件损坏，已停止以免覆盖历史数据：{path}: {exc}") from exc


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def seed_vendor(vendor):
    """把包内种子摊位拷到用户数据目录；已存在或没有种子则不动。"""
    src = SEEDS / vendor
    dst = vendor_dir(vendor)
    if dst.exists() or not (src / "menu.json").is_file():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)


def require_vendor(vendor):
    seed_vendor(vendor)
    d = vendor_dir(vendor)
    if not (d / "profile.json").is_file():
        die(f"没有这个摊位: {vendor}（先用 --new-vendor 建）")
    return d


def load_profile(vendor):
    return read_json(vendor_dir(vendor) / "profile.json", {})


def load_menu(vendor):
    return read_json(vendor_dir(vendor) / "menu.json", None)


def load_orders(vendor):
    return read_json(vendor_dir(vendor) / "orders.json", {})


def list_vendors():
    rows = []
    seen = set()
    for base in (HOME / "vendors", SEEDS):
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            if not d.is_dir() or d.name in seen:
                continue
            prof = read_json(d / "profile.json", {})
            menu = read_json(d / "menu.json", {})
            if not prof and not menu:
                continue
            seen.add(d.name)
            rows.append({
                "id": d.name,
                "name": prof.get("name") or d.name,
                "city": prof.get("city", ""),
                "address": prof.get("address", ""),
                "group": prof.get("group", ""),
                "pricing": prof.get("pricing", "none"),
                "sells": prof.get("sells", ""),
                "items": len(menu.get("items", [])) if isinstance(menu, dict) else 0,
                "in_home": (vendor_dir(d.name) / "profile.json").is_file(),
                "note": prof.get("note", ""),
            })
    return rows


# ---------- 价目表 ----------

def validate_menu(menu):
    if not isinstance(menu, dict) or not isinstance(menu.get("items"), list):
        die("价目表必须是含 items 数组的 JSON")
    aliases = {}
    seen_names = set()
    for obj in menu["items"]:
        if not isinstance(obj, dict) or not isinstance(obj.get("name"), str) or not obj["name"].strip():
            die(f"价目条目缺 name: {obj!r}")
        name = obj["name"].strip()
        name_key = norm(name)
        if name_key in seen_names:
            die(f"重复菜名: {name}")
        seen_names.add(name_key)
        price = obj.get("price_cents")
        if not isinstance(price, int) or isinstance(price, bool) or price <= 0:
            die(f"价格必须是正整数（分）: {name}")
        alias_list = obj.get("aliases", [])
        if not isinstance(alias_list, list) or not all(isinstance(a, str) and a.strip() for a in alias_list):
            die(f"菜品 aliases 必须是非空字符串数组: {name}")
        if "unit" in obj and (not isinstance(obj["unit"], str) or not obj["unit"].strip()):
            die(f"unit 必须是非空字符串: {name}")
        for a in [name, *alias_list]:
            key = norm(a)
            if key in aliases and aliases[key] != name:
                die(f"同一别名指向两个菜: {a}")
            aliases[key] = name
    ambiguous = menu.get("ambiguous_aliases", {})
    if not isinstance(ambiguous, dict):
        die("ambiguous_aliases 必须是对象")
    for alias in ambiguous:
        if norm(alias) in aliases:
            die(f"歧义别名与明确菜名冲突: {alias}")
    return menu

def catalog(menu):
    items = {i["name"]: i for i in menu["items"]}
    aliases = {}
    for obj in menu["items"]:
        for a in [obj["name"], *obj.get("aliases", [])]:
            aliases[norm(a)] = obj["name"]
    return menu, items, aliases


def resolve(name, menu, items, aliases):
    key = norm(name)
    if not key:
        return None, "菜品名称为空"
    for amb, choices in (menu.get("ambiguous_aliases") or {}).items():
        if norm(amb) == key:
            return None, "菜品有歧义，请确认：" + " / ".join(choices)
    canonical = aliases.get(key)
    if canonical:
        return canonical, None
    return None, f"菜单没有可靠匹配项：{name}。请确认实际名称及单价"


def menu_diff(vendor, new_menu):
    """新旧价目对比。只报差异，不写盘。"""
    old = load_menu(vendor) or {"items": []}
    old_map = {i["name"]: i.get("price_cents") for i in old.get("items", [])}
    new_map = {i["name"]: i.get("price_cents") for i in new_menu.get("items", [])}
    changes = []
    for name, cents in new_map.items():
        if name not in old_map:
            changes.append({"item": name, "change": "new", "old": None, "new": cents})
        elif old_map[name] != cents:
            changes.append({"item": name, "change": "price", "old": old_map[name], "new": cents})
    for name, cents in old_map.items():
        if name not in new_map:
            changes.append({"item": name, "change": "removed", "old": cents, "new": None})
    return changes


def verify_menu_change(vendor, new_menu, pricing, confirm_fixed=False, allow_remove=False):
    """显式禁止固定价静默变化与不完整菜单覆盖删除旧商品。"""
    changes = menu_diff(vendor, new_menu)
    removed = [x["item"] for x in changes if x["change"] == "removed"]
    if removed and not allow_remove:
        die("新菜单缺少旧商品，已阻止覆盖（可能只是部分价目）。要确实删除请明确 --allow-remove-items：" + "、".join(removed))
    if pricing == "fixed" and not confirm_fixed and any(c["change"] in ("price", "removed") for c in changes):
        die("固定价摊位检测到改价/删除；请先向用户确认，然后使用 --confirm-fixed-price-change")
    return changes


def update_menu(vendor, menu, source):
    """覆盖价目并把变更写入 price-log。调用前必须已经过用户确认。"""
    validate_menu(menu)
    changes = menu_diff(vendor, menu)
    write_json(vendor_dir(vendor) / "menu.json", menu)
    prof = load_profile(vendor)
    prof["price_updated_at"] = now_iso()
    write_json(vendor_dir(vendor) / "profile.json", prof)
    log = read_json(vendor_dir(vendor) / "price-log.json", [])
    log.append({"date": now_iso(), "source": source, "changes": changes})
    write_json(vendor_dir(vendor) / "price-log.json", log[-LOG_LIMIT:])
    return changes


# ---------- 点单计算（沿用坤哥版逻辑） ----------

def calculate(payload, menu):
    if isinstance(payload, list):
        payload = {"orders": payload}
    if not isinstance(payload, dict) or not isinstance(payload.get("orders"), list):
        raise ValueError("Input must be a JSON object containing an 'orders' array")
    _, items, aliases = catalog(menu)
    orders = OrderedDict()
    pending = []
    warnings = []
    if len(payload["orders"]) > 1000:
        raise ValueError("Too many lines: max 1000")
    for idx, row in enumerate(payload["orders"], 1):
        if not isinstance(row, dict):
            pending.append({"row": idx, "reason": "条目不是对象", "input": str(row)})
            continue
        person = str(row.get("person") or "我").strip()
        raw_name = str(row.get("item") or "").strip()
        action = str(row.get("action") or "add").strip().lower()
        if action not in ("add", "set", "subtract", "cancel"):
            pending.append({"row": idx, "person": person, "item": raw_name, "reason": f"不支持的操作: {action}"})
            continue
        row_vendor = row.get("vendor") or row.get("shop") or row.get("shop_id")
        current_vendor = payload.get("_vendor")
        if row_vendor and current_vendor and str(row_vendor) != str(current_vendor):
            pending.append({"row": idx, "person": person, "item": raw_name,
                            "reason": f"订单属于另一家店 {row_vendor}，不可并入 {current_vendor}"})
            continue
        name, error = resolve(raw_name, menu, items, aliases)
        if error:
            pending.append({"row": idx, "person": person, "item": raw_name, "reason": error})
            continue
        qty = row.get("qty")
        if action == "cancel" and qty is None:
            qty = 0
        if isinstance(qty, bool) or not isinstance(qty, int) or not 0 <= qty <= 10000:
            pending.append({"row": idx, "person": person, "item": raw_name, "reason": "数量必须是明确的非负整数（一般点单需大于0）"})
            continue
        if action in ("add", "subtract") and qty == 0:
            pending.append({"row": idx, "person": person, "item": raw_name, "reason": "增减数量必须大于0"})
            continue
        current = orders.setdefault(person, OrderedDict()).get(name, 0)
        if action == "add":
            new = current + qty
        elif action == "set":
            new = qty
        elif action == "subtract":
            if qty > current:
                pending.append({"row": idx, "person": person, "item": raw_name,
                                "reason": f"减去{qty}超过当前数量{current}，未修改"})
                continue
            new = current - qty
        else:
            new = 0
        if new > 10000:
            pending.append({"row": idx, "person": person, "item": raw_name, "reason": "最终数量不能超过10000"})
            continue
        if new:
            orders[person][name] = new
        else:
            orders[person].pop(name, None)
    people = []
    all_total = 0
    product_sum = OrderedDict()
    for person, lines in orders.items():
        if not lines:
            continue
        rows = []
        total = 0
        for name, qty in lines.items():
            price = items[name]["price_cents"]
            subtotal = price * qty
            rows.append({"item": name, "qty": qty, "unit_price": money(price), "subtotal": money(subtotal)})
            total += subtotal
            product_sum[name] = product_sum.get(name, 0) + qty
        people.append({"person": person, "items": rows, "subtotal": money(total)})
        all_total += total
    notes = payload.get("notes") or []
    if not isinstance(notes, list):
        notes = [str(notes)]
    notes = [str(n).strip() for n in notes if str(n).strip()]
    vendor = payload.get("_vendor") or ""
    vendor_name = load_profile(vendor).get("name", "") if vendor else ""
    head = f"【{vendor_name or '拼单'}｜待发送，尚未下单】" if vendor else "【拼单｜待发送，尚未下单】"
    group_lines = [head]
    for p in people:
        line = "、".join(f"{r['item']}×{r['qty']}" for r in p["items"])
        group_lines.append(f"{p['person']}：{line}（¥{p['subtotal']}）")
    if people:
        group_lines.append("合并汇总：" + "、".join(f"{name}×{qty}" for name, qty in product_sum.items()))
    group_lines.append(f"已确认合计：¥{money(all_total)}")
    if notes:
        group_lines.append("备注：" + "；".join(notes))
    if pending:
        group_lines.append(f"⚠ {len(pending)}项待确认，暂不计入合计：")
        for x in pending:
            group_lines.append(f"- {x.get('person', '我')} {x.get('item', '')}：{x['reason']}")
    group_lines.append("注：请以摊主实际报价为准。")
    return {
        "status": "needs_confirmation" if pending else "ok",
        "people": people,
        "product_summary": [{"item": k, "qty": v} for k, v in product_sum.items()],
        "confirmed_total": money(all_total),
        "pending": pending,
        "warnings": warnings,
        "notes": notes,
        "price_unit_note": menu.get("price_unit_note", ""),
        "group_message": "\n".join(group_lines),
    }


# ---------- 点单流水（每摊一份） ----------

def last_rows(vendor):
    last = load_orders(vendor).get("last")
    if not isinstance(last, dict):
        return []
    rows = []
    for row in last.get("orders", []):
        if not isinstance(row, dict):
            continue
        item, qty = row.get("item"), row.get("qty")
        if not item or not isinstance(qty, int) or isinstance(qty, bool) or qty <= 0:
            continue
        rows.append({"person": row.get("person") or "我", "item": item, "qty": qty, "action": "add"})
    return rows


def save_last(vendor, out, confirmed=True):
    """保存上次订单；只有明确已成交 confirmed=True 才累计消费。"""
    if out.get("status") != "ok" or not out.get("people"):
        raise ValueError("空订单或含待确认项，不保存也不计入消费")
    rows = []
    total_cents = 0
    for person in out["people"]:
        for row in person["items"]:
            rows.append({"person": person["person"], "item": row["item"], "qty": row["qty"]})
        total_cents += int(Decimal(str(person["subtotal"])) * 100)
    data = load_orders(vendor)
    log = data.get("log")
    log = log if isinstance(log, list) else []
    if confirmed:
        log.append({"saved_at": now_iso(), "total_cents": total_cents, "rows": rows})
    payload = {
        "version": 2,
        "updated_at": now_iso(),
        "last": {"saved_at": now_iso(), "total_cents": total_cents, "orders": rows,
                 "status": "confirmed" if confirmed else "draft"},
        "log": log[-LOG_LIMIT:],
    }
    write_json(vendor_dir(vendor) / "orders.json", payload)


def render_last(vendor):
    last = load_orders(vendor).get("last")
    if not isinstance(last, dict):
        return "这个摊位还没有存过点单记录。"
    lines = [f"## 上次的点单（{last.get('saved_at', '时间未知')}）"]
    for row in last.get("orders", []):
        lines.append(f"- {row.get('person', '我')}：{row.get('item')} × {row.get('qty')}")
    total = last.get("total_cents")
    if isinstance(total, int):
        lines.append(f"\n合计：¥{money(total)}")
    if last.get("status") == "draft":
        lines.append("状态：仅保存草稿，未计入累计消费")
    lines.append(f"\n记录位置：{vendor_dir(vendor) / 'orders.json'}")
    return "\n".join(lines)


def render_stats(vendor):
    log = load_orders(vendor).get("log")
    log = [e for e in log if isinstance(e, dict)] if isinstance(log, list) else []
    if not log:
        return "这个摊位还没有存过点单记录。"
    total = sum(int(e.get("total_cents") or 0) for e in log)
    count = len(log)
    qty_by_item = OrderedDict()
    times_by_item = {}
    for entry in log:
        for row in entry.get("rows", []):
            if not isinstance(row, dict):
                continue
            item, qty = row.get("item"), row.get("qty")
            if not item or not isinstance(qty, int) or qty <= 0:
                continue
            qty_by_item[item] = qty_by_item.get(item, 0) + qty
            times_by_item[item] = times_by_item.get(item, 0) + 1
    prof = load_profile(vendor)
    latest = log[-1]
    lines = [
        f"## {prof.get('name', vendor)} 消费记录（共 {count} 单）",
        f"- 累计：¥{money(total)}",
        f"- 单均：¥{money(int(round(total / count)))}",
        f"- 最近一单：{latest.get('saved_at', '时间未知')}，¥{money(int(latest.get('total_cents') or 0))}",
        "",
        "### 常点（按累计数量）",
    ]
    for item, qty in sorted(qty_by_item.items(), key=lambda kv: -kv[1])[:6]:
        lines.append(f"- {item}：累计 {qty} 份，点过 {times_by_item[item]} 次")
    lines.append(f"\n记录位置：{vendor_dir(vendor) / 'orders.json'}")
    return "\n".join(lines)


# ---------- 摊位档案/线索 ----------

def cmd_new_vendor(args):
    vendor = args.vendor
    seed_vendor(vendor)
    existed = (vendor_dir(vendor) / "profile.json").is_file()
    if existed and not args.ensure:
        die(f"摊位已存在: {vendor}（要改档案用 --ensure-vendor）")
    prof = load_profile(vendor) if existed else {}
    pricing = args.pricing or prof.get("pricing") or "none"
    if pricing not in PRICING_MODES:
        die(f"pricing 必须是 {'/'.join(PRICING_MODES)}")
    # 先校验所有输入，避免无效菜单留下半成品商家档案。
    new_menu = validate_menu(json.loads(args.menu_json)) if args.menu_json else None
    if existed and new_menu:
        verify_menu_change(vendor, new_menu, pricing,
                           bool(getattr(args, "confirm_fixed_price_change", False)),
                           bool(getattr(args, "allow_remove_items", False)))
    if not existed:
        prof.setdefault("id", vendor)
        prof.setdefault("created_at", now_iso())
    for key, val in (("name", args.display_name), ("group", args.group),
                     ("pricing", pricing), ("sells", args.sells),
                     ("note", args.note), ("city", args.city), ("address", args.address)):
        if val:
            prof[key] = val
    vendor_dir(vendor).mkdir(parents=True, exist_ok=True)
    write_json(vendor_dir(vendor) / "profile.json", prof)

    created_menu = None
    if new_menu:
        update_menu(vendor, new_menu, source="建档时录入" if not existed else "档案更新时录入")
        created_menu = new_menu
    parts = [f"{'档案已更新' if existed else '新摊位已建档'}：{prof.get('name', vendor)}（{vendor}）"]
    parts.append(f"价格类型：{PRICING_LABELS[prof.get('pricing', 'none')]}")
    if prof.get("city"):
        parts.append(f"城市：{prof['city']}" + (f"（{prof['address']}）" if prof.get("address") else ""))
    if prof.get("group"):
        parts.append(f"群：{prof['group']}")
    if prof.get("sells"):
        parts.append(f"卖：{prof['sells']}")
    if created_menu:
        parts.append(f"价目：{len(created_menu['items'])} 项已入库")
    elif not load_menu(vendor) and prof.get("pricing", "none") == "none":
        parts.append("（纯线索，没有价格；以后拿到价目再用 --update-menu 补）")
    print("\n".join(parts))


def render_profile(vendor):
    prof = load_profile(vendor)
    menu = load_menu(vendor) or {}
    lines = [f"## {prof.get('name', vendor)}（{vendor}）"]
    if prof.get("city"):
        lines.append(f"- 城市：{prof['city']}" + (f"，{prof['address']}" if prof.get("address") else ""))
    if prof.get("group"):
        lines.append(f"- 群：{prof['group']}")
    lines.append(f"- 价格类型：{PRICING_LABELS.get(prof.get('pricing', 'none'), prof.get('pricing'))}")
    if prof.get("sells"):
        lines.append(f"- 卖：{prof['sells']}")
    if prof.get("note"):
        lines.append(f"- 备注：{prof['note']}")
    if isinstance(menu, dict) and menu.get("items"):
        lines.append(f"- 价目：{len(menu['items'])} 项（更新于 {prof.get('price_updated_at', '未知')}）")
    else:
        lines.append("- 价目：无")
    orders = load_orders(vendor)
    if isinstance(orders.get("log"), list) and orders["log"]:
        total = sum(int(e.get("total_cents") or 0) for e in orders["log"])
        lines.append(f"- 已点过 {len(orders['log'])} 单，累计 ¥{money(total)}")
    lines.append(f"- 数据位置：{vendor_dir(vendor)}")
    return "\n".join(lines)


def render_vendors():
    rows = list_vendors()
    if not rows:
        return "还没有任何摊位。转发一条新的群消息，就能长出第一家。"
    lines = ["## 我的摊位", "| id | 店 | 城市 | 群 | 价格类型 | 价目 | 已点 |", "|---|---|---|---|---|---:|---:|"]
    for r in rows:
        orders = read_json(vendor_dir(r["id"]) / "orders.json", {})
        n = len(orders.get("log", [])) if isinstance(orders.get("log"), list) else 0
        lines.append(f"| {r['id']} | {r['name']} | {r['city'] or '—'} | {r['group'] or '—'} | {PRICING_LABELS.get(r['pricing'], r['pricing'])} | {r['items']} | {n} |")
    lines.append(f"\n数据目录：{HOME}")
    return "\n".join(lines)


def cmd_search(keyword, city=None):
    key = norm(keyword)
    hits = []
    for r in list_vendors():
        if city and norm(city) not in norm(r.get("city", "")):
            continue
        prof = load_profile(r["id"])
        menu = load_menu(r["id"]) or {}
        menu_items = []
        if isinstance(menu, dict):
            for it in menu.get("items", []):
                names = [it.get("name", ""), *(it.get("aliases") or [])]
                if any(key in norm(n) for n in names if n):
                    menu_items.append(it["name"])
        text_fields = [r.get("name", ""), r.get("group", ""), r.get("sells", ""),
                       r.get("note", ""), r.get("city", ""), r.get("address", "")]
        text_hit = any(key in norm(t) for t in text_fields if t)
        if menu_items or text_hit:
            hits.append({
                "id": r["id"], "name": r.get("name"), "city": r.get("city", ""),
                "address": r.get("address", ""), "group": r.get("group", ""),
                "sells": r.get("sells", ""), "pricing": r.get("pricing"),
                "matched_items": menu_items, "matched_text": text_hit,
            })
    return hits


def render_search(hits):
    if not hits:
        return "没有找到卖这个的摊位。转发它的群消息过来，就能建档。"
    lines = ["## 找到了："]
    for h in hits:
        seg = f"- **{h['name']}**（{h['id']}）"
        if h.get("city"):
            seg += f"，{h['city']}" + (f" {h['address']}" if h.get("address") else "")
        if h["group"]:
            seg += f"，群：{h['group']}"
        if h["sells"]:
            seg += f"，卖：{h['sells']}"
        if h["matched_items"]:
            seg += "，相关菜品：" + "、".join(h["matched_items"])
        lines.append(seg)
    return "\n".join(lines)


# ---------- 核价结果渲染 ----------

def render(out):
    chunks = ["## 核价结果", "| 点单人 | 菜品 | 数量 | 单价(元) | 小计(元) |", "|---|---|---:|---:|---:|"]
    for person in out["people"]:
        for row in person["items"]:
            chunks.append(f"| {person['person']} | {row['item']} | {row['qty']} | {row['unit_price']} | {row['subtotal']} |")
        chunks.append(f"| **{person['person']}小计** | | | | **{person['subtotal']}** |")
    chunks.append(f"\n**已确认合计：¥{out['confirmed_total']}**")
    if out["pending"]:
        chunks.append("\n### 待确认（不计入合计）")
        for x in out["pending"]:
            chunks.append(f"- 第{x['row']}条 {x.get('person', '')}「{x.get('item', '')}」：{x['reason']}")
    for w in out["warnings"]:
        chunks.append("注意：" + w)
    chunks.append("\n### 可复制到群里的点单草稿")
    chunks.append("```text\n" + out["group_message"] + "\n```")
    return "\n".join(chunks)


def render_menu(vendor):
    menu = load_menu(vendor)
    if not isinstance(menu, dict) or not menu.get("items"):
        return "这个摊位还没有价目。"
    prof = load_profile(vendor)
    lines = [f"## {prof.get('name', vendor)} 价目表（{len(menu['items'])} 项）"]
    for row in menu["items"]:
        lines.append(f"- {row['name']}\t¥{money(row['price_cents'])}")
    if menu.get("price_unit_note"):
        lines.append("\n说明：" + menu["price_unit_note"])
    return "\n".join(lines)


# ---------- CLI ----------

def main():
    ap = argparse.ArgumentParser(description="路边摊 Pro：多摊位点单算价与货源记录")
    ap.add_argument("--vendor", help="本次操作的摊位 id")
    ap.add_argument("--vendors", action="store_true", help="列出所有摊位")
    ap.add_argument("--profile", action="store_true", help="看摊位档案")
    ap.add_argument("--menu", action="store_true", help="看当前价目")
    ap.add_argument("--new-vendor", action="store_true", help="建新摊位（--ensure-vendor 为存在时更新档案）")
    ap.add_argument("--ensure-vendor", action="store_true")
    ap.add_argument("--display-name", help="店名")
    ap.add_argument("--group", help="所在微信群名")
    ap.add_argument("--pricing", help=f"价格类型：{'/'.join(PRICING_MODES)}")
    ap.add_argument("--sells", help="卖什么（线索型摊位的品类描述）")
    ap.add_argument("--city", help="所在城市（如：淄博）")
    ap.add_argument("--address", help="具体位置（如：公司北门斜对面）")
    ap.add_argument("--note", help="备注")
    ap.add_argument("--menu-json", help="价目表 JSON（建档/更新价目用）")
    ap.add_argument("--menu-file", help="从 UTF-8 JSON 文件导入价目表，避免手工复制长 JSON")
    ap.add_argument("--confirm-fixed-price-change", action="store_true", help="固定价变更已经用户明确确认")
    ap.add_argument("--allow-remove-items", action="store_true", help="确认覆盖菜单时允许删除原有菜品")
    ap.add_argument("--menu-diff", action="store_true", help="对比 --menu-json 与库里的价目，只报差异不写盘")
    ap.add_argument("--update-menu", action="store_true", help="覆盖价目（必须先经用户确认）")
    ap.add_argument("--search", help="按关键词找摊位/菜品（我想买X，谁家有）")
    ap.add_argument("--home", action="store_true", help="打印数据目录")
    source = ap.add_mutually_exclusive_group()
    source.add_argument("--input", help="UTF-8 JSON 点单文件")
    source.add_argument("--json", help="点单 JSON 参数")
    ap.add_argument("--output", choices=["markdown", "json"], default="markdown")
    ap.add_argument("--save", action="store_true", help="仅保存本次草稿供下次复用；不计入消费")
    ap.add_argument("--confirm-order", action="store_true", help="用户明确已经向商家下单后记账；计入真实消费")
    ap.add_argument("--last", action="store_true", help="看上次点的")
    ap.add_argument("--stats", action="store_true", help="看累计消费与常点")
    ap.add_argument("--base", choices=["last"], help="用上次的单打底，本次只写新增")
    ap.add_argument("--clear-last", action="store_true", help="清掉点单记录")
    args = ap.parse_args()

    try:
        if args.menu_file:
            if args.menu_json:
                die("--menu-file 与 --menu-json 不能同时使用")
            args.menu_json = Path(args.menu_file).read_text(encoding="utf-8")
        if args.home:
            print(HOME)
            return 0
        if args.vendors:
            print(render_vendors())
            return 0
        if args.search:
            hits = cmd_search(args.search, city=args.city)
            print(json.dumps(hits, ensure_ascii=False, indent=2) if args.output == "json" else render_search(hits))
            return 0
        if args.new_vendor or args.ensure_vendor:
            if not args.vendor:
                die("--new-vendor 需要同时给 --vendor <id>")
            cmd_new_vendor(args)
            return 0

        if not args.vendor:
            die("需要 --vendor 指定摊位（或用 --vendors / --search）")
        require_vendor(args.vendor)
        vendor = args.vendor

        if args.profile:
            print(render_profile(vendor))
            return 0
        if args.menu:
            print(render_menu(vendor))
            return 0
        if args.menu_json and args.menu_diff:
            new_menu = validate_menu(json.loads(args.menu_json))
            changes = menu_diff(vendor, new_menu)
            if args.output == "json":
                print(json.dumps(changes, ensure_ascii=False, indent=2))
            elif not changes:
                print("价目没有变化。")
            else:
                print("## 价目差异（未入库，等你确认）")
                for c in changes:
                    if c["change"] == "new":
                        print(f"- 新增 {c['item']}：¥{money(c['new'])}")
                    elif c["change"] == "price":
                        print(f"- **{c['item']}：¥{money(c['old'])} → ¥{money(c['new'])}**")
                    else:
                        print(f"- 库里有、新表没有：{c['item']}（¥{money(c['old'])}）")
            return 0
        if args.update_menu:
            if not args.menu_json:
                die("--update-menu 需要 --menu-json")
            new_menu = validate_menu(json.loads(args.menu_json))
            pricing = load_profile(vendor).get("pricing", "none")
            verify_menu_change(vendor, new_menu, pricing, args.confirm_fixed_price_change,
                               args.allow_remove_items)
            changes = update_menu(vendor, new_menu, source="update-menu")
            print(f"价目已更新（{len(changes)} 处变更已记入 price-log）。")
            return 0

        if args.clear_last:
            try:
                (vendor_dir(vendor) / "orders.json").unlink()
                print("已清掉这个摊位的点单记录。")
            except FileNotFoundError:
                print("本来就没有点单记录。")
            return 0
        if args.last:
            print(render_last(vendor))
            return 0
        if args.stats:
            print(render_stats(vendor))
            return 0

        raw = Path(args.input).read_text(encoding="utf-8") if args.input else args.json
        if raw is None:
            raw = sys.stdin.read()
        payload = json.loads(raw)
        if isinstance(payload, list):
            payload = {"orders": payload}
        menu = load_menu(vendor)
        if not isinstance(menu, dict) or not menu.get("items"):
            die("这个摊位还没有价目，算不了价。先拿到价目（--update-menu），或把它当线索摊位只记货源。")
        if args.base == "last":
            base_rows = last_rows(vendor)
            if not base_rows:
                die("找不到该摊位上一单；没有底单不能按'和上次一样'处理")
            payload = dict(payload)
            payload["orders"] = base_rows + list(payload.get("orders") or [])
        payload["_vendor"] = vendor
        out = calculate(payload, menu)
        print(json.dumps(out, ensure_ascii=False, indent=2) if args.output == "json" else render(out))
        if args.save or args.confirm_order:
            try:
                save_last(vendor, out, confirmed=args.confirm_order)
                action_note = "已确认下单并计入消费" if args.confirm_order else "已保存草稿（不计入消费）"
                note = f"{action_note}：{vendor_dir(vendor) / 'orders.json'}"
            except (ValueError, OSError) as exc:
                note = f"未保存：{exc}（原有订单记录保持不变）"
            print(note, file=sys.stderr if args.output == "json" else sys.stdout)
        return 0
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print("失败：" + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
