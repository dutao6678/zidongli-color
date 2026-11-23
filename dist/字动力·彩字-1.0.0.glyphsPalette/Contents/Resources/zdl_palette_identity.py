"""Names are associated with persistent identities; color is only a verification input."""
from copy import deepcopy
from hashlib import sha256
import json
from uuid import uuid4

KEY = "com.zidongli.color.paletteIdentity.v2"


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return sha256(encode(value).encode()).hexdigest()


def shape(rows):
    if rows and (not rows[0] or any(len(row) != len(rows[0]) for row in rows)):
        raise ValueError("原生色板槽位数不一致。")
    return len(rows), len(rows[0]) if rows else 0


def read(raw):
    data = json.loads(raw)
    if (not isinstance(data, dict) or data.get("version") != 2
            or type(data.get("revision")) is not int or data["revision"] < 0
            or not isinstance(data.get("slots"), list)
            or not isinstance(data.get("palettes"), list)
            or not isinstance(data.get("archived"), list)):
        raise ValueError("色板身份数据格式异常。")
    slots = data["slots"]
    palettes = data["palettes"]
    if (any(not isinstance(slot, str) or not slot for slot in slots) or len(set(slots)) != len(slots)
            or any(not isinstance(p, dict) or not isinstance(p.get("id"), str) or not p["id"]
                   or not isinstance(p.get("name"), str) or not isinstance(p.get("names"), dict)
                   or any(key not in slots or not isinstance(name, str) for key, name in p["names"].items())
                   for p in palettes)
            or len({p["id"] for p in palettes}) != len(palettes)
            or not isinstance(data.get("colors"), str) or not isinstance(data.get("legacy"), str)):
        raise ValueError("色板身份数据无效或存在重复 ID。")
    return data


def status(state, rows, legacy):
    if shape(rows) != (len(state["palettes"]), len(state["slots"])):
        return "套系或槽位结构已变化，名称待核对。"
    if state["legacy"] != digest(legacy):
        return "旧版名称记录已变化，名称待核对。"
    if state["colors"] != digest(rows):
        return "原生色板已变化，名称待核对。确认原位置改色后可按编号保留名称。"
    return ""


def labels(state):
    return tuple((p["name"], tuple(p["names"].get(slot, "") for slot in state["slots"]))
                 for p in state["palettes"])


def create(rows, legacy, verified):
    count, width = shape(rows)
    slots = [uuid4().hex for _ in range(width)]
    palettes = [dict(id=uuid4().hex, name=name, names=dict(
        (slot, label) for slot, label in zip(slots, names) if label))
        for name, names in verified]
    if len(palettes) != count:
        raise ValueError("旧版名称与套系数量不一致。")
    # Keep the legacy source unchanged even for rows that failed verification.
    return dict(version=2, revision=0, slots=slots, palettes=palettes, archived=[],
                colors=digest(rows), legacy=digest(legacy))


def evolve(state, rows, legacy, palette_order, slot_order, names=None):
    """Explicit maps are new index -> existing index, or None for new identity."""
    count, width = shape(rows)
    if len(palette_order) != count or len(slot_order) != width:
        raise ValueError("套系或槽位映射长度不符。")
    for order, old in ((palette_order, state["palettes"]), (slot_order, state["slots"])):
        previous = [index for index in order if index is not None]
        if len(previous) != len(set(previous)) or any(not 0 <= i < len(old) for i in previous):
            raise ValueError("存在重复或无效的身份映射。")
    next_state = deepcopy(state)
    slots = [state["slots"][i] if i is not None else uuid4().hex for i in slot_order]
    palettes = []
    for i, previous in enumerate(palette_order):
        prior = state["palettes"][previous] if previous is not None else None
        palette_id = prior["id"] if prior else uuid4().hex
        if names is not None and names[i] is not None:
            name, cells = names[i]
            slot_names = {slot: label for slot, label in zip(slots, cells) if label}
        else:
            name = prior["name"] if prior else ""
            slot_names = {slot: prior["names"][slot] for slot in slots if prior and slot in prior["names"]}
        palettes.append(dict(id=palette_id, name=name, names=slot_names))
    removed_palettes = [p for i, p in enumerate(state["palettes"]) if i not in palette_order]
    removed_slots = [slot for slot in state["slots"] if slot not in slots]
    if removed_palettes or removed_slots:
        next_state["archived"].append(dict(revision=state["revision"], slots=removed_slots,
            removed_palettes=deepcopy(removed_palettes),
            removed_names=[dict(palette=p["id"], names={s:p["names"][s] for s in removed_slots if s in p["names"]})
                           for p in state["palettes"]]))
    next_state.update(revision=state["revision"]+1, slots=slots, palettes=palettes,
                      colors=digest(rows), legacy=digest(legacy))
    return next_state
