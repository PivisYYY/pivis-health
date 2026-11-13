"""动作库：本机的 exercises-dataset（hasaneyldrm/exercises-dataset，1324 个动作）。

查一个动作练哪块肌肉、要什么器械、中文步骤，以及对膝盖（半月板）要留意什么。
P-Health 排动作、核对跟练视频时先查这里，肌群名称以它为准。

授权：动作文字和数据结构是 MIT（© Hasan Emir Yıldırım）；缩略图和 GIF 版权属于 Gym visual
（© Gym visual — https://gymvisual.com/），只在本机服务里给老大自己看，不进仓库、不进 App 包。
数据放在 ~/Tools/exercises-dataset（不进 git），config 的 exercise_db_dir 可以改。
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

DEFAULT_DIR = Path.home() / "Tools" / "exercises-dataset"
ATTRIBUTION = "© Gym visual — https://gymvisual.com/"

# 肌群、部位、器械：英文 → 中文（输出用）
MUSCLE_ZH = {
    "abs": "腹肌", "abdominals": "腹肌", "lower abs": "下腹", "core": "核心", "obliques": "腹斜肌",
    "pectorals": "胸大肌", "chest": "胸", "upper chest": "上胸",
    "biceps": "肱二头肌", "triceps": "肱三头肌", "brachialis": "肱肌", "forearms": "前臂",
    "wrists": "手腕", "wrist flexors": "屈腕肌", "wrist extensors": "伸腕肌", "grip muscles": "握力", "hands": "手",
    "delts": "三角肌", "deltoids": "三角肌", "rear deltoids": "三角肌后束", "shoulders": "肩",
    "rotator cuff": "肩袖", "serratus anterior": "前锯肌", "levator scapulae": "肩胛提肌",
    "traps": "斜方肌", "trapezius": "斜方肌", "rhomboids": "菱形肌", "upper back": "上背",
    "lats": "背阔肌", "latissimus dorsi": "背阔肌", "back": "背", "lower back": "下背", "spine": "脊柱（竖脊肌）",
    "glutes": "臀肌", "abductors": "髋外展肌（臀中肌）", "adductors": "内收肌", "inner thighs": "大腿内侧",
    "groin": "腹股沟", "hip flexors": "髋屈肌",
    "quads": "股四头肌", "quadriceps": "股四头肌", "hamstrings": "腘绳肌",
    "calves": "小腿", "soleus": "比目鱼肌", "shins": "胫骨前肌", "ankles": "踝", "ankle stabilizers": "踝稳定肌",
    "feet": "足", "cardiovascular system": "心肺", "sternocleidomastoid": "胸锁乳突肌",
}
PART_ZH = {
    "waist": "腰腹", "chest": "胸", "back": "背", "shoulders": "肩", "upper arms": "上臂", "lower arms": "前臂",
    "upper legs": "大腿", "lower legs": "小腿", "cardio": "有氧", "neck": "颈",
}
EQUIP_ZH = {
    "body weight": "徒手", "dumbbell": "哑铃", "cable": "绳索器械", "barbell": "杠铃", "leverage machine": "固定器械",
    "band": "弹力带", "resistance band": "弹力带", "smith machine": "史密斯机", "kettlebell": "壶铃",
    "weighted": "负重", "stability ball": "瑞士球", "ez barbell": "曲杆", "assisted": "辅助", "sled machine": "雪橇机",
    "medicine ball": "药球", "rope": "绳", "roller": "泡沫轴", "bosu ball": "波速球", "olympic barbell": "奥杆",
    "wheel roller": "健腹轮", "trap bar": "六角杠",
}

# 中文搜索词 → 英文（匹配动作名、肌群、部位、器械）
ALIASES: dict[str, tuple[str, ...]] = {
    # 肌群
    "臀中肌": ("abductors", "abduction", "hip abduction", "monster walk"), "髋外展": ("abduction", "abductors"),
    "臀大肌": ("glutes",), "臀": ("glutes", "glute"), "股四头": ("quads", "quadriceps"), "大腿前侧": ("quads", "quadriceps"),
    "腘绳": ("hamstrings", "hamstring"), "大腿后侧": ("hamstrings", "hamstring"), "内收": ("adductors", "adductor"),
    "小腿": ("calves", "calf", "soleus"), "比目鱼": ("soleus",), "核心": ("abs", "core", "plank"), "腹": ("abs", "obliques"),
    "腹斜": ("obliques",), "下背": ("lower back", "spine"), "腰背": ("lower back", "spine"), "竖脊": ("spine", "lower back"),
    "背阔": ("lats",), "上背": ("upper back", "rhomboids"), "菱形": ("rhomboids",), "斜方": ("traps", "trapezius"),
    "肩袖": ("rotator cuff", "external rotation", "internal rotation"), "三角肌": ("delts", "deltoids"), "肩": ("delts", "shoulders", "shoulder"),
    "前锯": ("serratus anterior",), "胸": ("pectorals", "chest"), "二头": ("biceps",), "三头": ("triceps",),
    "前臂": ("forearms", "wrist"), "髋屈": ("hip flexors",), "踝": ("ankles", "ankle"), "颈": ("neck", "levator scapulae"),
    # 动作
    "拉伸": ("stretch",), "深蹲": ("squat",), "蹲": ("squat",), "弓步": ("lunge",), "箭步": ("lunge",), "分腿蹲": ("split squat",),
    "臀桥": ("glute bridge", "bridge"), "桥": ("bridge",), "硬拉": ("deadlift",), "单腿硬拉": ("single leg deadlift",), "上台阶": ("step-up", "step up"),
    "提踵": ("calf raise",), "平板支撑": ("plank",), "侧桥": ("side bridge", "side plank"), "卷腹": ("crunch",),
    "俯卧撑": ("push-up", "push up"), "引体": ("pull-up", "chin-up"), "划船": ("row",), "推举": ("press",), "卧推": ("bench press",),
    "飞鸟": ("fly",), "弯举": ("curl",), "臂屈伸": ("dip", "extension"), "侧平举": ("lateral raise",), "腿屈伸": ("leg extension",),
    "腿弯举": ("leg curl", "hamstring curl"), "外展": ("abduction",), "怪兽走": ("monster walk",), "平衡": ("balance",),
    "单腿": ("single leg", "one leg"), "跳": ("jump",), "转体": ("twist", "rotation"), "泡沫轴": ("roller",),
    "外旋": ("external rotation",), "内旋": ("internal rotation",), "髋": ("hip",),
    # 器械
    "徒手": ("body weight",), "自重": ("body weight",), "弹力带": ("band", "resistance band"), "哑铃": ("dumbbell",),
    "杠铃": ("barbell",), "壶铃": ("kettlebell",), "瑞士球": ("stability ball",), "器械": ("leverage machine", "cable"),
}

# 膝盖（半月板）要留意的动作：关键词规则，只是提醒，还要看视频里的实际幅度
KNEE_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(jump|hop|plyo|burpee|skater|bound|tuck)\w*", re.I), "跳跃落地：半月板先避开"),
    (re.compile(r"\b(pistol|sissy|full squat|deep squat|ass to grass|hack squat)\b", re.I), "深屈膝负重：半月板先避开"),
    (re.compile(r"\bsquat\b", re.I), "下蹲：只做到无痛幅度，先别蹲到底"),
    (re.compile(r"\blunge\b|split squat", re.I), "弓步/分腿蹲：控制深度和膝不内扣，疼就退一级"),
    (re.compile(r"\b(twist|rotation|pivot|wood ?chop|shuffle|lateral)\b", re.I), "站立转体/侧向移动：留意脚踩地时膝盖扭转"),
    (re.compile(r"\bkneeling\b", re.I), "跪姿：膝盖直接受压，垫软垫，疼就换姿势"),
    (re.compile(r"\b(sled|leg press)\b", re.I), "大重量腿部推蹬：控制屈膝角度"),
]


def db_dir(cfg: Any = None) -> Path:
    raw = getattr(cfg, "exercise_db_dir", None) if cfg is not None else None
    return Path(raw).expanduser() if raw else DEFAULT_DIR


@lru_cache(maxsize=4)
def _load(path: str) -> tuple[dict, ...]:
    f = Path(path) / "data" / "exercises.json"
    if not f.is_file():
        return ()
    return tuple(json.loads(f.read_text(encoding="utf-8")))


def available(cfg: Any = None) -> bool:
    return bool(_load(str(db_dir(cfg))))


def _zh(m: str) -> str:
    return MUSCLE_ZH.get(m, m)


def knee_flags(ex: dict) -> list[str]:
    if ex.get("body_part") not in ("upper legs", "lower legs", "cardio", "waist") and \
            not re.search(r"squat|lunge|jump|step|leg", ex.get("name", ""), re.I):
        return []
    out: list[str] = []
    for pat, msg in KNEE_RULES:
        if pat.search(ex.get("name", "")) and msg not in out:
            if msg.startswith("下蹲") and any(o.startswith("深屈膝") for o in out):
                continue
            out.append(msg)
    return out


def summarize(ex: dict, full: bool = False) -> dict:
    d: dict[str, Any] = {
        "id": ex["id"],
        "name": ex["name"],
        "部位": PART_ZH.get(ex.get("body_part", ""), ex.get("body_part")),
        "主练": _zh(ex.get("target", "")),
        "辅助": [_zh(m) for m in ex.get("secondary_muscles") or []],
        "器械": EQUIP_ZH.get(ex.get("equipment", ""), ex.get("equipment")),
        "膝盖留意": knee_flags(ex),
        "图": f"/media/exercise/{Path(ex['image']).name}" if ex.get("image") else None,
        "动图": f"/media/exercise/{Path(ex['gif_url']).name}" if ex.get("gif_url") else None,
    }
    steps = (ex.get("instruction_steps") or {}).get("zh") or []
    d["步骤"] = steps if full else steps[:3]
    return d


def _terms(q: str) -> list[str]:
    """把中英文查询拆成英文词组：中文按别名表换成英文，没对上的中文留着去中文步骤里找。"""
    q = q.strip().lower()
    out: list[str] = []
    rest = q
    for zh in sorted(ALIASES, key=len, reverse=True):
        if zh in rest:
            out.extend(ALIASES[zh])
            rest = rest.replace(zh, " ")
    out.extend(w for w in re.split(r"[\s,，、/]+", rest) if w)
    return out


def _score(ex: dict, terms: list[str]) -> int:
    name = ex.get("name", "").lower()
    muscles = " ".join([ex.get("target", ""), ex.get("muscle_group", "")] + list(ex.get("secondary_muscles") or [])).lower()
    other = " ".join([ex.get("body_part", ""), ex.get("equipment", "")]).lower()
    zh = " ".join((ex.get("instruction_steps") or {}).get("zh") or [])
    s = 0
    for t in terms:
        if re.search(rf"(^|\W){re.escape(t)}", name):
            s += 7 if " " in t else 5
        elif t in muscles:
            s += 3 if t == ex.get("target", "").lower() else 2
        elif t in other:
            s += 1
        elif re.search(r"[一-鿿]", t) and t in zh:
            s += 1
    return s


def search(cfg: Any, query: str = "", muscle: str = "", equipment: str = "", limit: int = 8,
           no_knee_flags: bool = False) -> dict:
    data = _load(str(db_dir(cfg)))
    if not data:
        return {"error": "动作库没装：数据应在 " + str(db_dir(cfg)), "items": []}
    terms = _terms(query) if query else []
    mterms = _terms(muscle) if muscle else []
    eterms = _terms(equipment) if equipment else []
    hits = []
    for ex in data:
        if mterms:
            mus = " ".join([ex.get("target", ""), ex.get("muscle_group", "")] + list(ex.get("secondary_muscles") or []) + [ex.get("name", "")]).lower()
            if not any(t in mus for t in mterms):
                continue
        if eterms and not any(t in ex.get("equipment", "").lower() for t in eterms):
            continue
        if no_knee_flags and knee_flags(ex):
            continue
        s = _score(ex, terms) if terms else 1
        if s > 0:
            # 主练正好是要找的肌群，排前面
            if mterms and any(t == ex.get("target", "").lower() for t in mterms):
                s += 2
            hits.append((s, ex))
    hits.sort(key=lambda h: (-h[0], len(h[1]["name"])))
    return {"total": len(hits), "items": [summarize(ex) for _, ex in hits[:max(1, limit)]],
            "attribution": ATTRIBUTION,
            "note": "肌群以这里为准；膝盖留意是按动作名的关键词规则，还要看视频里的实际幅度"}


def get(cfg: Any, ex_id: str) -> dict | None:
    for ex in _load(str(db_dir(cfg))):
        if ex["id"] == ex_id:
            return summarize(ex, full=True)
    return None


def media_path(cfg: Any, url_path: str) -> Path | None:
    """/media/exercise/<文件名> → 本机文件；只认动作库里的 jpg / gif，防路径穿越。"""
    name = url_path.rsplit("/", 1)[-1]
    if not re.fullmatch(r"\d{4}-[A-Za-z0-9]+\.(jpg|gif)", name):
        return None
    sub = "images" if name.endswith(".jpg") else "videos"
    f = db_dir(cfg) / sub / name
    return f if f.is_file() else None
