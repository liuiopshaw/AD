# 导入 logging 模块，用于记录代理运行时的日志信息
import logging
# 导入 BaseAgent 基类，CreativeDesigningAgent 继承自它，复用通用代理创建逻辑
from src.agents.base_agent import BaseAgent
# 导入 ToolFactory 工具工厂类，用于创建材料设计所需的工具集
from src.tools import ToolFactory

# 配置 logging 模块的全局日志级别为 WARNING，
# 确保只有警告和错误级别日志输出，避免 INFO/DEBUG 刷屏
logging.basicConfig(level=logging.WARNING)
# 获取当前模块的 logger 实例，日志输出时带上模块名，便于问题定位
logger = logging.getLogger(__name__)

# 材料设计专家代理类
# 负责根据用户需求创建和优化水处理材料的解决方案
class CreativeDesigningAgent(BaseAgent):
    """创意设计代理（Creative Designing Agent）
       专门负责水处理材料的设计任务：
       - 根据用户需求生成材料设计方案
       - 从 Materials Project 等数据库查询材料信息
       - 输出结构化的设计结果（化学式、晶体结构、物理性质等）"""

    def __init__(self, llm):
        """初始化创意设计代理

        Args:
            llm: 语言模型实例，由外部传入（通常来自 Crew 配置或主程序）
        """
        # 延迟导入 Config 类，避免模块加载时的循环导入问题
        from src.config.config import Config
        # 调用父类 BaseAgent 的构造函数，传入设计代理专有的配置参数
        super().__init__(
            llm=llm,
            role="Creative_Designing_agent",  # 代理角色名：材料设计专家
            goal="Design and optimize water treatment material solutions, strictly following material type classification and structural description specifications",
            # 指定设计代理专用的提示词模板文件
            prompt_file="creative_designing_agent_prompt.md",
            # 从 Config 读取材料设计专用的温度参数，
            # 较高的温度可以增加设计方案的多样性/创造性
            temperature=Config.MATERIAL_DESIGNER_TEMPERATURE,
            # max_iter=1：性能优化，限制为仅 1 次迭代
            # 原值为 8，减少迭代次数可显著降低 API 调用成本并加快响应速度
            max_iter=1
        )

    def create_agent(self):
        """创建并返回配置好的创意设计 Agent 实例

        此方法覆盖父类的 create_agent，添加了：
        1. EAS（Elastic Algorithm Service）LLM 的创建尝试
        2. 材料设计专用工具的附加
        3. backstory 的增强（添加数据库查询和工具使用指导）

        Returns:
            Agent: 配置完成的材料设计 Agent 实例
        """
        # LLM 的选择（EAS / 带温度标准 LLM / 默认 LLM）已统一收敛到
        # BaseAgent._resolve_llm()，此处不再重复创建

        # 调用父类的 create_agent() 方法创建基础 Agent 实例
        agent = super().create_agent()
        # 附加工具：根据环境判断是否启用工具调用
        # 在 DashScope 兼容端点上，工具调用可能返回 500 错误，因此需要条件判断
        try:
            from src.utils.llm_config import tools_enabled
            if tools_enabled():
                # 工具启用时：创建材料设计专用工具集
                # 包括 Materials Project 查询、结构验证等工具
                agent.tools = ToolFactory.create_material_design_tools()
            else:
                # 工具禁用时：设置为空列表，代理将完全依赖 LLM 知识
                agent.tools = []
        except Exception:
            # 异常时默认启用工具（保守策略）
            agent.tools = ToolFactory.create_material_design_tools()

        # 增强 backstory：在原有提示词后追加额外的设计输出要求和工具使用策略
        agent.backstory += (
            "\n\nWhen outputting design results, include the following detailed information whenever possible:\n"
            "- Materials Project ID (mp-xxx) (if the material exists in the database)\n"
            "- Chemical formula and crystal structure description\n"
            "- Key physical properties (e.g., band gap, density)\n"
            "- Thermodynamic stability (height above convex hull)\n"
            "\nTool Usage Strategy (Rate Limiting & Reuse):\n"
            "- Prioritize reusing already-obtained structure validation or material identifier results; avoid duplicate database searches\n"
            "- Only call Materials Project search when essential information is missing, using minimal field sets\n"
            "- Limit result count for element combination queries to avoid large-scale data retrieval\n"
        )

        return agent
