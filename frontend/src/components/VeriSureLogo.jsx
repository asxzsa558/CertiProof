import './VeriSureLogo.css'

function VeriSureLogo({ size = 56, className = '' }) {
  return (
    <div className={`logo-container ${className}`} style={{ width: size, height: size }}>
      <div className="logo-coin">
        {/* 硬币侧面层 - 多层堆叠产生厚度 */}
        <div className="coin-edge coin-edge-1" />
        <div className="coin-edge coin-edge-2" />
        <div className="coin-edge coin-edge-3" />
        <div className="coin-edge coin-edge-4" />
        {/* 正面 - Logo */}
        <div className="coin-face">
          <img src="/verisure-logo.svg" alt="CertiProof" className="logo-img" />
        </div>
      </div>
    </div>
  )
}

export default VeriSureLogo
