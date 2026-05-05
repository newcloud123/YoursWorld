# 小说世界 D&D

沉浸式小说角色扮演游戏系统。将小说文本转化为可交互的世界，玩家可以穿越进小说世界，夺舍已有角色或创建自定义身份，与 NPC 进行对话式交互。

![界面预览](img/main1.JPG)

## 核心特性

- **章节时间线**：自动切分小说章节，按章节构建角色状态时间线
- **人物关系图谱**：基于 vis.js 的交互式关系图谱，支持按章节过滤
- **认知边界校验**：LLM 驱动的一致性校验，防止玩家引用角色不可能知道的信息
- **多 Agent 对话**：旁白、NPC 各自独立生成对话，形成沉浸式叙事体验
- **双重身份模式**：夺舍已有角色 / 杜撰全新身份
- **角色记忆面板**：实时查看角色的性格、背景、能力、人际关系等状态

## 技术栈

| 层 | 技术 |
|---|------|
| 后端框架 | FastAPI + Uvicorn |
| 知识图谱 | LightRAG (lightrag-hku) |
| LLM | OpenAI 兼容 API (MiMo) |
| Embedding | SiliconFlow BGE-M3 (1024 dim) |
| 前端 | 原生 JS + vis.js + CSS |
| 数据模型 | Pydantic v2 |

## 快速开始

### 1. 安装依赖

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置 API Key

编辑 `backend/config.py`，设置 LLM 和 Embedding API：

```python
LLM_API_KEY = "your-key"
LLM_BASE_URL = "https://your-llm-endpoint/v1"
LLM_MODEL = "your-model"

EMBEDDING_API_KEY = "your-key"
EMBEDDING_BASE_URL = "https://your-embedding-endpoint/v1"
EMBEDDING_MODEL = "BAAI/bge-m3"
```

或通过环境变量：

```bash
export LLM_API_KEY="your-key"
export LLM_BASE_URL="https://your-endpoint/v1"
```

### 3. 启动服务

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

访问 `http://localhost:8000`。

### 4. 上传小说

点击「上传小说」按钮，选择 `.txt` 文件。系统将自动：

1. 按章节格式切分文本
2. 提取人物列表和关系
3. 构建章节级角色状态时间线
4. 提取关键场景

## 使用流程

```
上传小说 → 选择章节 → 选择身份（夺舍/杜撰）→ 选择场景 → 进入世界
```

### 夺舍模式

选择一个已有角色，以穿越者身份使用该角色的身体和记忆。NPC 会根据原著关系与你互动。

### 杜撰模式

创建全新角色，以外来者身份进入小说世界。原著角色不认识你，会根据各自性格决定如何对待你。

### 对话交互

输入你的行动，系统会返回：
- **旁白**：环境描述和事件叙述
- **NPC 对话**：每个在场 NPC 根据性格和关系做出回应
- **GM 提示**：当行为超出认知边界时给出提示

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/novels` | 列出所有已上传小说 |
| POST | `/novel/upload` | 上传小说并提取数据 |
| GET | `/novel/{id}/chapters` | 获取章节列表 |
| GET | `/novel/{id}/characters` | 获取角色列表（支持 `?chapter_id=`） |
| GET | `/novel/{id}/graph` | 获取关系图谱数据 |
| GET | `/novel/{id}/scenes` | 获取场景列表 |
| POST | `/game/start` | 开始游戏会话 |
| POST | `/game/{id}/chat` | 发送游戏消息 |
| GET | `/game/{id}/state` | 获取会话状态 |
| DELETE | `/game/{id}` | 结束游戏会话 |

## 项目结构

```
backend/
  config.py           # API 配置和 Prompt 模板
  models.py           # Pydantic 数据模型
  main.py             # FastAPI 路由
  chat.py             # 游戏会话管理
  world_engine.py     # 世界状态机 + 认知校验 + 多 Agent 对话
  extraction.py       # 小说提取管线（LightRAG + 时间线）
  chapter_manager.py  # 章节切分和管理
frontend/
  index.html          # 页面结构
  css/style.css       # 暗色主题样式
  js/
    app.js            # 主流程编排
    timeline.js       # 章节时间线
    identity.js       # 身份选择面板
    scene.js          # 场景选择
    chat.js           # 游戏对话渲染
    graph.js          # vis.js 关系图谱
    character.js      # 角色列表面板
data/
  novels/             # 按小说组织的数据
    {novel_id}/
      raw.txt         # 原始文本
      chapters.json   # 章节列表
      characters.json # 角色数据
      scenes.json     # 场景数据
      timeline.json   # 角色状态时间线
      rag_storage/    # LightRAG 存储
  sessions/           # 游戏会话持久化
```

## 许可

MIT
