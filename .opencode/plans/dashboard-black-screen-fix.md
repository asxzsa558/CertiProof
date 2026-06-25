# Dashboard 黑屏问题诊断与修复计划

## 问题描述
用户反馈：刷新后 Dashboard 页面显示为黑屏

## 可能的原因

### 1. Three.js 渲染失败（最可能）
- WebGL 上下文创建失败
- three.js 版本不兼容
- Canvas 初始化错误
- 浏览器不支持 WebGL

### 2. JavaScript 运行时错误
- 3D 组件抛出异常
- 没有错误边界（Error Boundary）捕获异常
- 整个 React 应用崩溃

### 3. CSS 层级问题
- Canvas 遮挡了内容层
- z-index 设置不当
- Canvas 背景色为黑色

### 4. 资源加载问题
- 3D 组件依赖未正确加载
- 字体加载失败
- 图片资源缺失

## 诊断步骤

### 步骤 1：检查浏览器控制台
打开浏览器开发者工具（F12），查看 Console 标签页：
- 是否有红色错误信息？
- 是否有 "WebGL not supported" 错误？
- 是否有 "Cannot read property 'xxx' of undefined" 错误？

### 步骤 2：检查 WebGL 支持
在浏览器控制台运行：
```javascript
const canvas = document.createElement('canvas');
const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
console.log('WebGL supported:', !!gl);
```

### 步骤 3：检查网络请求
查看 Network 标签页：
- three.js 相关文件是否正确加载？
- 是否有 404 错误？
- 是否有加载超时的资源？

### 步骤 4：临时禁用 3D 组件
在 Dashboard.jsx 中注释掉 3D 组件，看页面是否恢复正常：
```javascript
// 临时注释
// <HolographicBackground />
// <HolographicGlobe />
// <DataFlow />
```

## 修复方案

### 方案 A：添加错误边界（推荐）
创建 ErrorBoundary 组件，捕获 3D 组件的错误，显示降级版本。

**优点：**
- 即使 3D 渲染失败，页面仍能正常显示
- 可以显示友好的错误提示
- 不影响其他功能

**实现：**
```javascript
class DashboardErrorBoundary extends React.Component {
  state = { hasError: false };
  
  static getDerivedStateFromError(error) {
    return { hasError: true };
  }
  
  componentDidCatch(error, errorInfo) {
    console.error('Dashboard error:', error, errorInfo);
  }
  
  render() {
    if (this.state.hasError) {
      return <div>3D 渲染失败，显示降级版本</div>;
    }
    return this.props.children;
  }
}
```

### 方案 B：检测 WebGL 支持
在渲染 3D 组件前检测 WebGL 支持，不支持则显示 2D 版本。

**优点：**
- 主动检测，避免错误
- 可以针对不同浏览器提供不同体验

**实现：**
```javascript
const isWebGLSupported = () => {
  try {
    const canvas = document.createElement('canvas');
    return !!(
      window.WebGLRenderingContext && 
      (canvas.getContext('webgl') || canvas.getContext('experimental-webgl'))
    );
  } catch (e) {
    return false;
  }
};

// 在 Dashboard 中使用
{isWebGLSupported() ? <HolographicBackground /> : <FallbackBackground />}
```

### 方案 C：懒加载 3D 组件
使用 React.lazy 和 Suspense 懒加载 3D 组件，减少初始加载时间。

**优点：**
- 减少初始 bundle 大小
- 3D 组件加载失败不影响主页面
- 可以显示加载状态

**实现：**
```javascript
const HolographicBackground = lazy(() => import('../components/HolographicBackground'));

<Suspense fallback={<div>加载中...</div>}>
  <HolographicBackground />
</Suspense>
```

### 方案 D：简化 3D 效果
如果 3D 渲染确实有问题，可以简化为 2D 动画效果。

**优点：**
- 兼容性更好
- 性能更好
- 减少依赖

**实现：**
- 使用 CSS 动画代替 Three.js
- 使用 Canvas 2D API 代替 WebGL
- 使用 SVG 动画

## 推荐修复顺序

1. **立即修复**：添加错误边界（方案 A）
   - 确保页面不会因 3D 错误而崩溃
   - 提供降级体验

2. **短期优化**：检测 WebGL 支持（方案 B）
   - 主动检测，避免错误
   - 提供更好的用户体验

3. **中期优化**：懒加载 3D 组件（方案 C）
   - 减少初始加载时间
   - 提高页面性能

4. **长期优化**：考虑简化 3D 效果（方案 D）
   - 如果 3D 效果不是核心功能，可以考虑简化
   - 使用更轻量的动画方案

## 立即行动

### 1. 检查浏览器控制台
请先打开浏览器控制台（F12），查看是否有错误信息，并告诉我：
- 是否有红色错误？
- 错误信息是什么？
- 是否有 "WebGL" 相关的错误？

### 2. 测试 WebGL 支持
在浏览器控制台运行以下代码，告诉我结果：
```javascript
const canvas = document.createElement('canvas');
const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
console.log('WebGL supported:', !!gl);
console.log('WebGL renderer:', gl ? gl.getParameter(gl.RENDERER) : 'N/A');
```

### 3. 临时禁用 3D 组件
如果确认是 3D 组件的问题，我可以立即添加错误边界，确保页面正常显示。

## 预期结果

修复后：
- ✅ 即使 3D 渲染失败，页面仍能正常显示
- ✅ 显示友好的错误提示或降级版本
- ✅ 不影响其他功能（统计面板、图表、项目列表等）
- ✅ 提供更好的用户体验
