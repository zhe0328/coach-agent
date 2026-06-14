"""Shared keyword sets for deterministic intent/routing heuristics."""

SAFETY_KEYWORDS = frozenset(
    {"痛", "伤", "保护", "难", "易", "换一个", "软绵绵", "受伤", "不适", "弹响"}
)

# Phrase-level safety signals (preferred over bare single-char 难/易).
SAFETY_PHRASES = frozenset(
    {
        "太难",
        "太易",
        "换一个",
        "软绵绵",
        "受伤",
        "不适",
        "弹响",
        "保护",
        "保护关节",
        "保护膝盖",
        "保护腰",
    }
)

ACTION_KEYWORDS = frozenset({"练", "推荐", "动作", "计划", "怎么练", "课表", "训练"})

FITNESS_ENTITY_KEYWORDS = frozenset(
    {
        "胸",
        "背",
        "肩",
        "腿",
        "臀",
        "腹",
        "核心",
        "哑铃",
        "杠铃",
        "弹力带",
        "深蹲",
        "卧推",
        "划船",
        "俯卧撑",
        "波比",
        "有氧",
        "力量",
        "肌肉",
        "关节",
        "器械",
        "自重",
    }
)

SPINE_TRAINING_KEYWORDS = frozenset(
    {
        "腿",
        "大腿",
        "背",
        "背部",
        "腰",
        "臀",
        "深蹲",
        "硬拉",
        "腘绳",
        "下肢",
        "后链",
    }
)

EXERCISE_RAG_KEYWORDS = frozenset(
    {"怎么做", "步骤", "发力", "姿势", "呼吸", "要领", "动作要领", "执行"}
)

KNOWLEDGE_RAG_KEYWORDS = frozenset(
    {
        "为什么",
        "顺序",
        "原理",
        "机制",
        "疲劳",
        "排课",
        "饮食",
        "营养",
        "能不能",
        "行不行",
        "还是",
        "组合",
        "干扰",
    }
)

GREETING_PREFIXES = frozenset(
    {"你好", "您好", "hi", "hello", "早上好", "晚上好", "在吗", "谢谢", "感谢"}
)
