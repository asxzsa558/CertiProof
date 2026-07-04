import React from 'react';
import '../styles/theme.css';

const Card = ({ 
  children, 
  title, 
  live = false, 
  className = '',
  onClick 
}) => {
  return (
    <div 
      className={`argus-card ${className}`}
      onClick={onClick}
      style={onClick ? { cursor: 'pointer' } : {}}
    >
      {title && (
        <div className="card-header">
          <span className="card-title">{title}</span>
          {live && (
            <div className="live-indicator">
              <span className="live-dot"></span>
              Live
            </div>
          )}
        </div>
      )}
      <div className="card-content" style={{ padding: '16px' }}>
        {children}
      </div>
    </div>
  );
};

export default Card;
