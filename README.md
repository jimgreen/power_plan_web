# Power Plan Web

考察站风-光-氢-储-柴联合规划系统的本地 Web 应用。项目提供方案参数维护、8760 时序数据维护、规划求解、方案评估、结果对比、任务并发和用户管理等页面，后台使用 Python 内置 HTTP 服务提供静态页面和 JSON API。

## 功能概览

- 参数维护：维护时序数据、设备参数、规划参数，并保存为方案工作簿。
- 规划求解：建立设备台数与小时级运行联合 MILP，输出规划结果、年度指标、小时曲线和安全曲线。
- 方案评估：读取方案与结果工作簿，重新评估经济性、绿电、安全等指标。
- 结果对比：对多个方案或结果文件做指标和曲线对比。
- 任务并发：统一查看规划求解和方案评估任务，可启动、排队、停止。
- 用户管理：基于 SQLite 的本地用户、登录和权限控制。开发时可使用本地免登录模式。

## 文件结构

```text
power_plan_web/
├── index.html                # 系统首页
├── planning.html             # 参数维护页面
├── optimize.html             # 规划求解页面
├── evaluation.html           # 方案评估页面
├── comparison.html           # 结果对比页面
├── tasks.html                # 任务并发页面
├── users.html                # 用户管理页面
├── login.html/register.html  # 登录和注册页面
├── assets/                   # 前端 JS/CSS/图片资源
│   ├── planning.js           # 参数维护前端逻辑
│   ├── optimize.js           # 规划求解前端逻辑
│   ├── evaluation.js         # 方案评估前端逻辑
│   ├── comparison.js         # 结果对比前端逻辑
│   ├── tasks.js              # 任务并发前端逻辑
│   ├── auth.js               # 登录态处理
│   ├── i18n.js               # 中英文界面翻译
│   └── planning.css          # 主要页面样式
├── server.py                 # Web 服务、API、任务运行时、结果导入导出
├── planning_store.py         # 方案目录与 parameters.xlsx 读写、默认值、参数校验
├── plan_optimizer.py         # 规划 MILP 建模、频率安全约束、结果整理
├── dispatch_milp.py          # MILP 建模工具和共享运行约束
├── milp_solver.py            # Gurobi/CPLEX/MOSEK/SciPy 求解器适配
├── calculation_precheck.py   # 求解前快速可行性检查
├── estimate.py               # 统计、聚合、指标计算工具
├── file_cache.py/file_ops.py # 文件缓存和安全文件操作
├── data/                     # 示例或模板数据
├── docs/                     # 详细算法和使用说明文档
├── tests/                    # 单元测试
├── requirements.txt          # Python 依赖
├── start_server.sh           # Linux/macOS 本地启动脚本
├── start_server.bat          # Windows 本地启动脚本
└── planning_schemes/         # 本地方案目录，默认不纳入 git
```

运行时还会使用或生成以下本地文件：

- `planning_schemes/<方案名>/parameters.xlsx`：方案参数工作簿。
- `planning_schemes/<方案名>/opt_results.xlsx`：规划求解默认结果工作簿。
- `planning_schemes/<方案名>/*_results.xlsx`：评估保存的其他结果工作簿。
- `power_plan_users.sqlite3`：用户与会话数据库。
- `web-server.out.log`、`web-server.err.log`：本地服务日志。

## 环境准备

推荐使用项目上一级的虚拟环境：

```bash
cd /home/yzk/cap_plan
python3 -m venv venv
./venv/bin/pip install -r power_plan_web/requirements.txt
```

也可以在 `power_plan_web/.venv` 中建立虚拟环境。`server.py` 启动时会自动尝试切换到以下虚拟环境：

1. `POWER_PLAN_VENV` 指定的位置
2. `../venv`
3. `../.venv`
4. `./.venv`

如需禁止自动切换虚拟环境：

```bash
export POWER_PLAN_DISABLE_VENV_BOOTSTRAP=1
```

基础依赖见 `requirements.txt`。商业 MILP 求解器不是必需项；`milp_solver.py` 会按 Gurobi、CPLEX、MOSEK、SciPy 的顺序自动尝试，最终可回退到 SciPy HiGHS。

## 启动方式

Linux/macOS：

```bash
cd /home/yzk/cap_plan/power_plan_web
./start_server.sh
```

Windows：

```bat
cd /d D:\final\cap_plan\power_plan_web
start_server.bat
```

直接启动：

```bash
cd /home/yzk/cap_plan/power_plan_web
POWER_PLAN_LOCAL_AUTH_BYPASS=1 ../venv/bin/python server.py --host 127.0.0.1 --port 8866
```

浏览器访问：

```text
http://127.0.0.1:8866/
```

常用页面：

- 参数维护：`http://127.0.0.1:8866/planning.html`
- 规划求解：`http://127.0.0.1:8866/optimize.html`
- 方案评估：`http://127.0.0.1:8866/evaluation.html`
- 任务并发：`http://127.0.0.1:8866/tasks.html`

## 常用环境变量

| 变量 | 作用 |
| --- | --- |
| `POWER_PLAN_LOCAL_AUTH_BYPASS=1` | 本地开发免登录，以管理员身份进入系统 |
| `POWER_PLAN_DISABLE_VENV_BOOTSTRAP=1` | 禁止 `server.py` 自动切换虚拟环境 |
| `POWER_PLAN_VENV=/path/to/venv` | 指定虚拟环境目录或 Python 解释器 |
| `POWER_PLAN_USER_DB=/path/to/users.sqlite3` | 指定用户数据库文件 |
| `POWER_PLAN_AMAP_KEY=...` | 指定高德 Web 服务 Key |
| `POWER_PLAN_DB_HOST` 等 | MySQL 连接配置，兼容旧监控/数据接口 |

## 使用流程

1. 打开参数维护页面。
2. 新建或复制方案。
3. 维护 8760 点时序数据，可文件导入、负荷生成、坐标取气象数据，也可在表格和曲线中修改。
4. 维护设备参数，包括成本、容量、台数上下限、寿命、柴发频率参数、构网型储能参数等。
5. 维护规划参数，包括绿电比例、扰动后安全参数、频率安全参数、初始 SOC、求解时间上限等。
6. 保存方案。
7. 打开规划求解页面，选择方案并启动求解。
8. 求解完成后查看规划结果、经济性、绿电、安全性和小时曲线。
9. 如需固定当前规划结果做运行校核，进入方案评估页面保存评估结果。
10. 如需多方案比较，进入结果对比页面选择方案和结果工作簿。

## 方案参数说明

方案参数存储在 `planning_schemes/<方案名>/parameters.xlsx`。主要工作表由 `planning_store.py` 中的 `SHEET_SPECS` 定义。

常见工作表：

- `时序数据`：8760 点风速、太阳辐照、温度、负荷。
- `柴发参数`：柴发成本、容量、运行上下限、油耗率、频率响应参数、数量上下限。
- `风机参数`、`光伏参数`：新能源设备参数和数量上下限。
- `储能PCS参数`：PCS 功率、效率、是否构网、构网型储能等效频率参数。
- `储能电池组参数`：电池容量、SOC 上下限、自损耗和数量上下限。
- `电制氢参数`、`储氢罐参数`、`燃料电池参数`：氢系统设备参数。
- `规划参数`：全局经济、安全、频率、扰动和求解配置。

旧工作簿缺少新字段时，读取时会用 `DEFAULT_PLANNING_PARAMETERS` 和设备默认值补齐。保存方案后会按当前字段列表重写。

## 频率安全约束

频率安全框架在 `plan_optimizer.py` 中实现。打开“是否考虑频率安全约束”后，模型会在每小时加入下限场景和上限场景约束，并在结果中输出最低频率、最高频率、稳态频率、RoCoF、频率裕度和等效频率参数。

当前网页保留的频率安全输入均会进入优化器或结果评估：

- `额定频率(Hz)`
- `频率最低点下限(Hz)`
- `频率最高点上限(Hz)`
- `频率下限安全裕度(Hz)`
- `频率上限安全裕度(Hz)`
- `负荷频率系数D`
- `RoCoF上限(Hz/s)`
- `稳态频率下限(Hz)`
- `稳态频率上限(Hz)`
- `频率等效调速时间常数T(s)`
- `频率Nadir评估时长(s)`
- `Nadir线性化每轴采样点数`
- `Nadir线性化区间比例`
- `频率下限扰动功率(kW)`
- `频率上限扰动功率(kW)`
- `网络同步系数基值`
- `网络同步系数斜率`
- `网络同步系数基准负荷(kW)`
- `储能是否参与调频`

频率扰动功率 `Delta P` 的映射：

- 下限场景自动值：`负荷 * 负荷向上扰动系数 + 新能源可用出力上界 * 新能源向下扰动系数`
- 上限场景自动值：`-负荷 * 负荷向下扰动系数`
- `频率下限扰动功率(kW)` 和 `频率上限扰动功率(kW)` 是手动覆盖值，仅在填入大于 0 时生效；填 0 时使用自动映射。

旧字段 `频率安全上限(1.0-1.5)` 和 `频率安全下限(0.5-1.0)` 已从网页、工作簿字段定义和校验逻辑中删除。

## 主要 API

页面通过 `server.py` 暴露 JSON API：

- `/api/auth/*`：登录、注册、退出、当前用户。
- `/api/planning/schemes`：方案列表、新建、读取、保存、复制、改名、删除。
- `/api/planning/time-series/import`：导入时序数据。
- `/api/planning/load-curve/*`：负荷曲线导入、生成、模板。
- `/api/planning/weather-history`：根据地点和年份获取历史气象。
- `/api/optimization/status`：规划求解状态和结果。
- `/api/optimization/control`：启动、排队、停止规划求解。
- `/api/evaluation/status`、`/api/evaluation/control`：方案评估状态和控制。
- `/api/evaluation/results`：评估结果文件读写。
- `/api/comparison/data`：结果对比数据。
- `/api/tasks`、`/api/tasks/control`：并发任务列表和控制。

## 测试

运行核心测试：

```bash
cd /home/yzk/cap_plan/power_plan_web
../venv/bin/python -m unittest tests.test_planning_store tests.test_plan_optimizer
../venv/bin/python -m unittest tests.test_dispatch_milp tests.test_milp_solver
```

运行服务器和页面相关测试：

```bash
../venv/bin/python -m unittest tests.test_server
```

`tests.test_server` 包含部分较慢的集成用例。开发某个页面或接口时，可以优先运行对应的目标用例。

语法检查：

```bash
python3 -m py_compile server.py planning_store.py plan_optimizer.py dispatch_milp.py
```

## Git 与本地数据

`.gitignore` 默认忽略：

- `planning_schemes/`
- `*.sqlite`、`*.sqlite3`
- `server*.log`
- `__pycache__/`
- `.pytest_cache/`
- `vendor/`

因此方案工作簿、结果工作簿、用户数据库和日志默认不会进入 Git。提交前建议检查：

```bash
git status --short
git diff --stat
```

## 常见问题

### 页面仍显示旧参数

前端 JS/CSS 使用版本号做缓存控制。若已经更新代码但浏览器仍显示旧字段，先确认 `planning.html` 中 `assets/planning.js?v=...` 已更新，再按 `Ctrl+F5` 强制刷新。

### 浏览器直接访问要求登录

本地开发可使用：

```bash
POWER_PLAN_LOCAL_AUTH_BYPASS=1 ../venv/bin/python server.py --host 127.0.0.1 --port 8866
```

或直接使用 `start_server.sh` / `start_server.bat`，脚本默认启用本地免登录。

### 求解返回不可行

优先检查：

- 设备数量上限是否足够。
- 构网型储能是否启用并配置了 `is_grid_forming=1`。
- 频率安全约束是否过严，例如 Nadir/Peak 限值、RoCoF 上限、扰动系数、手动扰动功率。
- 储能 SOC 上下限和初始 SOC 是否与运行需求冲突。
- 绿色电量占比下限是否过高。

### 依赖只在外层虚拟环境中存在

`server.py` 默认会优先使用 `../venv`。如果仍然使用了错误解释器，可显式设置：

```bash
POWER_PLAN_VENV=/home/yzk/cap_plan/venv python3 server.py --host 127.0.0.1 --port 8866
```

### 端口被占用

查找并停止旧进程：

```bash
ps -ef | grep 'server.py --host 127.0.0.1 --port 8866'
kill <pid>
```

或换端口启动：

```bash
../venv/bin/python server.py --host 127.0.0.1 --port 8877
```
