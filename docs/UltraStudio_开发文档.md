# Ultra Studio 开发文档

本地 AI 3D 创作工作台 / Agent + ComfyUI + Tauri

## 版本信息

| 项目 | 说明 |
| --- | --- |
| 当前版本 | `0.5.6` |
| 迭代日期 | `2026-05-28` |
| 产品定位 | 面向 AI + 技能创作场景的本地 3D 资产创作与展示工作台 |
| 核心链路 | 需求输入 -> Agent 工具编排 -> 图像生成/编辑 -> 视频生成 -> 三视图 -> 3D 重建 -> 预览与导出 |

## 1. 项目概述

Ultra Studio 是一个本地桌面 Agent 工作台，将自然语言对话、图像生成与编辑、Wan 视频生成、3D 资产生成、模型预览、文档工具、历史记录和 ComfyUI 状态管理整合在同一应用中。项目的重点不是单次模型调用，而是让用户以自然语言描述目标，由 Agent 在真实工具和产物之间持续推进任务，最终得到可预览、可导出、可展示的资产。

## 2. 系统架构

| 层级 | 主要模块 | 职责 |
| --- | --- | --- |
| React 前端 | `ChatPanel`、`ImageStudio`、`ThreeDStudio` | 对话输入、生成状态、结果卡片和 3D 预览 |
| Tauri 桌面层 | `src-tauri/` | 桌面窗口、Sidecar 启动、日志与本地集成 |
| Python Sidecar | `sidecar/routes/chat.py`、`sidecar/memory/` | LLM 路由、工具定义、连续调用与上下文回传 |
| 生成后端 | `sidecar/tools/comfy_client.py`、ComfyUI | Flux 图像生成/修改、Wan 视频生成、三视图生成、Hunyuan3D 建模 |
| 本地数据 | SQLite、输出目录 | 会话、历史任务、素材路径和生成结果 |

## 3. 核心能力

- Agent 对话：理解请求，选择对话、图片、3D、文件或文档工具。
- 图像工作区：生成概念图，通过 Flux 修改颜色、材质与视觉风格，并通过 Wan 2.2 TI2V 生成文生/图生视频。
- 3D 工作区：支持文生 3D、图生 3D、双图融合和多视角重建。
- 预览与导出：以 Three.js 展示 GLB 结果，支持实体与线框查看。
- 本地诊断：检查 Sidecar、SQLite、ComfyUI、输出目录及模型配置。
- 生成历史：保存任务产物和路径，以便恢复、复用与展示。

## 3.1 v0.5.1 视频生成补充

v0.5.1 在图像工作区完善 Wan 2.2 TI2V 5B 视频生成档位。视频生成只在工作区手动触发，不注册为 Agent 对话工具，避免慢任务进入普通对话工具链。

视频参数与策略：

- 支持文生视频和图生视频，源图像为可选输入。
- 时长限制为 1-5 秒，5 秒对应 121 帧。
- 支持 480p、576p、720p 分辨率。
- 标准模式提供 WanFast 单 LoRA 加速开关，界面默认开启并采用 8 步配置；用户可关闭后切回 fp16 无 LoRA 的 20 步质量路径。
- 实验加速模式使用 fp16 + FastWanFullAttn + Turbo 双 LoRA，沿用验证过的 `4 steps / cfg 1 / sa_solver / beta` 配置，界面明确提示稳定性与质量取舍。
- 速度模式使用 Turbo GGUF + Turbo LoRA，使用 5 步配置。

## 3.2 v0.5.2 图像 LoRA 补充

v0.5.2 在图像生成与图片编辑面板的质量选择与提示词之间加入可选的图像 LoRA 加载控件。快速模式对应 Flux 4B，高质量模式对应 Flux 9B，两类 LoRA 严格隔离，切换质量会停用之前选择的模型。

- 4B LoRA 放入 `lora/4b/`，9B LoRA 放入 `lora/9b/`。
- 直接放入 `lora/` 根目录的文件，仅在文件名包含 `4B` 或 `9B` 时归类。
- 用户启用 LoRA 后，Sidecar 动态将 `LoraLoaderModelOnly` 节点插入 Flux 生图或编辑工作流的 UNet 与采样模型链之间。
- 生成前后端均校验当前质量与 LoRA 家族，避免 4B 与 9B 模型混用。
- 选中模型会以 `ultra_studio_4b_` / `ultra_studio_9b_` 前缀硬链接到 ComfyUI `models/loras/` 根目录，确保模型列表刷新并避免复制大型权重文件。

## 3.3 v0.5.3 稳定性修复补充

v0.5.3 不改变图像、视频或 3D 工作流能力，重点修复启动和桌面桥接边界中的可复现问题。

- 修复 `python -m sidecar` 因导入已不存在初始化函数而无法启动的问题。
- 修复 Windows 便携版 ComfyUI 配置路径包含空格时，启动参数被按空格错误拆分导致启动失败的问题。
- 修复 Tauri 生成接口在返回包含中文的长非法响应时，以 UTF-8 字节位置截断正文可能造成应用 panic 的问题。
- Sidecar 初始化现在只在健康请求返回成功状态码后置为就绪，避免错误响应被当作后端可用。

## 3.4 v0.5.4 数据完整性与任务收束修复

v0.5.4 继续处理不易在正常演示流程中暴露、但会累积错误状态的问题。

- 项目移除现在显式删除该项目下的对话与短期消息，修复旧数据库迁移结构或未启用 SQLite 外键时遗留不可见孤儿数据的问题。
- SQLite 新连接启用外键约束，确保带级联约束的新数据结构按设计维护引用完整性。
- 创建项目对话前校验项目仍然存在，避免界面操作与删除操作交错时生成无法访问的孤儿对话。
- 取消 3D 生成时，即使 ComfyUI 中断接口已经离线，Sidecar 仍会将运行中的任务记录为已取消，并把中断不可达作为可诊断提示返回。

## 3.5 v0.5.5 Agent 前缀缓存优化

v0.5.5 调整工具模式的上下文组织方式，以适配支持自动 Prompt/Context Caching 的 OpenAI-compatible 模型服务。

- 将较稳定的 Agent 工具规则作为系统提示的长公共前缀保留。
- 将可能随记忆分支结构变化的记忆地图放置在固定规则之后，减少动态内容使整个规则前缀失效的机会。
- 记忆工具 schema 不再把动态分支列表写入 `enum`；合法分支仍由 Sidecar 执行端校验，工具定义可保持稳定。
- 不发送供应商专属缓存参数；实际缓存命中由已配置模型服务对相同前缀的支持决定。
- 新增回归测试，验证动态记忆地图变化时，固定 Agent 指令前缀与工具 schema 保持完全一致。

## 3.6 v0.5.6 网络检索与 DeepSeek API 适配

v0.5.6 在不破坏前缀缓存优化的前提下，为 Agent 增加联网资料查询能力，并在模型配置中加入 DeepSeek OpenAI-compatible API 预设。

- 新增 `web_search` 工具，通过 DuckDuckGo HTML 搜索页返回标题、链接、摘要和来源域名。
- 新增 `web_fetch` 工具，只读取明确 HTTP/HTTPS 单页正文，清理脚本、样式和 SVG 内容，不做整站递归爬取。
- 搜索结果和网页正文作为不可信外部数据处理，Agent 只摘要、引用和核对内容，不执行网页内指令。
- web 工具 schema 以稳定定义接入 `memory_map.py`，动态记忆地图继续放在稳定指令前缀之后，保证 v0.5.5 的缓存命中优化仍可生效。
- 设置页新增 DeepSeek provider，默认 Base URL 为 `https://api.deepseek.com`，模型名可填写 `deepseek-chat` 或其他兼容模型。

## 4. Agent 工具编排设计

### 4.1 设计目标

`0.4.0` 迭代将连续生成任务从固定流程分支提升为 LLM 可规划的工具执行过程。对于需要依赖中间产物的请求，路由器选择 `general_tools`，由模型查看每次工具返回的真实路径后决定下一步调用。

示例请求：

```text
生成一张飞船的图片，并生成三视图，然后生成模型
```

对应可执行链路：

```text
generate_image
-> generate_multiview_images_from_image
-> generate_3d_from_generated_multiview
```

### 4.2 依赖与安全约束

- 后一步必须使用前一步实际返回的图片路径，不允许由模型编造本地文件路径。
- 多视角建模只接受系统已经标识为 `front`、`left`、`back` 的三视图，不让 LLM 猜测用户上传图片的视角关系。
- 组合任务进入通用工具循环后，旧的单步图片/3D 快捷通道不再抢先执行。
- 工具调用循环提供足够回合，支持“生成/修改图片 -> 三视图 -> 建模 -> 汇总回复”的连续执行。

## 5. 外观修改与模型重建边界

当前版本没有直接编辑 `.glb` 网格、拓扑或材质参数的工具。因此用户说：

```text
把刚才这个模型改成金属材质，生成三视图，然后重建模型
```

系统将其解释为视觉外观重建流程：

```text
找到上一模型关联的活跃源图或预览图
-> modify_image_with_flux（把图片修改为金属材质）
-> generate_multiview_images_from_image（生成 front/left/back）
-> generate_3d_from_generated_multiview（生成新的 GLB 模型）
```

最终产物是基于修改后图片重新生成的新模型，而不是直接修改原有 GLB。响应中会标明 `重建源图` 与三视图路径，便于用户核对新模型的视觉依据。

## 6. 模型预览稳定性修复

模型预览的实体/线框切换曾会直接改写加载模型共享材质，导致从线框切回实体后出现异常偏色。`0.4.0` 中，预览组件在应用线框模式前为网格克隆材质实例，线框颜色仅影响当前显示状态，不再污染实体材质。

涉及模块：

- `src/components/ThreeDStudio/ModelPreview.tsx`

## 7. 关键实现模块

| 模块 | 本次职责 |
| --- | --- |
| `sidecar/memory/memory_map.py` | 注册 `generate_image`、三视图与多视图重建工具，描述外观修改边界 |
| `sidecar/memory/manager.py` | 提供工具范围判断与 Agent 连续编排规则 |
| `sidecar/routes/chat.py` | 工具循环、路由让行、中间产物聚合、同步与流式输出 |
| `sidecar/tools/comfy_client.py` | 执行图片编辑、三视图生成及 Hunyuan3D 多视角重建 |
| `src/components/ThreeDStudio/ModelPreview.tsx` | 修复线框切换造成的材质污染 |

## 8. 验证记录

本次迭代已完成以下检查：

- Python 语法检查：`python -m py_compile sidecar/routes/chat.py sidecar/memory/manager.py sidecar/memory/memory_map.py`
- 前端类型检查：`npm run typecheck`
- 生产构建：`npm run build`
- Agent 编排模拟验证：`generate_image -> generate_multiview_images_from_image -> generate_3d_from_generated_multiview`
- 外观修改重建模拟验证：`modify_image_with_flux -> generate_multiview_images_from_image -> generate_3d_from_generated_multiview`
- API 入口回归验证：同步与流式响应在组合任务中均进入工具循环，不被旧单步分支截断。
- 同步验证：工作目录与决赛版本目录中的相关修改文件保持一致。
- v0.5.3 回归验证：`python -m sidecar` 入口导入、含空格 ComfyUI 启动参数、Rust Unicode 摘要单元测试，以及 `npm run check`、`npm run build`、`cargo test`、Python 全量编译检查。
- v0.5.4 回归验证：新增项目级联清理、无效项目对话拒绝、离线取消收束三条自动化测试；执行 `npm run check`、`npm run build` 与 `cargo test --manifest-path src-tauri/Cargo.toml`。
- v0.5.5 回归验证：新增提示前缀稳定性测试；执行 `npm run check`、`npm run build` 与 `cargo test --manifest-path src-tauri/Cargo.toml`。
- v0.5.6 回归验证：新增网络工具解析、非 HTTP URL 拒绝、web 工具缓存前缀稳定性测试；执行 `npm run check` 与 `npm run build`。

构建阶段的 Vite 主 chunk 体积提示仍存在，但不影响构建成功或本次功能验证。

## 9. 后续优化方向

- 将工具调用步骤、耗时与中间产物形成可视化任务轨迹。
- 为路由决策和依赖型工具链增加自动化测试用例。
- 增加面向真实网格/材质的模型编辑工具，以区分视觉重建与原模型编辑。
- 持续优化前端拆包，降低主 bundle 体积。
