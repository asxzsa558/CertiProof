import React from 'react';

const MiniLineChart = ({ data, color = '#00d4ff', height = 40, min = 0, max = 100 }) => {
  if (!data || data.length === 0) return null;

  const range = max - min || 1;
  const width = 100;

  const points = data.map((value, index) => {
    const x = data.length === 1 ? width / 2 : (index / (data.length - 1)) * width;
    const clamped = Math.min(max, Math.max(min, value));
    const y = height - ((clamped - min) / range) * (height - 8) - 4;
    return `${x},${y}`;
  }).join(' ');

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      style={{ width: '100%', height: `${height}px` }}
    >
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="2"
        className="animated-line"
        style={{
          filter: `drop-shadow(0 0 4px ${color}80)`,
        }}
      />
      {data.map((value, index) => {
        const x = data.length === 1 ? width / 2 : (index / (data.length - 1)) * width
        const clamped = Math.min(max, Math.max(min, value))
        const y = height - ((clamped - min) / range) * (height - 8) - 4
        return <rect key={`${index}-${value}`} x={x - 0.4} y={y - 2} width="0.8" height="4" rx="0.4" fill={index === data.length - 1 ? '#fbbf24' : color} />
      })}
    </svg>
  );
};

export default MiniLineChart;
