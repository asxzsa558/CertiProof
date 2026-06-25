import { useState, useRef } from 'react'
import './HolographicCard.css'

export default function HolographicCard({ children, className = '', intensity = 15 }) {
  const [transform, setTransform] = useState('')
  const cardRef = useRef(null)

  const handleMouseMove = (e) => {
    if (!cardRef.current) return

    const rect = cardRef.current.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top

    // 计算旋转角度
    const centerX = rect.width / 2
    const centerY = rect.height / 2
    
    const rotateX = ((y - centerY) / centerY) * -intensity
    const rotateY = ((x - centerX) / centerX) * intensity

    setTransform(`perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale3d(1.02, 1.02, 1.02)`)
  }

  const handleMouseLeave = () => {
    setTransform('perspective(1000px) rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)')
  }

  return (
    <div
      ref={cardRef}
      className={`holographic-card ${className}`}
      style={{ transform }}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
    >
      {/* 扫描线效果 */}
      <div className="holographic-scanline" />
      
      {/* 边框发光 */}
      <div className="holographic-border" />
      
      {/* 内容 */}
      <div className="holographic-content">
        {children}
      </div>
      
      {/* 四角装饰 */}
      <div className="holographic-corner holographic-corner-tl" />
      <div className="holographic-corner holographic-corner-tr" />
      <div className="holographic-corner holographic-corner-bl" />
      <div className="holographic-corner holographic-corner-br" />
    </div>
  )
}
