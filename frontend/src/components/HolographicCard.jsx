import { useState, useRef } from 'react'
import './HolographicCard.css'

export default function HolographicCard({
  children,
  className = '',
  intensity = 15,
  noTilt = false,
  bare = false,
}) {
  const [transform, setTransform] = useState('')
  const cardRef = useRef(null)

  const handleMouseMove = (e) => {
    if (!cardRef.current) return

    const rect = cardRef.current.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top

    const centerX = rect.width / 2
    const centerY = rect.height / 2

    const rotateX = ((y - centerY) / centerY) * -intensity
    const rotateY = ((x - centerX) / centerX) * intensity

    setTransform(`perspective(1000px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale3d(1.02, 1.02, 1.02)`)
  }

  const handleMouseLeave = () => {
    setTransform(`perspective(1000px) rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)`)
  }

  const mouseProps = noTilt
    ? {}
    : { onMouseMove: handleMouseMove, onMouseLeave: handleMouseLeave }

  return (
    <div
      ref={cardRef}
      className={`holographic-card ${bare ? 'bare' : ''} ${className}`}
      style={noTilt ? {} : { transform }}
      {...mouseProps}
    >
      {!bare && <div className="holographic-scanline" />}
      {!bare && <div className="holographic-border" />}
      <div className="holographic-content">{children}</div>
      {!bare && (
        <>
          <div className="holographic-corner holographic-corner-tl" />
          <div className="holographic-corner holographic-corner-tr" />
          <div className="holographic-corner holographic-corner-bl" />
          <div className="holographic-corner holographic-corner-br" />
        </>
      )}
    </div>
  )
}