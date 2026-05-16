(() => {
  const STORAGE_KEY = "powerPlanLanguage";
  const LANGUAGES = [
    { code: "zh", label: "中文" },
    { code: "en", label: "English" },
  ];

  const dictionary = {
    "考察站风-光-氢-储-柴联合规划系统": "Station Wind-Solar-Hydrogen-Storage-Diesel Planning System",
    "系统首页": "Home",
    "参数维护": "Parameters",
    "规划求解": "Planning Solver",
    "方案评估": "Scenario Evaluation",
    "结果对比": "Result Comparison",
    "任务并发": "Task Concurrency",
    "用户管理": "User Management",
    "结果比对": "Result Comparison",
    "当前用户:": "Current user:",
    "退出": "Logout",
    "管理员": "Admin",
    "普通用户": "User",
    "用户登录": "User Login",
    "用户注册": "User Registration",
    "用户名": "Username",
    "密码": "Password",
    "登录": "Login",
    "注册新用户": "Register",
    "注册并登录": "Register and Login",
    "返回登录": "Back to Login",
    "处理中...": "Processing...",
    "请求失败": "Request failed",
    "刷新状态": "Refresh Status",
    "展示所有规划计算任务和方案评估任务": "Show all planning calculation and scenario evaluation tasks",
    "规划计算任务": "Planning Calculation Tasks",
    "方案评估任务": "Scenario Evaluation Tasks",
    "方案名称": "Scenario Name",
    "全部方案": "All Scenarios",
    "按方案名称筛选方案评估任务": "Filter scenario evaluation tasks by scenario name",
    "任务类型": "Task Type",
    "规划计算": "Planning Calculation",
    "任务所用方案": "Task Scenario",
    "任务所用结果": "Task Result",
    "任务状态": "Task Status",
    "立刻启动": "Start Now",
    "加入排队": "Queue",
    "退出队列": "Exit Queue",
    "停止计算": "Stop Calculation",
    "从等待队列中删除当前方案": "Remove current scenario from the waiting queue",
    "从等待队列中删除当前评估任务": "Remove current evaluation task from the waiting queue",
    "当前方案已加入队列": "Current scenario is queued",
    "当前评估任务已加入队列": "Current evaluation task is queued",
    "将当前方案加入排队": "Queue current scenario",
    "将当前评估任务加入排队": "Queue current evaluation task",
    "未计算": "Not Calculated",
    "排队中": "Queued",
    "计算中": "Calculating",
    "完成计算": "Completed",
    "启动": "Start",
    "停止": "Stop",
    "进程号": "PID",
    "计算开始时刻": "Calculation Start Time",
    "计算结束时刻": "Calculation End Time",
    "计算总用时(秒)": "Elapsed Time (s)",
    "最新更新日志": "Latest Log",
    "暂无任务": "No tasks",
    "暂无规划计算任务": "No planning calculation tasks",
    "暂无方案评估任务": "No scenario evaluation tasks",
    "调整规划计算和方案评估任务表高度": "Resize planning calculation and scenario evaluation task tables",
    "任务类型必须为规划计算或方案评估": "Task type must be planning calculation or scenario evaluation",
    "方案列表": "Scenario List",
    "当前:": "Current:",
    "未选择方案": "No scenario selected",
    "未选择结果": "No result selected",
    "当前: 未选择方案": "Current: No scenario selected",
    "当前: 未选择方案/未选择结果": "Current: No scenario selected / No result selected",
    "名称": "Name",
    "时序数据": "Time Series",
    "设备参数": "Device Parameters",
    "规划参数": "Planning Parameters",
    "柴油价格(万元/吨)": "Diesel Price (10k CNY/t)",
    "绿色电量占比下限(0.0-1.0)": "Green Energy Ratio Lower Bound (0.0-1.0)",
    "规划求解时间上限(分钟)": "Planning Solver Time Limit (minutes)",
    "初始电储SOC(0.0-1.0)": "Initial Battery SOC (0.0-1.0)",
    "初始氢储SOC(0.0-1.0)": "Initial Hydrogen Storage SOC (0.0-1.0)",
    "成本(万元/台)": "Cost (10k CNY/unit)",
    "容量": "Capacity",
    "容量(kW)": "Capacity (kW)",
    "容量(kWh)": "Capacity (kWh)",
    "容量(Nm3)": "Capacity (Nm3)",
    "功率上限(kW)": "Power Upper Limit (kW)",
    "功率下限(kW)": "Power Lower Limit (kW)",
    "油耗率(kg/kWh)": "Fuel Consumption Rate (kg/kWh)",
    "切入风速(m/s)": "Cut-in Wind Speed (m/s)",
    "额定风速(m/s)": "Rated Wind Speed (m/s)",
    "切出风速(m/s)": "Cut-out Wind Speed (m/s)",
    "数量下限(台)": "Quantity Lower Bound (units)",
    "数量上限(台)": "Quantity Upper Bound (units)",
    "设计年限(年）": "Design Life (years)",
    "设计年限(年)": "Design Life (years)",
    "自损耗率(0-1%/天)": "Self-discharge Rate (0-1%/day)",
    "氢-电效率(kWh/Nm3)": "Hydrogen-to-Electric Efficiency (kWh/Nm3)",
    "电-氢效率(Nm3/kWh)": "Electric-to-Hydrogen Efficiency (Nm3/kWh)",
    "充电效率(0.0-1.0)": "Charge Efficiency (0.0-1.0)",
    "放电效率(0.0-1.0)": "Discharge Efficiency (0.0-1.0)",
    "惯量常数H(s)": "Inertia Constant H(s)",
    "惯量常数H(s)必须在1.0到10.0之间": "Inertia constant H(s) must be between 1.0 and 10.0",
    "一次调频系数K": "Primary Frequency Coefficient K",
    "一次调频系数K必须在0.1到1.0之间": "Primary frequency coefficient K must be between 0.1 and 1.0",
    "阻尼系数D": "Damping Coefficient D",
    "阻尼系数D必须在0.001到1.0之间": "Damping coefficient D must be between 0.001 and 1.0",
    "调速时间常数T(s)": "Governor Time Constant T(s)",
    "调速时间常数T(s)必须在0.1到2.0之间": "Governor time constant T(s) must be between 0.1 and 2.0",
    "等效惯量常数H(s)": "Equivalent Inertia Constant H(s)",
    "等效惯量常数H(s)必须在0.5到10.0之间": "Equivalent inertia constant H(s) must be between 0.5 and 10.0",
    "等效一次调频系数K": "Equivalent Primary Frequency Coefficient K",
    "等效一次调频系数K必须在0.1到5.0之间": "Equivalent primary frequency coefficient K must be between 0.1 and 5.0",
    "等效阻尼系数D": "Equivalent Damping Coefficient D",
    "等效阻尼系数D必须在0.001到1.0之间": "Equivalent damping coefficient D must be between 0.001 and 1.0",
    "储能是否参与调频": "Storage Participates in Frequency Regulation",
    "是否考虑扰动后平衡约束": "Post-Disturbance Balance Constraint",
    "负荷向上扰动系数(0.0-0.5)": "Load Up Disturbance Factor (0.0-0.5)",
    "负荷向下扰动系数(0.0-0.5)": "Load Down Disturbance Factor (0.0-0.5)",
    "新能源向下扰动系数(0.0-0.5)": "Renewable Down Disturbance Factor (0.0-0.5)",
    "是否考虑频率安全约束": "Frequency Security Constraint",
    "频率安全上限(1.0-1.5)": "Frequency Security Upper Bound (1.0-1.5)",
    "频率安全下限(0.9-1.0)": "Frequency Security Lower Bound (0.9-1.0)",
    "频率安全下限(0.5-1.0)": "Frequency Security Lower Bound (0.5-1.0)",
    "频率最低点下限(Hz)": "Frequency Nadir Lower Limit (Hz)",
    "频率最高点上限(Hz)": "Frequency Peak Upper Limit (Hz)",
    "频率下限安全裕度(Hz)": "Lower Frequency Safety Margin (Hz)",
    "频率上限安全裕度(Hz)": "Upper Frequency Safety Margin (Hz)",
    "负荷频率系数D": "Load Frequency Coefficient D",
    "RoCoF上限(Hz/s)": "RoCoF Upper Limit (Hz/s)",
    "稳态频率下限(Hz)": "Steady-State Frequency Lower Limit (Hz)",
    "稳态频率上限(Hz)": "Steady-State Frequency Upper Limit (Hz)",
    "频率Nadir评估时长(s)": "Frequency Nadir Evaluation Duration (s)",
    "Nadir线性化每轴采样点数": "Nadir Linearization Samples per Axis",
    "Nadir线性化区间比例": "Nadir Linearization Interval Ratio",
    "网络同步系数基值": "Network Synchronization Coefficient Base",
    "网络同步系数斜率": "Network Synchronization Coefficient Slope",
    "网络同步系数基准负荷(kW)": "Network Synchronization Reference Load (kW)",
    "Nadir线性化每轴采样点数必须为正整数": "Nadir linearization samples per axis must be a positive integer",
    "稳态频率上限(Hz)不能小于稳态频率下限(Hz)": "Steady-state frequency upper limit cannot be lower than the lower limit",
    "是否考虑新能源N-1": "Renewable N-1 Constraint",
    "是否考虑负荷扰动": "Load Disturbance Constraint",
    "方案概览": "Scenario Overview",
    "统计直方图": "Statistical Histograms",
    "待选设备列表": "Candidate Device List",
    "校验与摘要": "Validation and Summary",
    "时序行数": "Time Series Rows",
    "时序行数：": "Time Series Rows: ",
    "设备条目": "Device Entries",
    "设备条目：": "Device Entries: ",
    "暂无设备条目": "No device entries",
    "新建方案": "New Scenario",
    "复制方案": "Copy Scenario",
    "修改名称": "Rename",
    "保存方案": "Save Scenario",
    "删除方案": "Delete Scenario",
    "导入曲线": "Import Curves",
    "曲线已修改，请保存方案": "Curve updated. Please save the scenario",
    "负荷生成": "Generate Load",
    "负荷曲线已调整，请检查预览后点击确定。": "Load curve adjusted. Please review the preview and confirm.",
    "坐标选择": "Select Coordinates",
    "地图接口切换": "Map Provider Switch",
    "高德地图": "Amap",
    "OpenStreetMap": "OpenStreetMap",
    "确认坐标": "Confirm Coordinates",
    "纬度": "Latitude",
    "经度": "Longitude",
    "历史数据年": "Historical Year",
    "获取历史气象": "Fetch Weather History",
    "风速": "Wind Speed",
    "太阳辐射": "Solar Irradiance",
    "太阳辐照": "Solar Irradiance",
    "温度": "Ambient Temperature",
    "室温": "Ambient Temperature",
    "负荷": "Load",
    "环境温度": "Ambient Temperature",
    "曲线预览": "Curve Preview",
    "导入曲线预览": "Imported Curve Preview",
    "导入曲线显示切换": "Imported Curve Display Toggle",
    "调整导入曲线预览高度": "Resize imported curve preview height",
    "导入曲线已调整，请确认后保存。": "Imported curves adjusted. Please confirm to save.",
    "打开文件后，在这里预览8760点曲线。": "Open a file to preview the 8760-point curves here.",
    "打开文件后显示曲线预览": "Curve preview appears after opening a file",
    "请选择至少一条曲线": "Please select at least one curve",
    "负荷总功率": "Total Load Power",
    "启动优化": "Start Optimization",
    "启动评估": "Start Evaluation",
    "停止优化": "Stop Optimization",
    "停止评估": "Stop Evaluation",
    "运行日志": "Run Log",
    "评估日志": "Evaluation Log",
    "曲线展示": "Curves",
    "结果概览": "Result Overview",
    "供能分析": "Energy Analysis",
    "安全评估": "Safety Assessment",
    "安全分析": "Safety Analysis",
    "评估概览": "Evaluation Overview",
    "经济性评估": "Economic Assessment",
    "安全性评估": "Safety Assessment",
    "经济性指标": "Economic Indicators",
    "安全性指标": "Safety Indicators",
    "状态": "Status",
    "开始": "Start",
    "完成": "Finish",
    "停止求解": "Stop Solver",
    "待启动": "Not Started",
    "度电成本": "LCOE",
    "绿电占比": "Green Energy Share",
    "总成本": "Total Cost",
    "绿色电量占比": "Green Energy Ratio",
    "综合评分": "Score",
    "风险等级": "Risk Level",
    "当前规划结果": "Current Planning Result",
    "删除结果": "Delete Result",
    "复制结果": "Copy Result",
    "保存结果": "Save Result",
    "暂无结果文件": "No result files",
    "暂无可读取结果文件": "No readable result files",
    "无法读取": "Unreadable",
    "结果文件": "Result file",
    "结果文件无法读取，可能已损坏或格式不正确": "Result file cannot be read. It may be damaged or in an invalid format.",
    "无法读取，请重新生成或删除该文件。": "Cannot be read. Please regenerate or delete this file.",
    "设备类型": "Device Type",
    "设计台数": "Designed Units",
    "单台容量": "Single Unit Capacity",
    "暂无规划结果": "No planning result",
    "成本构成": "Cost Composition",
    "年柴油成本": "Annual Diesel Cost",
    "年均建设成本": "Annualized Construction Cost",
    "运行成本": "Operating Cost",
    "建设成本": "Construction Cost",
    "电量构成": "Energy Composition",
    "柴发电量": "Diesel Generation",
    "绿电电量": "Green Energy",
    "新能源电量": "Renewable Energy",
    "是否构网": "Grid-forming",
    "SOC上限": "SOC Upper Bound",
    "SOC下限": "SOC Lower Bound",
    "是否构网必须为0或1": "Grid-forming must be 0 or 1",
    "SOC上限(0.0-1.0)必须在0到1之间": "SOC upper bound (0.0-1.0) must be between 0 and 1",
    "SOC下限(0.0-1.0)必须在0到1之间": "SOC lower bound (0.0-1.0) must be between 0 and 1",
    "设计台数必须为非负整数": "Designed units must be a non-negative integer",
    "请先选择结果文件": "Please select a result file first",
    "请先选择方案": "Please select a scenario first",
    "请输入新结果名称": "Enter a new result name",
    "复制失败": "Copy failed",
    "结果文件已删除": "Result file deleted",
    "结果文件已复制：": "Result file copied: ",
    "结果文件已保存：": "Result file saved: ",
    "小时级曲线": "Hourly Curves",
    "日级统计": "Daily Statistics",
    "月度统计": "Monthly Statistics",
    "年度统计": "Annual Statistics",
    "全年": "Full Year",
    "指定月": "Selected Month",
    "指定日": "Selected Day",
    "月份": "Month",
    "日期": "Day",
    "曲线时间范围筛选": "Curve Time Range Filter",
    "曲线时间范围": "Curve Time Range",
    "时序曲线时间范围筛选": "Time Series Curve Range Filter",
    "时序曲线时间范围": "Time Series Curve Range",
    "日级统计只支持全年或指定月筛选": "Daily statistics only support full-year or selected-month filters",
    "暂无小时级曲线": "No hourly curves",
    "请选择小时级曲线": "Please select hourly curves",
    "正在加载小时级曲线": "Loading hourly curves",
    "暂无日曲线": "No daily curve",
    "暂无可显示曲线": "No visible curves",
    "暂无曲线": "No curves",
    "年度统计以表格显示": "Annual statistics are shown as a table",
    "暂无年度统计": "No annual statistics",
    "规划容量对比": "Planning Capacity Comparison",
    "供能指标对比": "Energy Indicator Comparison",
    "安全指标对比": "Safety Indicator Comparison",
    "经济性指标对比": "Economic Indicator Comparison",
    "安全性指标对比": "Safety Indicator Comparison",
    "添加对比": "Add Comparison",
    "对比": "Comparison",
    "方案列表": "Scenario List",
    "结果列表": "Result List",
    "暂无方案": "No scenarios",
    "暂无结果": "No results",
    "暂无规划容量对比": "No planning capacity comparison",
    "暂无供能指标对比": "No energy indicator comparison",
    "暂无安全指标对比": "No safety indicator comparison",
    "暂无经济性指标对比": "No economic indicator comparison",
    "暂无安全性指标对比": "No safety indicator comparison",
    "平均": "Avg",
    "最大": "Max",
    "最小": "Min",
    "合计": "Total",
    "指标": "Metric",
    "数值": "Value",
    "单位": "Unit",
    "风机总功率": "Total Wind Power",
    "光伏总功率": "Total PV Power",
    "柴发总功率": "Total Diesel Power",
    "电储能总功率": "Total Battery Power",
    "电储电量": "Battery Energy",
    "电制氢总功率": "Total Electrolyzer Power",
    "储氢罐氢储量": "Hydrogen Storage",
    "燃料电池总功率": "Total Fuel Cell Power",
    "风力最大可发": "Wind Available Power",
    "光伏最大可发": "PV Available Power",
    "新能源最大可发": "Renewable Available Power",
    "弃风总功率": "Curtailed Wind Power",
    "弃光总功率": "Curtailed PV Power",
    "新能源弃电总功率": "Renewable Curtailment Power",
    "切负荷功率": "Unserved Load Power",
    "负荷总电量": "Total Load Energy",
    "柴发总发电量": "Total Diesel Generation",
    "风机总发电量": "Total Wind Generation",
    "光伏总发电量": "Total PV Generation",
    "电储能总储电量": "Battery Charge Energy",
    "电储能总放电量": "Battery Discharge Energy",
    "电制氢总用电量": "Electrolyzer Energy Use",
    "氢储总增加量": "Hydrogen Storage Increase",
    "氢储总消耗量": "Hydrogen Storage Consumption",
    "燃料电池总发电量": "Fuel Cell Generation",
    "风力最大可发电量": "Available Wind Energy",
    "光伏最大可发电量": "Available PV Energy",
    "新能源最大可发电量": "Available Renewable Energy",
    "新能源实发电量": "Actual Renewable Energy",
    "弃风总电量": "Curtailed Wind Energy",
    "弃光总电量": "Curtailed PV Energy",
    "新能源总弃电量": "Total Renewable Curtailment",
    "切负荷总电量": "Unserved Load Energy",
    "新能源占比": "Renewable Share",
    "新能源弃电率": "Renewable Curtailment Rate",
    "柴发日电量": "Daily Diesel Energy",
    "风电日电量": "Daily Wind Energy",
    "光伏日电量": "Daily PV Energy",
    "氢能日电量": "Daily Hydrogen Energy",
    "储能放电量": "Storage Discharge Energy",
    "负荷电量": "Load Energy",
    "制氢电量": "Hydrogen Production Energy",
    "储能充电量": "Storage Charge Energy",
    "向上频率最大值": "Maximum Upward Frequency",
    "向下频率最小值": "Minimum Downward Frequency",
    "绿电日曲线": "Green Energy Daily Curve",
    "安全频率日曲线": "Safety Frequency Daily Curve",
    "暂无运行日志": "No run log",
    "暂无评估日志": "No evaluation log",
    "清空日志": "Clear Log",
    "保存日志到文件": "Save Log to File",
    "主功能导航": "Main Navigation",
    "规划求解操作": "Planning Solver Actions",
    "规划求解总体指标": "Planning Solver Summary Metrics",
    "规划求解结果切换": "Planning Solver Result Tabs",
    "方案评估操作": "Scenario Evaluation Actions",
    "方案评估总体指标": "Scenario Evaluation Summary Metrics",
    "方案评估结果切换": "Scenario Evaluation Result Tabs",
    "评估运行信息切换": "Evaluation Runtime View Tabs",
    "调整评估日志高度": "Resize evaluation log height",
    "结果文件管理": "Result File Management",
    "结果文件列表": "Result File List",
    "结果对比标签栏": "Result Comparison Tab Bar",
    "结果对比表格": "Result Comparison Tables",
    "调整结果显示和评估面板宽度": "Resize result list and evaluation panel",
    "调整左侧规划结果和中间构成图宽度": "Resize left planning result and middle composition chart",
    "调整中间构成图和右侧年指标宽度": "Resize middle composition chart and right annual metrics",
    "调整经济性指标表格和曲线宽度": "Resize economic indicator table and chart",
    "调整安全性指标表格和曲线宽度": "Resize safety indicator table and chart",
    "调整规划容量和经济性指标表格宽度": "Resize planning capacity and economic indicator tables",
    "调整经济性指标和安全性指标表格宽度": "Resize economic and safety indicator tables",
    "调整对比表格和曲线板高度": "Resize comparison tables and chart panel",
    "小时级曲线、日级统计、月度统计和年度统计列表": "Hourly curves, daily statistics, monthly statistics and annual statistics list",
    "小时级曲线、日级统计、月度统计和年度统计对比": "Hourly curves, daily statistics, monthly statistics and annual statistics comparison",
    "小时级曲线、日级统计、月度统计和年度统计名称": "Hourly curves, daily statistics, monthly statistics and annual statistics names",
    "日级统计 月度统计 年度统计": "Daily Statistics Monthly Statistics Annual Statistics",
    "语言": "Language",
    "中文": "Chinese",
    "用户名称": "Username",
    "权限": "Role",
    "创建时间": "Created At",
    "已删除": "Deleted",
    "操作": "Actions",
    "删除": "Delete",
    "关闭": "Close",
    "打开文件": "Open File",
    "文件导入": "Import File",
    "正在导入负荷文件": "Importing load file",
    "负荷文件导入成功，请检查预览后点击确定。": "Load file imported. Please check the preview and click OK.",
    "负荷文件导入失败：": "Load file import failed: ",
    "负荷文件已导入为原始曲线，请点击生成负荷曲线。": "Load file imported as the source curve. Click Generate Load Curve.",
    "原始负荷曲线已载入，请点击生成负荷曲线。": "Source load curve loaded. Click Generate Load Curve.",
    "正在载入原始负荷曲线...": "Loading source load curve...",
    "请选择负荷文件": "Please select a load file",
    "请先选择负荷文件": "Please select a load file first",
    "已从": "Imported ",
    "导入8760点负荷曲线": " as a 8760-point load curve",
    "导入8760点负荷原始曲线": " as a 8760-point source load curve",
    "文件共有": "source rows: ",
    "行，已自适应扩展到8760点": ", adapted to 8760 points",
    "已按相邻点自动补齐": "filled ",
    "个缺失时点": " missing time points",
    "已合并": "merged ",
    "个重复小时数据": " duplicate hourly records",
    "已修复": "repaired ",
    "个无效数值": " invalid values",
    "生成负荷曲线": "Generate Load Curve",
    "保存模板": "Save Template",
    "请输入负荷模板名称": "Enter load template name",
    "模板名称不能为空": "Template name cannot be empty",
    "正在保存负荷模板...": "Saving load template...",
    "负荷模板已保存：": "Load template saved: ",
    "负荷模板保存失败：": "Load template save failed: ",
    "负荷模板保存已取消": "Load template save canceled",
    "模板名称已存在": "Template name already exists",
    "是否覆盖保存？": "Overwrite?",
    "请先生成或导入负荷曲线": "Please generate or import a load curve first",
    "负荷模板": "Load Template",
    "模板1": "Template 1",
    "模板2": "Template 2",
    "模板3": "Template 3",
    "生成负荷曲线预览": "Generated load curve preview",
    "正在生成负荷曲线...": "Generating load curve...",
    "负荷曲线已生成，请检查预览后点击确定。": "Load curve generated. Please check the preview and click OK.",
    "请先生成负荷曲线": "Please generate or import a load curve first",
    "负荷曲线已确认，请保存方案": "Load curve confirmed. Please save the scenario",
    "负荷生成已取消": "Load generation canceled",
    "负荷最大值": "Load Max",
    "负荷最小值": "Load Min",
    "负荷平均值": "Load Average",
    "指定模式": "Mode",
    "随机曲线": "Random Curve",
    "模式1": "Pattern 1",
    "模式2": "Pattern 2",
    "模式3": "Pattern 3",
    "修改前": "Before",
    "修改后": "After",
    "确定": "OK",
    "取消": "Cancel",
    "暂无方案，请先在参数维护中新建方案。": "No scenarios. Please create one in Parameters first.",
    "暂无方案，请新建方案。": "No scenarios. Please create one.",
    "未加载": "Not Loaded",
    "未选择文件": "No file selected",
    "（无法读取）": "(Unreadable)",
    "请求后台失败，请检查 WEB 服务是否正常运行，或查看服务器错误日志。": "Failed to reach the backend. Please check whether the WEB service is running or review the server error log.",
    "后台处理失败:": "Backend processing failed:",
  };

  const translations = new Map(Object.entries(dictionary).map(([zh, en]) => [normalizeText(zh), en]));
  const reverseTranslations = new Map(Object.entries(dictionary).map(([zh, en]) => [normalizeText(en), zh]));
  const ignoredTags = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "SVG", "CANVAS"]);
  let observer = null;
  let translating = false;
  let dialogsPatched = false;

  function currentLanguage() {
    return localStorage.getItem(STORAGE_KEY) === "en" ? "en" : "zh";
  }

  function setLanguage(language) {
    const next = language === "en" ? "en" : "zh";
    localStorage.setItem(STORAGE_KEY, next);
    document.documentElement.lang = next === "en" ? "en" : "zh-CN";
    updateLanguageControl(next);
    translateDocument(next);
  }

  function boot() {
    insertLanguageControl();
    patchDialogs();
    setLanguage(currentLanguage());
    observer = new MutationObserver(() => {
      if (translating) return;
      translateDocument(currentLanguage());
    });
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  }

  function insertLanguageControl() {
    if (document.getElementById("languageSelect")) return;
    const wrap = document.createElement("label");
    wrap.className = "language-switch";
    wrap.innerHTML = `<span>语言</span><select id="languageSelect" aria-label="语言 / Language">${LANGUAGES.map((item) => `<option value="${item.code}">${item.label}</option>`).join("")}</select>`;
    const target = document.querySelector(".topbar .user-status") || document.querySelector(".home-user-status") || document.querySelector(".auth-card");
    if (target?.classList.contains("auth-card")) {
      target.parentNode.insertBefore(wrap, target);
    } else if (target) {
      target.parentNode.insertBefore(wrap, target);
    } else {
      document.body.insertBefore(wrap, document.body.firstChild);
    }
    wrap.querySelector("select").addEventListener("change", (event) => setLanguage(event.target.value));
  }

  function updateLanguageControl(language) {
    const select = document.getElementById("languageSelect");
    if (select) select.value = language;
  }

  function translateDocument(language) {
    translating = true;
    try {
      translateTextNodes(document.body, language);
      translateAttributes(document.body, language);
    } finally {
      translating = false;
    }
  }

  function translateTextNodes(root, language) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        if (!node.nodeValue || !node.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
        if (isIgnored(node.parentElement)) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach((node) => {
      const translated = translateText(node.nodeValue, language);
      if (translated !== node.nodeValue) node.nodeValue = translated;
    });
  }

  function translateAttributes(root, language) {
    root.querySelectorAll("[aria-label], [placeholder], [title]").forEach((element) => {
      ["aria-label", "placeholder", "title"].forEach((name) => {
        if (!element.hasAttribute(name)) return;
        const translated = translateText(element.getAttribute(name), language);
        if (translated !== element.getAttribute(name)) element.setAttribute(name, translated);
      });
    });
  }

  function translateText(text, language) {
    const raw = String(text ?? "");
    const trimmed = raw.trim();
    if (!trimmed) return raw;
    const leading = raw.match(/^\s*/)?.[0] || "";
    const trailing = raw.match(/\s*$/)?.[0] || "";
    const normalized = normalizeText(trimmed);
    const translated = language === "en" ? translateToEnglish(normalized) : translateToChinese(normalized);
    return translated === normalized ? raw : `${leading}${translated}${trailing}`;
  }

  function translateToEnglish(text) {
    if (translations.has(text)) return translations.get(text);
    for (const [zh, en] of partialTranslations(translations)) {
      if (text.includes(zh)) return text.replaceAll(zh, en);
    }
    return text;
  }

  function translateToChinese(text) {
    if (reverseTranslations.has(text)) return reverseTranslations.get(text);
    for (const [en, zh] of partialTranslations(reverseTranslations)) {
      if (text.includes(en)) return text.replaceAll(en, zh);
    }
    return text;
  }

  function partialTranslations(map) {
    return Array.from(map.entries()).sort((left, right) => right[0].length - left[0].length);
  }

  function patchDialogs() {
    if (dialogsPatched) return;
    dialogsPatched = true;
    const nativeAlert = window.alert.bind(window);
    const nativeConfirm = window.confirm.bind(window);
    const nativePrompt = window.prompt.bind(window);
    window.alert = (message) => nativeAlert(translateText(message, currentLanguage()));
    window.confirm = (message) => nativeConfirm(translateText(message, currentLanguage()));
    window.prompt = (message, defaultValue) => nativePrompt(translateText(message, currentLanguage()), defaultValue);
  }

  function normalizeText(value) {
    return String(value ?? "").replace(/\s+/g, " ").trim();
  }

  function isIgnored(element) {
    return !element || ignoredTags.has(element.tagName) || element.closest("[data-i18n-ignore]");
  }

  window.PowerPlanI18n = { setLanguage, currentLanguage, translate: translateText };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
