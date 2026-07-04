import { useEffect, useRef } from 'react'

export default function DataFlow({ enabled = true }) {
  const canvasRef = useRef(null)
  const animationRef = useRef(null)

  useEffect(() => {
    if (!enabled) return
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    // 设置 canvas 尺寸
    const resize = () => {
      canvas.width = window.innerWidth
      canvas.height = window.innerHeight
    }
    resize()
    window.addEventListener('resize', resize)

    // 数据流列
    const columns = Math.floor(canvas.width / 20)
    const drops = Array(columns).fill(0).map(() => Math.random() * -100)
    
    // 字符集（数字 + 十六进制）
    const chars = '0123456789ABCDEF'
    const getRandomChar = () => chars[Math.floor(Math.random() * chars.length)]

    // 绘制函数
    const draw = () => {
      // 半透明黑色覆盖（创建拖尾效果）
      ctx.fillStyle = 'rgba(10, 10, 11, 0.05)'
      ctx.fillRect(0, 0, canvas.width, canvas.height)

      // 设置字体和颜色
      ctx.font = '14px "JetBrains Mono", monospace'
      
      // 绘制每一列
      for (let i = 0; i < drops.length; i++) {
        const char = getRandomChar()
        const x = i * 20
        const y = drops[i] * 20

        // 头部字符（亮绿色）
        ctx.fillStyle = '#00ff88'
        ctx.shadowBlur = 10
        ctx.shadowColor = '#00ff88'
        ctx.fillText(char, x, y)

        // 尾部字符（半透明）
        ctx.shadowBlur = 0
        ctx.fillStyle = 'rgba(0, 255, 136, 0.3)'
        ctx.fillText(getRandomChar(), x, y - 20)
        ctx.fillStyle = 'rgba(0, 255, 136, 0.15)'
        ctx.fillText(getRandomChar(), x, y - 40)

        // 重置或下落
        if (y > canvas.height && Math.random() > 0.975) {
          drops[i] = 0
        }
        drops[i] += 0.5
      }

      animationRef.current = requestAnimationFrame(draw)
    }

    draw()

    return () => {
      window.removeEventListener('resize', resize)
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current)
      }
    }
  }, [enabled])

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        width: '100%',
        height: '100%',
        zIndex: 1,
        pointerEvents: 'none',
        opacity: 0.4,
        display: enabled ? 'block' : 'none',
      }}
    />
  )
}
