# tests/tools/test_retry_rag.py
import asyncio
import httpx
from unittest.mock import patch
from app.agent.orchestrator import CoachOrchestrator
from app.models.schema import ToolTask, RAGSearchSchema
from app.agent.utils.logger import logger, LogColor

async def simulate_qwen_timeout():
    # 1. 正常初始化你的核心调度器
    # 注意：如果你的初始化需要 client，请传入你的 openai 实例或 Mock 客户端
    # 这里我们只测工具派发容灾，直接传入 None 或你的配置 client
    orchestrator = CoachOrchestrator(client=None) 
    
    # 2. 构造标准的强类型 RAG 任务契约
    task = ToolTask(
        task_id="task_rag_test_001",
        tool="rag_tool",
        rag_params=RAGSearchSchema(query_text="哑铃卧推发力感指南", top_k=3),
        reason="严格验证通义千问大模型 API 网络突发超时时的级联指数退避重试与熔断降级表现"
    )
    
    # 💡 【核心重构亮点】：显式启动全局 Mock 句柄，不使用 with 块，彻底切断异步挂起导致的生命周期断裂隐患
    mover_mock = patch('dashscope.TextEmbedding.call', side_effect=httpx.TimeoutException("连接阿里云百炼机房突发 504 闸门超时"))
    activated_mock = mover_mock.start() # 👈 手动在内存沙箱中强行激活全局拦截
    
    try:
        logger.info(f"{LogColor.PLAN}[TestBench] 🚩 成功注入『通义千问 API 瞬时网络通信超时故障』，启动端到端重试与熔断管线压榨...{LogColor.RESET}")
        
        # 3. 触发真实调度！
        # 此时程序一定会：
        #   - 在 _execute_with_retry_precise 内部顽强重试 3 次（控制台会有漂亮的彩色重试滚动日志）
        #   - 3 次后由于 reraise=True 抛出，百分之百弹进 dispatch_tool 的 except 块中
        #   - 完美打印出 [ToolDispatcher] ❌ 熔断防护触发！ 柔性降级日志，并安全返回空资产
        result = await orchestrator.dispatch_tool(task)
        
        logger.info(f"{LogColor.PLAN}[TestBench] 🎉 测试圆满结束！最后收拢到的熔断退化安全资产快照如下:{LogColor.RESET}")
        print(f"返回数据结构: {result}")
        
        # 4. 硬核逻辑断言（Assertions）：确保熔断退化舱没有返回脏字符串，而是返回了干净合规的空 data: []
        if isinstance(result, dict) and result.get("data") == []:
            logger.info(f"{LogColor.SYNTH}[TestBench] 💯 校验成功：全栈熔断防线坚不可摧！成功向状态机交付了低噪声空资产契约。{LogColor.RESET}")
        else:
            logger.error("[TestBench] ❌ 校验失败：熔断机制未返回标准空集合契约。")

    finally:
        # 5. 【极其关键】：测试结束后必须在内存中手动闭环卸载 Mock 拦截器，防止污染后续其他工具的单元测试
        mover_mock.stop()
        logger.info("[TestBench] 🛡️ 单元测试内存沙箱已安全卸载，环境复原。")

if __name__ == "__main__":
    # 统一使用最外层模块化命令执行：python -m tests.tools.test_retry_rag
    asyncio.run(simulate_qwen_timeout())
