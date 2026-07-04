import { useEffect, useState, useRef } from 'react'
import './RadialGauge.css'

export default function RadialGauge({
  value = 0,
  max = 100,
  label = '',
  sub = '',
  color = '#00ff88',
  size = 140,
  thickness = 8,
  suffix = '',
  decimals = 0,
}) {
  const [displayValue, setDisplayValue] = useState(0)
  const animationRef = useRef(null)
  const startTime = useRef(null)
  const duration = 800

  useEffect(() => {
    startTime.current = null
    if (animationRef.current) cancelAnimationFrame(animationRef.current)

    const animate = (timestamp) => {
      if (!startTime.current) startTime.current = timestamp
      const progress = timestamp - startTime.current
      const pct = Math.min(progress / duration, 1)
      const eased = 1 - Math.pow(1 - pct, 4)
      setDisplayValue(value * eased)

      if (pct < 1) {
        animationRef.current = requestAnimationFrame(animate)
      } else {
        setDisplayValue(value)
      }
    }
    animationRef.current = requestAnimationFrame(animate)

    return () => {
      if (animationRef.current) cancelAnimationFrame(animationRef.current)
    }
  }, [value])

  const radius = (size - thickness) / 2
  const circumference = 2 * Math.PI * radius
  const percent = Math.min(displayValue / max, 1)
  const dashOffset = circumference * (1 - percent)
  const gradientId = `gauge-grad-${color.replace('#', '')}-${Math.random().toString(36).slice(2, 8)}`

  return (
    <div className="radial-gauge" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="radial-gauge-svg">
        <defs>
          <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={color} stopOpacity="1" />
            <stop offset="100%" stopColor={color} stopOpacity="0.4" />
          </linearGradient>
        </defs>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="rgba(255, 255, 255, 0.05)"
          strokeWidth={thickness}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={`url(#${gradientId})`}
          strokeWidth={thickness}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
          style={{
            filter: `drop-shadow(0 0 6px ${color}80)`,
            transition: 'stroke-dashoffset 0.1s ease-out',
          }}
        />
        <circle
          cx={size / 2 + radius * Math.cos((percent * 360 - 90) * Math.PI / 180)}
          cy={size / 2 + radius * Math.sin((percent * 360 - 90) * Math.PI / 180)}
          r={thickness / 2 + 1}
          fill={color}
          style={{
            filter: `drop-shadow(0 0 8px ${color})`,
          }}
        />
      </svg>
      <div className="radial-gauge-center">
        <div className="radial-gauge-value" style={{ color, textShadow: `0 0 20px ${color}80` }}>
          {displayValue.toFixed(decimals)}{suffix}
        </div>
        {label && <div className="radial-gauge-label">{label}</div>}
        {sub && <div className="radial-gauge-sub">{sub}</div>}
      </div>
    </div>
  )
}