"""工单智能分类助手（第三十八批，排期第四批项）：基于历史工单的 TF-IDF 分类建议。

- 语料 = 历史工单（标题+描述 → 问题分类），中文按 2-gram 切分（无需分词依赖）
- 分类向量 = 词频 × 逆文档频率，L2 归一化；预测取输入文本命中词的加权得分
- 输出 Top3 分类建议 + 置信度与优先级初判（关键词规则）
- 定位为「人工复核兜底」的辅助建议：不参与自动分派，不改变工单流转
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from math import log, sqrt

from app.models.ticket import Ticket

# 优先级初判关键词（按命中优先级从高到低；初判仅为建议，提交时仍可手选）
URGENCY_WORDS = {
    "urgent": ("瘫痪", "全员", "大面积", "泄露", "安全事件", "断网", "无法工作", "中毒", "勒索"),
    "high": ("紧急", "故障", "报错", "无法", "异常", "打不开", "崩溃", "卡死", "丢失", "损坏", "连不上"),
    "low": ("咨询", "请教", "申请", "开通", "权限", "安装申请", "查询", "什么时候", "预计", "预约"),
}

_STOP = {"的", "了", "在", "是", "我", "有", "和", "就", "不", "都", "一个", "没有", "我们", "你们", "问题", "工单", "麻烦", "请", "一下", "现在", "需要", "可以"}

_cache: dict = {"built_at": None, "ticket_count": -1, "vectors": None}


def _grams(text: str) -> list[str]:
    """中文 2-gram + 英文/数字词，去停用词。"""
    cleaned = "".join(ch for ch in (text or "").lower() if ch.isprintable())
    grams: list[str] = []
    buf = ""
    for ch in cleaned:
        if ch.isspace():
            if buf:
                grams.append(buf)
                buf = ""
        elif ch.isascii() and (ch.isalnum() or ch in "._-"):
            buf += ch
        else:
            if buf:
                grams.append(buf)
                buf = ""
            grams.append(ch)
    if buf:
        grams.append(buf)
    # 相邻汉字组成 2-gram
    cjk = [g for g in grams if len(g) == 1 and "\u4e00" <= g <= "\u9fff"]
    bigrams = [cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)]
    out = [g for g in grams if len(g) > 1 and g not in _STOP] + [b for b in bigrams if b not in _STOP]
    # 去重保序
    seen: set[str] = set()
    return [g for g in out if not (g in seen or seen.add(g))]


def rebuild_if_stale(db) -> bool:
    """工单数量变化时重建索引（进程内缓存）；语料 <5 条时不构建。返回是否重建。"""
    from sqlalchemy import func

    total = db.query(func.count(Ticket.id)).filter(Ticket.id.isnot(None)).scalar() or 0
    if total < 5:
        return False
    if _cache["vectors"] is not None and _cache["ticket_count"] == total:
        return False
    rows = db.query(Ticket.title, Ticket.description, Ticket.category).filter(
        Ticket.category.is_not(None)
    ).all()
    tf = defaultdict(lambda: defaultdict(float))  # category -> gram -> count
    df = defaultdict(int)  # gram -> 出现的分类数
    for title, desc, cat in rows:
        grams = set(_grams(f"{title or ''} {desc or ''}"))
        if not grams:
            continue
        for g in grams:
            tf[cat][g] += 1
        for g in grams:
            df[g] += 1
    n_cats = max(len(tf), 1)
    vectors: dict[str, dict[str, float]] = {}
    for cat, counter in tf.items():
        vec = {}
        for g, c in counter.items():
            idf = log(n_cats / max(df[g], 1)) + 1.0
            vec[g] = c * idf
        norm = sqrt(sum(v * v for v in vec.values())) or 1.0
        vectors[cat] = {g: v / norm for g, v in vec.items()}
    _cache["vectors"] = vectors
    _cache["ticket_count"] = total
    _cache["built_at"] = datetime.now()
    return True


def suggest(db, title: str, description: str) -> dict:
    """返回分类建议 Top3 与优先级初判；语料不足时 items 为空。"""
    rebuild_if_stale(db)
    vectors = _cache["vectors"]
    if not vectors:
        return {"items": [], "priority": None}
    grams = set(_grams(f"{title or ''} {description or ''}"))
    if not grams:
        return {"items": [], "priority": None}
    scores = {cat: sum(w for g, w in vec.items() if g in grams) for cat, vec in vectors.items()}
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    hits = [(c, s) for c, s in ranked if s > 0][:3]
    total_score = sum(s for _, s in hits) or 1.0
    items = [
        {"category": c, "score": round(s / total_score, 2), "confidence": round(100 * s / total_score)}
        for c, s in hits
    ]
    text = f"{title or ''}{description or ''}"
    priority = None
    for p, words in URGENCY_WORDS.items():
        if any(w in text for w in words):
            priority = p
            break
    return {"items": items, "priority": priority}
