import React from 'react';

const MiniDonutChart = ({ value, size = 60, color = '#00d4ff' }) => {
  const radius = 25;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (value / 100) * circumference;
  
  return (
    <svg width={size} height={size} style={{ display: 'block' }}>
      <circle
        cx="30"
        cy="30"
        r={radius}
        fill="none"
        stroke="rgba(0, 212, 255, 0.1)"
        strokeWidth="4"
      />
      <circle
        cx="30"
        cy="30"
        r={radius}
        fill="none"
        stroke={color}
        strokeWidth="4"
        strokeDasharray={circumference}
        strokeDashoffset={strokeDashoffset}
        transform="rotate(-90 30 30)"
        className="animated-ring"
        style={{
          filter: `drop-shadow(0 0 6px ${color}80)`,
        }}
      />
      <text
        x="30"
        y="35"
        textAnchor="middle"
        fill="#f1f5f9"
        fontSize="14"
        fontWeight="700"
        fontFamily="var(--font-mono)"
      >
        {value}%
      </text>
    </svg>
  );
};

export default MiniDonutChart;
