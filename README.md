# 🧩 STL Part Editor

浏览器端的 STL 内部零件剔除器。把 CAD 直出的 STL 拆成连通体，自动判断哪些零件「从外面根本看不见」（电机、轴承、螺丝、内部支架），一键剔除；判断不准的地方，点一下就能手动改。

面向仿真/渲染场景：机器人 URDF 的 visual / collision mesh 常常带着整套内部装配，面数是外壳的三五倍，删掉它们外观分毫不差，但网格能瘦一半以上。

**在线体验：** [https://tony1213.github.io/stl-part-editor/](https://tony1213.github.io/stl-part-editor/)

零依赖单文件——不联网、不上传，STL 全在本机内存里处理。把 `index.html` 存到本地双击也一样能用。

## 截图

<table>
<tr>
<td align="center"><img src="screenshots/overview.png" width="480"/><br><b>自动判定</b>（红色 = 从外面看不见，待删）</td>
<td align="center"><img src="screenshots/xray.png" width="480"/><br><b>穿透显示选中件</b>（蓝色是被壳体挡住的部分，<b>橙色是它露在外面的面</b>）</td>
</tr>
<tr>
<td align="center"><img src="screenshots/expose.png" width="480"/><br><b>外露高亮</b>（一眼看出删掉这批零件后，外表面哪里会缺）</td>
<td align="center"><img src="screenshots/result.png" width="480"/><br><b>剔除后</b>（10.7 万面 → 4.2 万面，外形一模一样）</td>
</tr>
</table>

## 它怎么判断「内部零件」

1. **焊接顶点 → 拆连通体。** 只沿「恰好被两个面共用」的边连通。CAD 里贴合的零件会共用非流形边（一条边挂 3 个以上的面），那种边不算连通，否则电机会和外壳并成一坨。
2. **算可见率。** 从球面上 64 个均匀方向做正交射线扫描（GPU，320×320 的 id buffer），只统计每根射线打到的**第一个**三角形——这就是「从外面看得见」的面。一个连通体里可见面的占比 = 它的可见率。
3. **低于阈值的整块删掉。** 几何本身一个三角形都不改：导出的 STL 是原文件三角形的**精确子集**，不做简化、不重网格、不做任何变换，包围盒不变。

默认阈值 5%：完全藏在壳体里的零件是 0~2%，外壳/盖板是 40%~75%，中间那一段（能从散热孔、走线孔里露出一点的）才需要人眼定夺——所以有了手动模式。

## 功能

### 自动
- 拖放或选择 STL（二进制 / ASCII 都支持）
- 连通体拆分 + 可见率计算，10 万面约 3 秒
- 阈值滑条 0~40% 实时重算，右侧列表按面数排序，列出每个零件的面数 / 可见率 / 状态
- 小于 100 面的碎片（CAD 导出的零面积三角形）一律保留，不参与判定

### 看得见才好判断
内部零件被壳体挡着，选中了也看不见——所以有这三样：

- **穿透显示选中件**（<kbd>X</kbd>）：选中的零件透过外壳画出来，位置、形状、朝向一目了然
- **橙色 = 这一面从外面看得见**：选中件上直接标出它露出来的那些面，配合页脚的「露出 N 面」，
  「这零件到底能不能删」不用猜——全蓝就是全藏着，橙色成片就是删了会在外表面留豁口
- **外露高亮**（<kbd>E</kbd>）：把当前所有待删零件的外露面一起标橙，一眼扫出整体影响
- **选中即聚焦**：点列表里的零件，相机自动飞过去把它摆在画面中央

### 手动
- 在模型上**点一下**选中零件，3D 高亮 + 列表自动滚到对应行
- **Shift+点** 或**双击**切换保留/删除，列表里双击同样有效
- 手动改过的零件打 ✋ 标记，页脚显示改动数量，`重置手动改动` 一键回到纯阈值判定
- `只看选中`（<kbd>I</kbd>）单独看一个零件，确认它到底是什么
- `显示被删零件`（<kbd>H</kbd>）切换红色件的显示；<kbd>F</kbd> 重新聚焦当前选中件
- `全保留` / `全删除` / `按阈值重算`
- <kbd>Delete</kbd> 删除当前选中零件

### 视图
- 左键拖动旋转，滚轮缩放，右键拖动平移
- 灰色 = 保留，红色 = 待删，蓝色 = 选中（穿透显示），橙色 = 从外面看得见的面
- 跟随系统亮色/暗色主题

### 导出
- 二进制 STL，文件名自动加 `_ML` 后缀
- 只写保留下来的三角形，法线沿用原文件

## 使用方法

### 在线使用

打开 [https://tony1213.github.io/stl-part-editor/](https://tony1213.github.io/stl-part-editor/)，把 STL 拖进去。

### 本地使用

```bash
git clone https://github.com/tony1213/stl-part-editor.git
cd stl-part-editor
xdg-open index.html      # 或者直接双击；macOS 用 open index.html
```

没有构建步骤，没有依赖，`index.html` 就是全部。

### 批量处理（命令行）

网页版适合逐个确认、手动修正。整个机器人几十个 mesh 时用 `cli/vis_split.py` 跑批——同一套判据的 Python 实现（trimesh + Embree），连通体拆分规则、可见率算法、100 面碎片规则与网页版完全一致，两边结果可以互相替换。

```bash
pip install -r cli/requirements.txt

python cli/vis_split.py <目录或文件>            # 默认阈值 0.05，输出同目录、文件名加 _ML
python cli/vis_split.py meshes/ --thresh 0.15 -o meshes_ml015/
python cli/vis_split.py part.STL --report       # 打印每个连通体的面数/可见率/判定
python cli/vis_split.py meshes/ --dry-run       # 只统计不写文件
```

跑完会给一张汇总表（每个文件的面数变化、删了几个零件），并单独列出**可见率落在阈值附近的零件**——那些就是需要拖进网页版人工过一眼的。

## 技术栈

- 原生 WebGL2（无 three.js，无框架，无构建工具）
- STL 解析 / 顶点焊接 / 并查集连通体 / 可见率扫描 / STL 导出全部手写
- 命令行版：Python + trimesh + Embree（`cli/`，判据与网页版一致）
- 部署：GitHub Pages（GitHub Actions 直接发布仓库根目录）

## 已知限制

- 需要 WebGL2（Chrome / Edge / Firefox 新版本均支持）
- 判据只看「从外面看不见」。如果一个零件从散热孔能露出一点点（可见率 5%~15%），自动判定会拿不准，需要人工过一眼——这正是手动模式存在的理由
- 浏览器只能往下载目录写文件，导出后需自行移动到目标位置
- 可见率用 320×320 的扫描网格，特别细小的外露特征（<0.3mm）可能采样不到

## 技术支持

如有问题或建议，欢迎通过邮件联系：[tony10012.tc@gmail.com](mailto:tony10012.tc@gmail.com)

© 2026 Dong.Wu All Rights Reserved

## License

MIT
