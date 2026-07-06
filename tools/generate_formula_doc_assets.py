from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "doc"
SRC = OUT / "model_algorithm_description_equations.md"
REFERENCE = OUT / "reference_equations.docx"


def set_east_asia_font(style, font_name: str) -> None:
    style.font.name = font_name
    style.element.rPr.rFonts.set(qn("w:eastAsia"), font_name)


def set_paragraph_style(style, *, font: str, size: int, bold: bool = False) -> None:
    set_east_asia_font(style, font)
    style.font.size = Pt(size)
    style.font.bold = bold
    style.paragraph_format.line_spacing = 1.0
    style.paragraph_format.space_after = Pt(4)
    style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY


def make_reference_docx() -> None:
    doc = Document()
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.2)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.4)
    section.right_margin = Cm(2.2)

    styles = doc.styles
    set_paragraph_style(styles["Normal"], font="宋体", size=12)
    set_paragraph_style(styles["Body Text"], font="宋体", size=12)
    set_paragraph_style(styles["Caption"], font="宋体", size=10)
    set_paragraph_style(styles["Heading 1"], font="黑体", size=18, bold=True)
    set_paragraph_style(styles["Heading 2"], font="黑体", size=15, bold=True)
    set_paragraph_style(styles["Heading 3"], font="黑体", size=13, bold=True)

    for style_name in ("Table Grid", "Compact"):
        if style_name in styles:
            set_east_asia_font(styles[style_name], "宋体")

    doc.add_paragraph("参考样式模板。")
    doc.save(REFERENCE)


def markdown() -> str:
    return r"""---
title: 考察站风光氢储柴联合规划模型与算法说明
author: Power Plan Web
date: 2026-05-25
lang: zh-CN
---

\newpage

# 文档目的与模型边界

本文档给出 Power Plan Web 后台“规划求解”和“方案评估”的统一数学模型说明。文档面向算法维护、工程校核和结果解释，重点描述目标函数、优化变量、运行约束、快速可行性预检查、求解器调用逻辑以及输出指标计算规则。与界面操作手册不同，本文不解释按钮位置和页面交互，而是说明每一次点击“启动”后，后台究竟构造了什么优化问题、为什么可能失败、结果文件中每类曲线和指标来自哪些数学表达式。

系统当前采用统一的混合整数线性规划模型。规划求解时，设备建设台数是整数决策变量；方案评估时，设备建设台数从当前结果文件读取，并通过上下界相等的方式固定，调度问题仍复用同一套 MILP 建模代码。因此，方案评估不是一个独立的简化仿真程序，而是“建设台数已知”的特殊规划问题。

系统调度时间尺度为小时级，全年共 8760 个点。模型在每个小时同时考虑负荷硬平衡、柴油发电机出力、风电和光伏最大可发、弃电、储能充放电、制氢、储氢、燃料电池发电以及可选的扰动后平衡约束。输出结果包括小时级曲线、日级统计、月度统计和年度指标。

核心优化问题可概括为：

$$
\min_{x,y,z}\; J(x,y,z)
\quad
\mathrm{s.t.}\quad
A x + B y + C z \leq b,\;
E x + F y + G z = h,\;
y \in \mathbb{Z},\;
z \in \{0,1\}
$$

其中，$x$ 表示连续运行变量，$y$ 表示整数台数变量，$z$ 表示充放电互斥等二进制状态变量。模型的主要工程目标是，在满足设备数量边界、设备运行约束、安全约束、绿电占比约束和无切负荷功率平衡的前提下，使年均建设成本和柴油成本最低，并用很小的辅助惩罚项进行运行状态择优。

主要模块包括：`plan_optimizer.py` 负责规划入口，读取方案参数、构造规划模型并写入结果文件；`estimate.py` 负责方案评估入口，读取方案和指定结果后固定建设台数；`dispatch_milp.py` 负责公共 MILP 建模，统一管理变量、目标函数、稀疏约束矩阵和公共约束；`milp_solver.py` 负责统一调用 Gurobi、CPLEX、MOSEK 和 SciPy/HiGHS；`calculation_precheck.py` 负责快速预检查，在正式求解前识别明显不可行场景。

# 集合、下标与时间尺度

模型使用离散小时集合 $\mathcal{T}$ 表示全年 8760 个运行时段：

$$
\mathcal{T}=\{1,2,\ldots,8760\}
$$

设备按类型划分为若干候选行集合。每一行代表一类设备参数，例如某一种柴油发电机、某一种风机或某一种储能 PCS。规划求解不是逐台枚举全部候选设备，而是对每个设备行设置建设台数变量，从而显著降低变量规模。

$$
\mathcal{G},\mathcal{W},\mathcal{P},\mathcal{S},\mathcal{B},\mathcal{E},\mathcal{H},\mathcal{F}
$$

分别表示柴油发电机、风机、光伏、储能 PCS、储能电池组、电制氢、储氢罐和燃料电池集合。

对于任一设备集合 $\mathcal{D}$，第 $i$ 行设备的建设台数记为：

$$
q_i^{\mathcal{D}} \in \mathbb{Z}_{+}
$$

设备台数必须满足界面维护的数量上下限：

$$
\underline{q}_i^{\mathcal{D}}
\leq
q_i^{\mathcal{D}}
\leq
\overline{q}_i^{\mathcal{D}}
$$

方案评估时，若结果文件中给出的设计台数为 $\hat{q}_i^{\mathcal{D}}$，则模型通过上下界相等来固定该变量：

$$
\underline{q}_i^{\mathcal{D}}
=
\overline{q}_i^{\mathcal{D}}
=
\hat{q}_i^{\mathcal{D}}
$$

这样做的优点是规划和评估共用同一套变量、约束和结果输出逻辑。若后续增加新的运行约束，只需要在公共 MILP 中增加一次，规划和评估可以同时生效。

# 输入数据与预处理

时序数据包括风速、太阳辐射、环境温度和负荷功率。负荷功率直接进入电力平衡约束，环境温度当前主要用于曲线输出和扩展分析，风速和太阳辐射用于计算风机和光伏的最大可发功率。

第 $t$ 小时的输入向量可写为：

$$
d_t = \left(v_t,\; r_t,\; \theta_t,\; L_t\right)
$$

其中，$v_t$ 为风速，$r_t$ 为太阳辐射，$\theta_t$ 为环境温度，$L_t$ 为负荷功率。导入文件不足 8760 行时，后台会提示并自动补齐；中间出现无效数值或断点时，优先使用相邻点插补，保证导入流程可以继续。该处理不改变模型结构，但会影响最大可发功率和负荷电量，因此导入后应在曲线板中检查形状是否合理。

负荷总电量为：

$$
E^{\mathrm{load}}=
\sum_{t\in\mathcal{T}} L_t \Delta t
$$

当前小时步长为 1 小时，因此：

$$
\Delta t = 1
$$

规划参数中的关键全局参数包括柴油价格、绿色电量占比下限、优化求解时间上限、初始电储 SOC、初始氢储 SOC、是否考虑扰动后平衡约束以及扰动系数。设备参数中的成本、设计年限、容量、效率、自损耗率、SOC 上下限、是否构网等参数直接进入约束或目标函数。

# 统一规划与评估建模

规划求解和方案评估的主要差异在建设台数是否可以优化。规划求解中，建设台数变量在数量上下限之间自由选择；方案评估中，建设台数被固定为当前结果文件中的设计台数。

规划求解的建设变量空间为：

$$
q_i^{\mathcal{D}}
\in
\left[
\underline{q}_i^{\mathcal{D}},
\overline{q}_i^{\mathcal{D}}
\right]\cap\mathbb{Z}_{+}
$$

方案评估的建设变量空间为：

$$
q_i^{\mathcal{D}}
=
\hat{q}_i^{\mathcal{D}}
$$

从数学上看，方案评估是规划模型的一个截面。这样处理可以避免“规划模型一套约束、评估模型另一套约束”带来的结果不一致问题。例如，当储能自损耗、氢储自损耗、构网储能约束、扰动后平衡约束发生调整时，规划求解和方案评估都会沿用同一套实现。

统一建模框架可以写成：

$$
\Omega_{\mathrm{eval}}
\subseteq
\Omega_{\mathrm{plan}}
$$

其中 $\Omega_{\mathrm{plan}}$ 是规划可行域，$\Omega_{\mathrm{eval}}$ 是固定建设台数后的评估可行域。若评估失败，通常意味着当前给定台数在全年 8760 小时联合优化下无法满足约束，而不是简单的前端显示问题。

# 决策变量

模型变量分为三大类：建设台数变量、小时级连续运行变量和小时级状态变量。

建设变量包括：

$$
q_i^{G},\;
q_i^{W},\;
q_i^{PV},\;
q_i^{PCS},\;
q_i^{BAT},\;
q_i^{EL},\;
q_i^{HT},\;
q_i^{FC}
$$

小时级主要连续变量包括柴油总出力、风电实际出力、光伏实际出力、弃风、弃光、储能充电、储能放电、电储 SOC、电制氢功率、氢储 SOC、燃料电池功率和切负荷功率：

$$
P_{g,t},\;
P_{w,t},\;
P_{pv,t},\;
C_{w,t},\;
C_{pv,t},\;
P_{ch,t},\;
P_{dis,t},\;
E_{bat,t},\;
P_{el,t},\;
H_{t},\;
P_{fc,t},\;
P_{shed,t}
$$

储能充放电互斥采用二进制变量：

$$
u_{ch,t},u_{dis,t}\in\{0,1\}
$$

柴发和电制氢不再按每台设备单独展开二进制变量，而是使用行级开机台数整数变量。第 $i$ 行柴发在第 $t$ 小时的开机台数为：

$$
n_{g,i,t}\in\mathbb{Z}_{+}
$$

第 $i$ 行电制氢在第 $t$ 小时的开机台数为：

$$
n_{el,i,t}\in\mathbb{Z}_{+}
$$

这种台数级建模可以保持启停和上下限约束，同时避免对每台候选设备建立大量 0/1 变量，有利于提高求解速度。

# 目标函数

规划求解目标函数由年均建设成本、柴油运行成本和辅助小惩罚项组成。模型不再使用切负荷成本项作为可行性兜底；切负荷变量仅为结果字段兼容而保留，并在规划和评估中固定为 0。设 $c_i^{\mathcal{D}}$ 为第 $i$ 行设备单台建设成本，单位为万元/台；$Y_i^{\mathcal{D}}$ 为设计年限，单位为年。设备年均建设成本为：

$$
C_{\mathrm{inv}}
=
\sum_{\mathcal{D}}
\sum_{i\in\mathcal{D}}
\frac{c_i^{\mathcal{D}}}{Y_i^{\mathcal{D}}}
q_i^{\mathcal{D}}
$$

柴油发电量对应的柴油消耗量为：

$$
M_{\mathrm{diesel}}
=
\frac{1}{1000}
\sum_{t\in\mathcal{T}}
\sum_{i\in\mathcal{G}}
\rho_i^{G} P_{g,i,t}\Delta t
$$

其中 $\rho_i^G$ 为油耗率，单位为 kg/kWh。除以 1000 后得到吨。年柴油成本为：

$$
C_{\mathrm{diesel}}
=
\pi_{\mathrm{diesel}} M_{\mathrm{diesel}}
$$

其中 $\pi_{\mathrm{diesel}}$ 为柴油价格，单位为万元/吨。若设备能力和运行约束无法满足每小时功率平衡，模型应返回不可行或求解失败，而不是通过切负荷变量获得可行解。

完整目标函数为：

$$
\min J
=
C_{\mathrm{inv}}
+C_{\mathrm{diesel}}
+C_{\mathrm{aux}}
$$

$C_{\mathrm{aux}}$ 表示用于改善求解稳定性的辅助小惩罚项，例如运行状态轻微惩罚。结果概览中的总成本通常只展示建设成本、柴油成本等业务指标，不把辅助惩罚作为经济指标解释。

# 电力平衡约束

每个小时必须满足无切负荷电力平衡。供电侧包括柴油发电、风电、光伏、储能放电和燃料电池发电；用电侧包括负荷、储能充电和电制氢。

$$
\sum_{i\in\mathcal{G}}P_{g,i,t}
+P_{w,t}
+P_{pv,t}
+P_{dis,t}
+\sum_{i\in\mathcal{F}}P_{fc,i,t}
=
L_t
+P_{ch,t}
+\sum_{i\in\mathcal{E}}P_{el,i,t}
$$

切负荷变量固定为 0：

$$
P_{shed,t}=0
$$

因此规划结果必须无未供负荷。若求解失败，应优先检查柴油、风光、储能和燃料电池容量是否不足，以及扰动后平衡约束是否过紧。

# 风机最大可发功率

风机最大可发功率由风速和单机容量共同决定。模型使用切入风速、额定风速和切出风速构造分段线性近似。设第 $i$ 行风机容量为 $S_i^W$，切入风速为 $v_i^{in}$，额定风速为 $v_i^{rated}$，切出风速为 $v_i^{out}$。单台风机第 $t$ 小时最大可发功率为：

$$
\overline{p}_{w,i,t}
=
\begin{cases}
0, & v_t < v_i^{in} \\
S_i^W\dfrac{v_t-v_i^{in}}{v_i^{rated}-v_i^{in}}, & v_i^{in}\leq v_t < v_i^{rated} \\
S_i^W, & v_i^{rated}\leq v_t \leq v_i^{out} \\
0, & v_t > v_i^{out}
\end{cases}
$$

第 $i$ 行风机总最大可发功率为：

$$
\overline{P}_{w,i,t}
=
q_i^W \overline{p}_{w,i,t}
$$

全系统风机最大可发功率为：

$$
\overline{P}_{w,t}
=
\sum_{i\in\mathcal{W}}
q_i^W \overline{p}_{w,i,t}
$$

输出曲线中的“风力最大可发”即为 $\overline{P}_{w,t}$。

# 光伏最大可发功率

光伏最大可发功率按容量和太阳辐射计算。根据当前业务约定，光伏发电效率参数已删除，最大可发公式为：

$$
\overline{p}_{pv,i,t}
=
S_i^{PV}\frac{r_t}{1000}
$$

其中 $S_i^{PV}$ 为第 $i$ 行光伏单台容量，$r_t$ 为第 $t$ 小时太阳辐射，单位为 W/m²。第 $i$ 行光伏总最大可发功率为：

$$
\overline{P}_{pv,i,t}
=
q_i^{PV}\overline{p}_{pv,i,t}
$$

全系统光伏最大可发功率为：

$$
\overline{P}_{pv,t}
=
\sum_{i\in\mathcal{P}}
q_i^{PV}\overline{p}_{pv,i,t}
$$

新能源最大可发功率为：

$$
\overline{P}_{ren,t}
=
\overline{P}_{w,t}
+\overline{P}_{pv,t}
$$

# 风光统一弃电率与线性化

为了减少多解并使弃风、弃光具有一致解释，模型在同一小时使用统一的新能源弃电率。记该弃电率为 $\alpha_t$：

$$
0\leq \alpha_t\leq 1
$$

实际风电出力和弃风功率满足：

$$
C_{w,t}
=
\alpha_t\overline{P}_{w,t}
$$

$$
P_{w,t}
=
\left(1-\alpha_t\right)\overline{P}_{w,t}
$$

实际光伏出力和弃光功率满足：

$$
C_{pv,t}
=
\alpha_t\overline{P}_{pv,t}
$$

$$
P_{pv,t}
=
\left(1-\alpha_t\right)\overline{P}_{pv,t}
$$

由于 $\overline{P}_{w,t}$ 和 $\overline{P}_{pv,t}$ 中含有建设台数变量，$\alpha_t q_i$ 会形成双线性项。模型通过 McCormick 包络对乘积变量 $m_{i,t}=\alpha_t q_i$ 进行线性化。若 $q_i\in[0,\overline{q}_i]$ 且 $\alpha_t\in[0,1]$，则：

$$
m_{i,t}\geq 0
$$

$$
m_{i,t}\leq q_i
$$

$$
m_{i,t}\leq \overline{q}_i\alpha_t
$$

$$
m_{i,t}\geq q_i-\overline{q}_i(1-\alpha_t)
$$

借助该变量，弃电功率可表示为线性形式：

$$
C_{w,t}
=
\sum_{i\in\mathcal{W}}
\overline{p}_{w,i,t}m_{w,i,t}
$$

$$
C_{pv,t}
=
\sum_{i\in\mathcal{P}}
\overline{p}_{pv,i,t}m_{pv,i,t}
$$

# 柴油发电机约束

柴油发电机采用行级开机台数变量。第 $i$ 行柴油发电机在第 $t$ 小时的开机台数必须小于等于建设台数：

$$
0\leq n_{g,i,t}\leq q_i^G
$$

若单台出力下限和上限分别为 $\underline{P}_{g,i}$ 和 $\overline{P}_{g,i}$，则该行总出力满足：

$$
\underline{P}_{g,i} n_{g,i,t}
\leq
P_{g,i,t}
\leq
\overline{P}_{g,i} n_{g,i,t}
$$

柴油发电总功率为：

$$
P_{g,t}
=
\sum_{i\in\mathcal{G}}P_{g,i,t}
$$

柴油发电总容量为：

$$
S_G
=
\sum_{i\in\mathcal{G}}
\overline{P}_{g,i} q_i^G
$$

该容量既用于容量构成展示，也用于电网向上调节能力计算。由于柴油机有开机台数约束，单小时内不是所有已建设容量都一定可以用于实际出力，只有开机机组才参与运行上下限。

# 电制氢约束

电制氢同样使用行级开机台数变量。第 $i$ 行电制氢在第 $t$ 小时的开机台数满足：

$$
0\leq n_{el,i,t}\leq q_i^{EL}
$$

若单台制氢功率下限和上限分别为 $\underline{P}_{el,i}$ 和 $\overline{P}_{el,i}$，则总制氢功率满足：

$$
\underline{P}_{el,i} n_{el,i,t}
\leq
P_{el,i,t}
\leq
\overline{P}_{el,i} n_{el,i,t}
$$

电制氢消耗电功率进入电力平衡的用电侧。制氢产生的氢气量为：

$$
Q_{el,t}
=
\sum_{i\in\mathcal{E}}
\eta_{el,i}P_{el,i,t}\Delta t
$$

其中 $\eta_{el,i}$ 为电-氢效率，单位为 Nm³/kWh。若出现大量新能源弃电但制氢功率仍为 0，常见原因包括电制氢未建设、电制氢功率下限导致无法小功率运行、储氢罐已满、期末氢储平衡限制、燃料电池效率不足导致制氢再发电不能降低目标函数、或其他电力平衡和扰动安全约束更紧。

# 储能 PCS 与充放电互斥

储能 PCS 决定系统电储能的充放电功率上限。模型使用两个非负连续变量表示充电功率和放电功率：

$$
P_{ch,t}\geq 0,\quad P_{dis,t}\geq 0
$$

充电和放电不能同时发生，因此引入二进制变量：

$$
u_{ch,t}+u_{dis,t}\leq 1
$$

储能 PCS 总容量为：

$$
S_{PCS}
=
\sum_{i\in\mathcal{S}}
S_i^{PCS} q_i^{PCS}
$$

充电功率和放电功率均受 PCS 容量限制：

$$
P_{ch,t}\leq S_{PCS}u_{ch,t}
$$

$$
P_{dis,t}\leq S_{PCS}u_{dis,t}
$$

PCS 的充电效率和放电效率从储能 PCS 参数表读取，分别记为 $\eta_{ch}$ 和 $\eta_{dis}$。它们用于电池 SOC 动态方程。

# 电储能 SOC 约束

电池组决定系统电储能容量。总电池容量为：

$$
E_{BAT}^{max}
=
\sum_{i\in\mathcal{B}}
S_i^{BAT}q_i^{BAT}
$$

SOC 上下限来自储能电池参数：

$$
\mathrm{SOC}^{min}E_{BAT}^{max}
\leq
E_{bat,t}
\leq
\mathrm{SOC}^{max}E_{BAT}^{max}
$$

若电池自损耗率为 $\lambda_{bat}$，以每天为单位输入，则小时保持系数可近似写为：

$$
\gamma_{bat}
=
1-\frac{\lambda_{bat}}{24}
$$

电储能动态方程为：

$$
E_{bat,t}
=
\gamma_{bat}E_{bat,t-1}
+\eta_{ch}P_{ch,t}\Delta t
-\frac{1}{\eta_{dis}}P_{dis,t}\Delta t
$$

首小时的初始电量由规划参数中的初始电储 SOC 给出：

$$
E_{bat,0}
=
\mathrm{SOC}_{bat}^{0}E_{BAT}^{max}
$$

模型还要求每天起始和次日起始电储能容量一致，用于避免日间能量透支：

$$
E_{bat,24d}
=
E_{bat,24(d-1)}
,\quad d=1,2,\ldots,365
$$

当电池电量低于下限时不能放电，当电池电量高于上限时不能充电。实现上通过 SOC 阈值指示变量近似表达该逻辑，从而保持 MILP 形式。

# 储氢与燃料电池约束

储氢罐总容量为：

$$
H^{max}
=
\sum_{i\in\mathcal{H}}
S_i^{HT}q_i^{HT}
$$

储氢量满足：

$$
0\leq H_t\leq H^{max}
$$

若储氢自损耗率为 $\lambda_H$，按每天输入，则小时保持系数为：

$$
\gamma_H
=
1-\frac{\lambda_H}{24}
$$

燃料电池消耗氢气并产生电功率。若第 $i$ 行燃料电池氢-电效率为 $\eta_{fc,i}$，单位为 kWh/Nm³，则氢气消耗量为：

$$
Q_{fc,t}
=
\sum_{i\in\mathcal{F}}
\frac{P_{fc,i,t}\Delta t}{\eta_{fc,i}}
$$

氢储动态方程为：

$$
H_t
=
\gamma_H H_{t-1}
+Q_{el,t}
-Q_{fc,t}
$$

初始氢储量由规划参数中的初始氢储 SOC 给出：

$$
H_0
=
\mathrm{SOC}_{H}^{0}H^{max}
$$

全年期末氢储必须等于初始氢储：

$$
H_{8760}=H_0
$$

这一约束确保模型不能通过消耗初始氢气获得虚假的低柴油结果。若储氢罐有自损耗但没有电制氢能力，且又要求期末等于初始，则模型会不可行，因此快速预检查会提前给出中文错误提示。

# 绿色电量占比约束

绿色电量包括风电、光伏、储能放电和燃料电池发电。年度绿色电量为：

$$
E_{\mathrm{green}}
=
\sum_{t\in\mathcal{T}}
\left(
P_{w,t}+P_{pv,t}+P_{dis,t}
+\sum_{i\in\mathcal{F}}P_{fc,i,t}
\right)\Delta t
$$

柴油发电量为：

$$
E_{\mathrm{diesel}}
=
\sum_{t\in\mathcal{T}}
\sum_{i\in\mathcal{G}}
P_{g,i,t}\Delta t
$$

总发电量为：

$$
E_{\mathrm{total}}
=
E_{\mathrm{green}}
+E_{\mathrm{diesel}}
$$

若绿色电量占比下限为 $\beta_{\mathrm{green}}$，则约束为：

$$
E_{\mathrm{green}}
\geq
\beta_{\mathrm{green}}
E_{\mathrm{total}}
$$

该约束是年度约束，不要求每个小时均满足固定绿电比例。若风机和光伏建设上限均为 0，但绿色电量占比下限大于 0，快速预检查会直接判定不可行。

# 构网储能与在线支撑约束

系统要求每个小时至少有柴油发电机或构网储能在线，以保证电网有基本支撑。设构网储能在线台数为 $n_{gf,i,t}$，柴油开机台数为 $n_{g,i,t}$，则：

$$
\sum_{i\in\mathcal{G}}n_{g,i,t}
+\sum_{i\in\mathcal{S}_{gf}}n_{gf,i,t}
\geq 1
$$

其中 $\mathcal{S}_{gf}$ 是构网型储能 PCS 集合。跟网型 PCS 不参与该在线支撑计数，也不参与电网向上或向下调节能力计算。

构网储能在线台数不能超过建设台数：

$$
0\leq n_{gf,i,t}\leq q_i^{PCS}
$$

若电池电量处于下限附近，构网 PCS 不具备向上调节能力；若电池电量处于上限附近，构网 PCS 不具备向下调节能力。模型通过可用台数变量和 SOC 阈值指示变量近似表达这一逻辑。

# 扰动后平衡约束

当“是否考虑扰动后平衡约束”启用时，模型每个小时增加电网向上、向下调节能力约束。负荷向上扰动功率为：

$$
\Delta P_{L,t}^{up}
=
L_t k_L^{up}
$$

负荷向下扰动功率按负方向输出曲线显示：

$$
\Delta P_{L,t}^{down}
=
-L_t k_L^{down}
$$

新能源向下扰动功率为：

$$
\Delta P_{ren,t}^{down}
=
\left(P_{w,t}+P_{pv,t}\right)k_{ren}^{down}
$$

电网向上调节需求为：

$$
R_t^{up,req}
=
\Delta P_{L,t}^{up}
+\Delta P_{ren,t}^{down}
$$

电网向下调节需求为：

$$
R_t^{down,req}
=
\Delta P_{L,t}^{down}
$$

电网向上调节能力由开机柴发剩余容量和构网型储能剩余放电能力组成：

$$
R_t^{up}
=
\sum_{i\in\mathcal{G}}
\left(\overline{P}_{g,i}n_{g,i,t}-P_{g,i,t}\right)
+
\sum_{i\in\mathcal{S}_{gf}}
\left(S_i^{PCS}n_{gf,i,t}-P_{gf,i,t}\right)
$$

电网向下调节能力按负方向输出，当前业务公式为：

$$
R_t^{down}
=
-\left(
\sum_{i\in\mathcal{G}}P_{g,i,t}
+
\sum_{i\in\mathcal{S}_{gf}}
\left(P_{gf,i,t}+S_i^{PCS}n_{gf,i,t}\right)
\right)
$$

扰动后安全约束为：

$$
R_t^{up}
\geq
R_t^{up,req}
$$

$$
R_t^{down}
\leq
R_t^{down,req}
$$

由于向下能力和向下需求均按负方向展示，工程实现中需要特别注意不等号方向。界面曲线中如果看到向下能力为正，应检查储能构网/跟网状态和符号转换逻辑是否一致。

# 频率安全参数与当前实现边界

规划参数中保留了频率安全相关参数，包括频率安全上下限、频率最低点下限、最高点上限、频率安全裕度、负荷频率系数、RoCoF 上限、稳态频率上下限、Nadir 评估时长、线性化采样点数、网络同步系数等。这些参数用于描述更细粒度的频率动态安全边界。

典型频率动态可抽象为：

$$
2H_{\mathrm{eq}}\frac{d\Delta f(t)}{dt}
=
\Delta P_m(t)
-\Delta P_e(t)
-D_{\mathrm{eq}}\Delta f(t)
$$

RoCoF 约束通常可写为：

$$
\left|
\frac{d\Delta f(0)}{dt}
\right|
\leq
R_{\max}
$$

频率最低点约束为：

$$
f_0+\Delta f_{\min}
\geq
f_{\mathrm{nadir}}^{min}
$$

稳态频率约束为：

$$
f_{\mathrm{ss}}^{min}
\leq
f_0+\Delta f_{\mathrm{ss}}
\leq
f_{\mathrm{ss}}^{max}
$$

当前后台 MILP 的严格频率动态约束仍处于可扩展位置，主要已实现的是与构网储能、柴发开机和扰动后平衡相关的静态安全约束。若要进一步实现完整频率 Nadir 约束，需要把等效惯量、一次调频系数、阻尼系数和网络同步系数纳入线性化或分段线性化模型。

# 快速可行性预检查

正式求解 MILP 前，后台会执行快速可行性预检查，用于识别无需进入求解器即可判定明显不可行的场景。预检查失败时，任务状态应切换为“计算失败”，并把中文错误写入运行日志。

第一类预检查是绿电比例基本可行性。若风机和光伏最大可发电量之和低于绿电比例要求，则不可行：

$$
\frac{
\sum_{t\in\mathcal{T}}
\left(\overline{P}_{w,t}+\overline{P}_{pv,t}\right)\Delta t
}{
\sum_{t\in\mathcal{T}}L_t\Delta t
}
<
\beta_{\mathrm{green}}
$$

第二类预检查是单小时最大供电能力。若某个小时风机、光伏和柴油最大供电功率之和小于负荷，则即使不考虑储能和氢能也已经存在明显供电缺口：

$$
\overline{P}_{w,t}
+\overline{P}_{pv,t}
+\overline{P}_{g,t}
<
L_t
$$

第三类预检查是氢储自损耗可补偿性。若储氢罐下限或当前设计台数大于 0、自损耗率大于 0，但电制氢上限或设计台数为 0，同时模型要求期末氢储等于初始氢储，则不可行：

$$
H^{max}>0,\quad
\lambda_H>0,\quad
q^{EL}=0,\quad
H_{8760}=H_0
\Rightarrow
\mathrm{infeasible}
$$

第四类预检查是电储自损耗可补偿性。若电池容量大于 0、自损耗率大于 0，但储能 PCS 为 0，同时模型要求日末电储等于初始电储，则不可行：

$$
E_{BAT}^{max}>0,\quad
\lambda_{bat}>0,\quad
q^{PCS}=0,\quad
E_{bat,24d}=E_{bat,24(d-1)}
\Rightarrow
\mathrm{infeasible}
$$

预检查只在任务正式开始计算时执行，加入排队时不执行。这样可以避免排队阶段因为数据临时状态导致误报，也保证任务真正启动时使用最新方案和结果文件。

# 求解器接口与算法流程

模型构造完成后，后台将目标函数、变量上下界、变量类型和稀疏约束矩阵传给统一求解器适配器。自动求解顺序为：

$$
\mathrm{Gurobi}
\rightarrow
\mathrm{CPLEX}
\rightarrow
\mathrm{MOSEK}
\rightarrow
\mathrm{SciPy/HiGHS}
$$

求解器适配器的抽象接口可表示为：

$$
\mathrm{solve}
\left(
c,\;l_x,\;u_x,\;\mathcal{I},\;A,\;l_c,\;u_c,\;\tau,\;\epsilon
\right)
$$

其中 $c$ 是目标函数向量，$l_x,u_x$ 是变量上下界，$\mathcal{I}$ 是整数变量集合，$A$ 是稀疏约束矩阵，$l_c,u_c$ 是约束上下界，$\tau$ 是时间上限，$\epsilon$ 是 MIP gap。优化求解时间上限来自规划参数中的“优化求解时间上限(分钟)”。

整体流程为：

1. 读取方案参数、设备参数和时序数据。
2. 对输入数据执行合法性清洗和快速可行性预检查。
3. 构建设备建设变量和小时级运行变量。
4. 写入目标函数系数。
5. 添加电力平衡、风光可发、弃电、柴发、储能、氢能、绿电比例、安全约束。
6. 调用求解器。
7. 解析解向量，计算小时、日、月、年度指标。
8. 写入同名 `xxx_results.xlsx` 文件。

若达到最大求解时间而中止，任务状态应标记为“计算超时”；若预检查失败或优化失败，任务状态应标记为“计算失败”；若用户主动停止，任务状态应标记为“计算中止”。

# 结果曲线与统计指标

小时级输出曲线包括输入数据、发电出力、储能状态、氢能状态、弃电、切负荷和扰动安全相关曲线。典型输出包括：

$$
v_t,\;r_t,\;\theta_t,\;L_t,\;
P_{g,t},\;P_{w,t},\;P_{pv,t},\;P_{ch,t},\;P_{dis,t},\;
E_{bat,t},\;P_{el,t},\;H_t,\;P_{fc,t}
$$

新能源实发功率为：

$$
P_{ren,t}
=
P_{w,t}+P_{pv,t}
$$

新能源弃电总功率为：

$$
C_{ren,t}
=
C_{w,t}+C_{pv,t}
$$

新能源占比小时曲线可按实际供电贡献定义为：

$$
\eta_{ren,t}
=
\frac{P_{ren,t}+P_{dis,t}+P_{fc,t}}
{P_{g,t}+P_{ren,t}+P_{dis,t}+P_{fc,t}+\epsilon}
$$

新能源弃电率为：

$$
\eta_{curt,t}
=
\frac{C_{ren,t}}
{\overline{P}_{ren,t}+\epsilon}
$$

日级和月度统计通过对小时量聚合得到。以日级负荷电量为例：

$$
E_{load,d}
=
\sum_{t\in\mathcal{T}_d}
L_t\Delta t
$$

月度新能源弃电量为：

$$
E_{curt,m}
=
\sum_{t\in\mathcal{T}_m}
C_{ren,t}\Delta t
$$

年度统计指标包括负荷总电量、柴发总电量、风机总电量、光伏总电量、电储充放电量、电制氢用电量、氢储增加量、氢储消耗量、燃料电池发电量、绿色电量占比、新能源弃电率、柴油消耗、年总成本和度电成本。

度电成本前端显示为：

$$
\mathrm{LCOE}
=
\frac{C_{\mathrm{annual}}}{E_{\mathrm{load}}}
$$

其中单位换算由前端显示层处理，后端不为了三位小数显示而归一化原始结果。

# 成本、容量与电量构成

结果概览中使用横向堆叠柱状图展示成本构成、容量构成和电量构成。成本构成按万元显示：

$$
C_{\mathrm{annual}}
=
C_{\mathrm{inv}}
+C_{\mathrm{diesel}}
$$

容量构成按 kW 显示，通常包括柴发、风电、光伏、电储和燃料电池：

$$
S_{\mathrm{cap}}
=
S_G+S_W+S_{PV}+S_{PCS}+S_{FC}
$$

电量构成按万 kWh 显示，前端展示时将 kWh 除以 10000：

$$
\widetilde{E}
=
\frac{E}{10000}
$$

这样处理可以减少图表文字冗余。例如“成本构成(单位: 万元)”后，分量名称不再重复“成本”和“万元”；“电量构成(单位: 万 kWh)”后，分量名称可以简化为柴发、绿电等。

# 文件输出与前端读取

规划求解和方案评估均将结果写入当前方案目录下的 `xxx_results.xlsx` 文件。默认规划结果文件名为 `opt_results.xlsx`。文件中包含规划结果、小时级曲线、日级统计、月度统计和年度统计。前端结果概览、经济性指标、安全性指标、曲线展示和结果对比页面均应优先从该 Excel 文件读取已生成结果，而不是重新计算。

文件写入采用临时文件加原子替换的思路。若目标文件被 Excel 或其他进程占用，Windows 可能返回：

$$
\mathrm{WinError}\;32
$$

此时应提示用户关闭占用文件后重试。系统中的所有文件写操作都应尽量采用相同机制，避免半写入文件破坏结果。

为了提高访问速度，后台已经增加文件缓存机制。缓存的基本原则是：当文件路径、修改时间和大小不变时，可以复用解析结果；当文件变化时，必须重新读取。对于任务并发页面，只需要判断结果文件是否存在时，不应打开并完整解析 `xxx_results.xlsx`。

# 性能优化与变量规模控制

8760 小时 MILP 的变量规模较大，建模方式直接影响求解速度。当前模型已经避免对风机、光伏、储能电池、储氢罐等设备逐台展开 0/1 变量，而是尽量使用行级建设台数和行级开机台数。这样可以显著减少二进制变量数量。

若某类设备有 $N$ 行，时间点数为 $T$，逐台建模的二进制变量规模可能达到：

$$
O\left(T\sum_{i=1}^{N}\overline{q}_i\right)
$$

行级台数建模的整数变量规模则约为：

$$
O(TN)
$$

当候选设备上限较大时，两者差异非常明显。储能充放电互斥仍保留每小时二进制变量，因为该互斥关系是系统级状态，变量规模仅为：

$$
2T
$$

此外，前端也采用延迟加载和缓存策略。小时级曲线数据量最大，因此在页面初始化时应避免阻塞其他表格和统计信息刷新；但也不应等用户点击曲线名称时才临时读取，较好的方式是后台空闲时预取并缓存。

# 模型局限与后续扩展

当前模型以年尺度能量经济性和小时级运行可行为主，已经覆盖风、光、柴、电储、制氢、储氢和燃料电池的主要线性运行约束。仍需注意以下边界：

1. 柴发启停目前以开机台数表达，未完整加入最小开停机时间、爬坡率和启动成本。
2. 风机功率曲线采用分段线性近似，未纳入空气密度修正和复杂机型曲线。
3. 光伏最大可发按容量和太阳辐射线性计算，未纳入组件温度修正。
4. 频率安全参数已经在前端和数据结构中维护，但完整动态 Nadir 线性化仍属于扩展项。
5. 储能和氢能采用聚合模型，不区分每台设备的个体 SOC。

后续如果需要提高动态安全精度，可以引入分段线性频率响应模型：

$$
\Delta f_{\min}
\approx
\sum_{k=1}^{K}
\lambda_k \phi_k(H_{\mathrm{eq}},K_{\mathrm{eq}},D_{\mathrm{eq}},\Delta P)
$$

并增加凸组合约束：

$$
\sum_{k=1}^{K}\lambda_k=1,\quad
\lambda_k\geq 0
$$

这样可以在保持 MILP 或混合整数线性近似结构的同时，更准确地约束频率最低点和稳态频率。

# 附录 A：主要符号表

| 符号 | 含义 | 单位 |
| --- | --- | --- |
| $L_t$ | 第 $t$ 小时负荷功率 | kW |
| $v_t$ | 第 $t$ 小时风速 | m/s |
| $r_t$ | 第 $t$ 小时太阳辐射 | W/m² |
| $q_i$ | 第 $i$ 行设备建设台数 | 台 |
| $P_{g,i,t}$ | 第 $i$ 行柴发第 $t$ 小时出力 | kW |
| $P_{w,t}$ | 风机总实际出力 | kW |
| $P_{pv,t}$ | 光伏总实际出力 | kW |
| $C_{w,t}$ | 弃风功率 | kW |
| $C_{pv,t}$ | 弃光功率 | kW |
| $P_{ch,t}$ | 电储能充电功率 | kW |
| $P_{dis,t}$ | 电储能放电功率 | kW |
| $E_{bat,t}$ | 电储能电量 | kWh |
| $P_{el,t}$ | 电制氢总功率 | kW |
| $H_t$ | 储氢罐氢储量 | Nm³ |
| $P_{fc,t}$ | 燃料电池总功率 | kW |
| $P_{shed,t}$ | 切负荷功率 | kW |
| $\alpha_t$ | 风光统一弃电率 | - |
| $\beta_{\mathrm{green}}$ | 绿色电量占比下限 | - |

# 附录 B：公式索引

表 2 汇总本文常用公式与所在主题，便于维护人员定位。

| 公式主题 | 主要表达 |
| --- | --- |
| 规划主问题 | $\min J,\; Ax\leq b,\; y\in\mathbb{Z}$ |
| 设备台数约束 | $\underline{q}_i\leq q_i\leq\overline{q}_i$ |
| 评估固定台数 | $q_i=\hat{q}_i$ |
| 年均建设成本 | $C_{\mathrm{inv}}=\sum c_iq_i/Y_i$ |
| 柴油成本 | $C_{\mathrm{diesel}}=\pi_{\mathrm{diesel}}M_{\mathrm{diesel}}$ |
| 电力平衡 | 供电侧 + 切负荷 = 负荷 + 充电 + 制氢 |
| 风机最大可发 | 分段风速功率曲线 |
| 光伏最大可发 | $\overline{p}_{pv}=S^{PV}r/1000$ |
| 统一弃电率 | $C_w=\alpha\overline{P}_w,\; C_{pv}=\alpha\overline{P}_{pv}$ |
| 柴发上下限 | $\underline{P}n\leq P\leq\overline{P}n$ |
| 储能互斥 | $u_{ch}+u_{dis}\leq 1$ |
| 电储 SOC | $E_t=\gamma E_{t-1}+\eta_{ch}P_{ch}-P_{dis}/\eta_{dis}$ |
| 氢储动态 | $H_t=\gamma_HH_{t-1}+Q_{el}-Q_{fc}$ |
| 绿电比例 | $E_{green}\geq\beta E_{total}$ |
| 扰动上调 | $R^{up}\geq R^{up,req}$ |
| 扰动下调 | $R^{down}\leq R^{down,req}$ |

"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    make_reference_docx()
    SRC.write_text(markdown(), encoding="utf-8")
    print(SRC)
    print(REFERENCE)


if __name__ == "__main__":
    main()
