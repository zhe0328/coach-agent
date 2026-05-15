from .utils.logger import logger, LogColor

class WorkflowRouter:
    """
    状态路由拦截：实现无延迟的拓扑环跳转判断
    """
    def __init__(self):
        pass

    def should_stop(self, is_complete: bool, current_step: int, max_loops: int) -> str:
        # 数据通过大模型或规则质检，可以进行合成响应
        prefix = f"{LogColor.ROUTER}[Router] 🧭"
        suffix = f"{LogColor.RESET}"
        if is_complete:
            logger.info(f"{prefix} 质检达标，审批通过！耗时 {current_step + 1} 轮迭代。流向 -> Synthesizer{suffix}")
            return "synthesize"

        # 达到反思上限，为规避延迟过大和 Token 成本失控强制截断
        if current_step >= max_loops - 1:
            logger.warning(f"{prefix} 达到最大尝试轮数阈值（{max_loops}次），触发强行阻断拦截，确保低延迟！流向 -> Synthesizer{suffix}")
            return "synthesize"

        # 触发回滚重试
        logger.info(f"{prefix} 发现数据缺口，拦截向下透传！批准启动下一轮 ReAct 纠错迭代。{suffix}")
        return "retry"
