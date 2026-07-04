import React from 'react';
import '../styles/theme.css';

const LiveIndicator = ({ lastUpdate }) => {
  return (
    <div className="live-indicator">
      <span className="live-dot"></span>
      <span>Live</span>
      {lastUpdate && (
        <span style={{ marginLeft: '8px', color: 'var(--text-muted)', fontSize: '10px' }}>
          {lastUpdate}
        </span>
      )}
    </div>
  );
};

export default LiveIndicator;
