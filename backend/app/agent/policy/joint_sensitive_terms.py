"""Per-joint training terms that should trigger graph_tool when profile lists that injury."""

from app.models.memory import JOINT_LITERAL

# Keys must align with JOINT_LITERAL / Neo4j Joint nodes.
JOINT_SENSITIVE_TERMS: dict[str, frozenset[str]] = {
    "脊柱": frozenset(
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
    ),
    "肩关节": frozenset(
        {
            "肩",
            "卧推",
            "推举",
            "过顶",
            "引体",
            "飞鸟",
            "侧平举",
            "双杠",
            "倒立",
        }
    ),
    "膝关节": frozenset(
        {
            "膝",
            "深蹲",
            "跑",
            "跳",
            "弓步",
            "阶梯",
            "起落",
            "冲刺",
        }
    ),
    "髋关节": frozenset(
        {
            "髋",
            "深蹲",
            "硬拉",
            "弓步",
            "臀",
            "后链",
            "开髋",
        }
    ),
    "踝关节": frozenset(
        {
            "踝",
            "跑",
            "跳",
            "提踵",
            "箱跳",
            "冲刺",
            "跳绳",
        }
    ),
    "腕关节": frozenset(
        {
            "腕",
            "俯卧撑",
            "卧推",
            "弯举",
            "支撑",
            "倒立",
            "双杠",
        }
    ),
    "肘关节": frozenset(
        {
            "肘",
            "弯举",
            "三头",
            "俯卧撑",
            "双杠",
            "窄握",
        }
    ),
}

ALL_JOINTS: tuple[str, ...] = tuple(JOINT_SENSITIVE_TERMS.keys())
