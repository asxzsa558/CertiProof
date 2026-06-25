# Dashboard UI 优化计划 - 背景 Logo + 风险态势面板

## Context

当前 Dashboard 存在两个问题：
1. **背景缺少品牌标识**：电影中的特工界面（CIA/NSA）都有一个巨大的背景 Logo，当前实现只有粒子和数据流，缺少这个标志性元素
2. **右侧 3D 地球无实际价值**：占用了 400px 空间但没有展示有意义的信息，应该替换为风险态势面板

## 改动 1：背景大 Logo 水印

### 目标
在 3D 全息背景中心添加一个巨大的 VeriSure Logo，类似电影中 CIA 的大徽章效果。

### 实现方案（CSS 方式）

**修改文件**：`frontend/src/pages/Dashboard.jsx`

在背景层（`dash-root` 内）添加：
```jsx
{/* 品牌水印层 */}
<div className="dash-bg-watermark">
  <VeriSureLogo size={600} />
</div>
```

**修改文件**：`frontend/src/pages/Dashboard.css`

添加样式：
```css
.dash-bg-watermark {
  position: fixed;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  opacity: 0.03;
  pointer-events: none;
  z-index: 0;
  filter: blur(0.5px);
}

.dash-bg-watermark .logo-container {
  width: 600px !important;
  height: 600px !important;
}
```

### 效果
- 巨大的 VeriSure 硬币 Logo 作为背景水印
- 极低透明度（3%），若隐若现
- 与粒子、网格、数据流动画叠加，形成层次感

---

## 改动 2：右侧面板改为风险态势面板

### 目标
移除 3D 地球，替换为风险态势面板，展示：
1. 漏洞严重等级分布（柱状图）
2. 失分条款 TOP 5 列表

### 数据来源

Dashboard API 已返回 `risk` 数据：
```json
{
  "risk": {
    "critical": 2,
    "high": 5,
    "medium": 12,
    "low": 8,
    "info": 3,
    "open": 15,
    "in_progress": 8,
    "resolved": 7,
    "top_clauses": [
      {"clause_id": "8.1.3.1", "name": "边界访问控制", "count": 5},
      ...
    ]
  }
}
```

### 实现方案

**修改文件**：`frontend/src/pages/Dashboard.jsx`

1. 移除 `HolographicGlobe` 导入和使用
2. 添加 `BarChart`, `Bar` 从 `recharts` 导入
3. 替换右侧面板内容：

```jsx
{/* 右侧：风险态势面板 */}
<div className="dash-right-panel">
  <HolographicCard className="dash-risk-panel">
    <div className="dash-risk-header">
      <span className="dash-risk-title">RISK POSTURE</span>
      <span className="dash-risk-sub">风险态势</span>
    </div>
    
    {/* 严重等级分布柱状图 */}
    <div className="dash-risk-chart">
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={riskBarData} layout="vertical">
          <XAxis type="number" hide />
          <YAxis 
            type="category" 
            dataKey="name" 
            tick={{ fill: 'rgba(255,255,255,0.7)', fontSize: 12 }}
            width={50}
          />
          <Bar dataKey="value" fill="#00ff88" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
    
    {/* 处理状态 */}
    <div className="dash-risk-status">
      <div className="dash-risk-status-item">
        <span className="dash-risk-dot" style={{ background: '#ff4d4f' }} />
        <span>待处理</span>
        <strong>{data?.risk?.open ?? 0}</strong>
      </div>
      <div className="dash-risk-status-item">
        <span className="dash-risk-dot" style={{ background: '#faad14' }} />
        <span>进行中</span>
        <strong>{data?.risk?.in_progress ?? 0}</strong>
      </div>
      <div className="dash-risk-status-item">
        <span className="dash-risk-dot" style={{ background: '#52c41a' }} />
        <span>已解决</span>
        <strong>{data?.risk?.resolved ?? 0}</strong>
      </div>
    </div>
    
    {/* 失分条款 TOP 5 */}
    <div className="dash-risk-top">
      <div className="dash-risk-top-title">TOP FAILING CLAUSES</div>
      {data?.risk?.top_clauses?.slice(0, 5).map((clause, i) => (
        <div key={clause.clause_id} className="dash-risk-top-item">
          <span className="dash-risk-top-rank">{i + 1}</span>
          <span className="dash-risk-top-id">{clause.clause_id}</span>
          <span className="dash-risk-top-name">{clause.name}</span>
          <span className="dash-risk-top-count">{clause.count}</span>
        </div>
      ))}
    </div>
  </HolographicCard>
</div>
```

**修改文件**：`frontend/src/pages/Dashboard.css`

添加风险面板样式：
```css
.dash-risk-panel {
  padding: 0;
  overflow: hidden;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.dash-risk-header {
  padding: 20px 24px;
  border-bottom: 1px solid rgba(0, 255, 136, 0.1);
}

.dash-risk-title {
  font-size: 14px;
  font-weight: 700;
  color: #ff6b35;
  letter-spacing: 2px;
  font-family: 'JetBrains Mono', monospace;
  display: block;
}

.dash-risk-sub {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.5);
  letter-spacing: 1px;
}

.dash-risk-chart {
  padding: 16px 24px;
  border-bottom: 1px solid rgba(0, 255, 136, 0.1);
}

.dash-risk-status {
  padding: 16px 24px;
  display: flex;
  justify-content: space-around;
  border-bottom: 1px solid rgba(0, 255, 136, 0.1);
}

.dash-risk-status-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.7);
}

.dash-risk-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.dash-risk-status-item strong {
  font-size: 18px;
  color: #fff;
  font-family: 'JetBrains Mono', monospace;
}

.dash-risk-top {
  padding: 16px 24px;
  flex: 1;
}

.dash-risk-top-title {
  font-size: 10px;
  color: rgba(255, 255, 255, 0.5);
  letter-spacing: 2px;
  font-family: 'JetBrains Mono', monospace;
  margin-bottom: 12px;
}

.dash-risk-top-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.dash-risk-top-rank {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 77, 79, 0.2);
  color: #ff4d4f;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
}

.dash-risk-top-id {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.5);
  font-family: 'JetBrains Mono', monospace;
}

.dash-risk-top-name {
  flex: 1;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.8);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dash-risk-top-count {
  font-size: 14px;
  font-weight: 700;
  color: #ff4d4f;
  font-family: 'JetBrains Mono', monospace;
}
```

### 数据准备

在 Dashboard 组件中添加：
```jsx
const riskBarData = data ? [
  { name: '严重', value: data.risk.critical, fill: '#ff4d4f' },
  { name: '高危', value: data.risk.high, fill: '#fa8c16' },
  { name: '中危', value: data.risk.medium, fill: '#fadb14' },
  { name: '低危', value: data.risk.low, fill: '#52c41a' },
  { name: '信息', value: data.risk.info, fill: '#1890ff' },
] : []
```

---

## 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `frontend/src/pages/Dashboard.jsx` | 修改 | 添加背景水印，移除地球，添加风险面板 |
| `frontend/src/pages/Dashboard.css` | 修改 | 添加水印样式和风险面板样式 |

---

## 验证方案

1. **背景水印**：
   - 刷新页面，应能看到巨大的 VeriSure Logo 水印在背景中
   - 透明度很低，若隐若现，不影响内容阅读

2. **风险态势面板**：
   - 右侧显示风险态势面板（替代原来的 3D 地球）
   - 柱状图显示漏洞严重等级分布
   - 显示待处理/进行中/已解决的数量
   - 显示失分条款 TOP 5 列表

3. **响应式**：
   - 大屏：左右分栏布局保持
   - 中屏（<1400px）：右侧面板移到下方
   - 小屏（<960px）：单列布局

---

## 实施顺序

1. 修改 `Dashboard.jsx`：添加背景水印
2. 修改 `Dashboard.css`：添加水印样式
3. 修改 `Dashboard.jsx`：移除地球，添加风险面板
4. 修改 `Dashboard.css`：添加风险面板样式
5. 重新构建并测试
