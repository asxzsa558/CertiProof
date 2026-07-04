# 修复工具结果显示问题

## 问题描述
所有工具都显示为"端口扫描"，无法区分工具类型和状态。

## 根本原因
`renderResultMessage` 函数没有从 `scanResults.asset_results` 中提取正确的工具类型和状态信息。

## 修改文件
`frontend/src/components/ChatWorkspace.jsx`

## 修改内容

### 1. 修改 `renderResultMessage` 函数（第1249行开始）

**当前代码：**
```javascript
const tool = msg.tool || 'scan_ports'
const status = weakPasswords.length > 0 ? 'warning' : 
               vulnerabilities.length > 0 || webVulnerabilities.length > 0 ? 'warning' :
               'success'
```

**修改为：**
```javascript
// 从 asset_results 提取工具类型和状态
const assetResults = scanResults.asset_results || {}
const firstAsset = Object.values(assetResults)[0]
const tool = firstAsset?.capability || 'scan_ports'
const status = firstAsset?.status === 'failed' ? 'failed' :
               firstAsset?.display_status || 'success'
const error = firstAsset?.error
```

### 2. 添加错误信息显示

在 `details` 部分添加错误信息展示：

```javascript
{error && (
  <div className="result-details-section error-section">
    <div className="section-title danger">
      <ExclamationCircleFilled style={{ marginRight: 8 }} />
      错误信息
    </div>
    <div className="error-message">{error}</div>
  </div>
)}
```

### 3. 添加错误样式

在 `ToolResultCard.css` 中添加：

```css
.error-section {
  border-left: 3px solid #ef4444;
  background: rgba(239, 68, 68, 0.05);
}

.error-message {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  color: #ef4444;
  padding: 8px 12px;
  background: rgba(0, 0, 0, 0.2);
  border-radius: 4px;
  word-break: break-word;
}
```

## 实施步骤

1. 修改 `ChatWorkspace.jsx` 的 `renderResultMessage` 函数
2. 添加错误信息展示逻辑
3. 在 `ToolResultCard.css` 添加错误样式
4. 重新构建前端：`npm run build`
5. 重新构建 Docker：`docker-compose build frontend`
6. 重启容器：`docker-compose up -d frontend`

## 测试计划

### 测试用例

1. **端口扫描**
   - 输入：`扫描 121.40.95.31 端口`
   - 预期：显示"端口扫描"工具，状态为"成功"或"警告"

2. **弱口令检测**
   - 输入：`检测 121.40.95.31 弱口令`
   - 预期：显示"弱口令检测"工具，状态为"成功"

3. **Nikto 扫描**
   - 输入：`扫描 121.40.95.31 Web漏洞`
   - 预期：显示"Web漏洞扫描"工具，状态为"成功"

4. **SSL 检测**
   - 输入：`检测 121.40.95.31 SSL`
   - 预期：显示"SSL/TLS检测"工具，状态为"成功"

5. **错误场景**
   - 输入：`扫描 无效IP 端口`
   - 预期：显示"端口扫描"工具，状态为"失败"，显示错误信息

### 验证点

- [ ] 工具类型正确显示
- [ ] 状态标签正确（成功/警告/失败）
- [ ] 错误信息内联显示
- [ ] 摘要统计正确
- [ ] 详情可展开/收起
- [ ] 复制功能正常

## 回滚方案

如果出现问题，可以回滚到上一个版本：
```bash
git checkout HEAD~1 frontend/src/components/ChatWorkspace.jsx
npm run build
docker-compose build frontend
docker-compose up -d frontend
```
